import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.api.deps import require_role
from app.api.v1.admin import (
    list_conversation_priority_table,
    list_total_customer_details_table,
)
from app.api.v1.auth import login_user, logout_user, refresh_session, register_user
from app.api.v1.customer import (
    get_customer_requirements,
    list_customer_leads,
    update_customer_requirements,
)
from app.api.v1.super_owner import (
    read_private_transcript,
    stream_private_audio,
)
from app.core.security import (
    create_access_token,
    encrypt_transcript,
    login_rate_limiter,
    validate_password_strength,
)
from app.db.base import Base
from app.main import app
from app.models import (
    AuditLog,
    Conversation,
    Customer,
    Lead,
    RefreshToken,
    User,
)
from app.models.audit_log import AuditLogTamperingError
from app.schemas.auth import (
    LogoutRequest,
    RefreshTokenRequest,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.customer import CustomerRequirementUpdateRequest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class DummyRequest:
    def __init__(self, ip: str = "127.0.0.1"):
        class Client:
            host = ip

        self.client = Client()
        self.headers = {"user-agent": "pytest-phase4-security/1.0"}


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


# =============================================================================
# 1. Password Complexity & Validation Tests
# =============================================================================


def test_password_strength_validation():
    # Too short (< 8 chars)
    with pytest.raises(ValueError, match="at least 8 characters"):
        validate_password_strength("Short1!")

    # Missing uppercase
    with pytest.raises(ValueError, match="uppercase"):
        validate_password_strength("lowercase123!")

    # Missing lowercase
    with pytest.raises(ValueError, match="lowercase"):
        validate_password_strength("UPPERCASE123!")

    # Missing digit
    with pytest.raises(ValueError, match="digit"):
        validate_password_strength("NoDigitsHere!")

    # Missing special character
    with pytest.raises(ValueError, match="special character"):
        validate_password_strength("NoSpecialChar123")

    # Valid strong password
    validate_password_strength("Valid#Password2026")


# =============================================================================
# 2. Registration & Customer Auto-Link Tests
# =============================================================================


def test_registration_and_customer_auto_link(db_session: Session):
    req = DummyRequest("10.0.0.1")
    reg_req = UserRegisterRequest(
        email="raj.verma@example.com",
        password="Secure#Password2026",
        role="customer",
        full_name="Raj Verma",
        phone="+91-9876543210",
    )
    user = register_user(reg_req, db_session, req)
    assert user.id is not None
    assert user.email == "raj.verma@example.com"
    assert user.role == "customer"

    # Verify linked customer profile created
    cust = db_session.query(Customer).filter(Customer.user_id == user.id).first()
    assert cust is not None
    assert cust.full_name == "Raj Verma"
    assert cust.phone == "+91-9876543210"

    # Duplicate registration must fail
    with pytest.raises(HTTPException) as exc:
        register_user(reg_req, db_session, req)
    assert exc.value.status_code == 400


# =============================================================================
# 3. Login Brute-Force Rate Limiting & Lockout Tests
# =============================================================================


def test_login_brute_force_rate_limiting(db_session: Session):
    ip = "192.168.10.50"
    req = DummyRequest(ip)
    email = "target.user@realty.com"

    reg_req = UserRegisterRequest(
        email=email,
        password="Master#Key2026",
        role="customer",
    )
    register_user(reg_req, db_session, req)

    wrong_req = UserLoginRequest(email=email, password="WrongPassword#1")

    # Clear any previous test attempts
    login_rate_limiter.reset(f"{email}:{ip}")

    # Attempts 1 to 4 should fail with 401
    for attempt in range(1, 5):
        with pytest.raises(HTTPException) as exc:
            login_user(wrong_req, db_session, req)
        assert exc.value.status_code == 401
        assert "Incorrect email or password" in exc.value.detail

    # 5th failed attempt triggers 429 lockout
    with pytest.raises(HTTPException) as exc5:
        login_user(wrong_req, db_session, req)
    assert exc5.value.status_code == 429
    assert "Too many failed login attempts" in exc5.value.detail

    # 6th attempt while locked out is rejected immediately with 429
    with pytest.raises(HTTPException) as exc6:
        login_user(wrong_req, db_session, req)
    assert exc6.value.status_code == 429

    # Reset limiter simulates lockout expiry
    login_rate_limiter.reset(f"{email}:{ip}")

    # Correct login succeeds and issues short-lived access token + refresh token
    correct_req = UserLoginRequest(email=email, password="Master#Key2026")
    resp = login_user(correct_req, db_session, req)
    assert resp.access_token is not None
    assert resp.refresh_token is not None
    assert resp.expires_in == 900  # 15 minutes


# =============================================================================
# 4. Refresh Token Rotation & Replay Attack Defense Tests
# =============================================================================


def test_refresh_token_rotation_and_replay_detection(db_session: Session):
    req = DummyRequest("10.0.0.5")
    email = "investor@realty.com"
    reg_req = UserRegisterRequest(
        email=email, password="Invest#Password2026", role="customer"
    )
    user = register_user(reg_req, db_session, req)

    login_resp = login_user(
        UserLoginRequest(email=email, password="Invest#Password2026"), db_session, req
    )
    token_1 = login_resp.refresh_token

    # 1. Rotate token_1 -> yields token_2, marks token_1 revoked
    refresh_req_1 = RefreshTokenRequest(refresh_token=token_1)
    rotate_resp_1 = refresh_session(refresh_req_1, db_session, req)
    token_2 = rotate_resp_1.refresh_token
    assert token_2 != token_1

    # 2. Rotate token_2 -> yields token_3, marks token_2 revoked
    refresh_req_2 = RefreshTokenRequest(refresh_token=token_2)
    rotate_resp_2 = refresh_session(refresh_req_2, db_session, req)
    token_3 = rotate_resp_2.refresh_token
    assert token_3 != token_2

    # 3. REPLAY ATTACK: Attacker presents already-revoked token_1!
    # System MUST detect replay attack, invalidate ALL active tokens for this user, and return 401
    replay_req = RefreshTokenRequest(refresh_token=token_1)
    with pytest.raises(HTTPException) as exc_replay:
        refresh_session(replay_req, db_session, req)
    assert exc_replay.value.status_code == 401
    assert "Revoked refresh token presented" in exc_replay.value.detail

    # Verify that token_3 was also revoked as part of the replay attack mitigation
    token_3_record = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .first()
    )
    assert token_3_record is None  # All active tokens were revoked


# =============================================================================
# 5. Logout & Session Revocation Tests
# =============================================================================


def test_logout_revocation(db_session: Session):
    req = DummyRequest("10.0.0.8")
    email = "logout.test@realty.com"
    register_user(
        UserRegisterRequest(email=email, password="Logout#Pass2026", role="customer"),
        db_session,
        req,
    )
    login_resp = login_user(
        UserLoginRequest(email=email, password="Logout#Pass2026"), db_session, req
    )
    refresh_token = login_resp.refresh_token

    user = db_session.query(User).filter(User.email == email).first()

    # Logout
    logout_resp = logout_user(
        LogoutRequest(refresh_token=refresh_token),
        current_user=user,
        db=db_session,
        req=req,
    )
    assert "Successfully logged out" in logout_resp.message

    # Attempting to refresh with the logged out token must fail
    with pytest.raises(HTTPException) as exc:
        refresh_session(
            RefreshTokenRequest(refresh_token=refresh_token), db_session, req
        )
    assert exc.value.status_code == 401


# =============================================================================
# 6. Customer RBAC & IDOR Prevention Tests
# =============================================================================


def test_customer_idor_prevention(db_session: Session):
    req = DummyRequest()
    # Create Customer Alice
    alice_user = register_user(
        UserRegisterRequest(
            email="alice@realty.com",
            password="Alice#Password2026",
            role="customer",
            full_name="Alice Smith",
            phone="+91-9111111111",
        ),
        db_session,
        req,
    )
    alice_cust = (
        db_session.query(Customer).filter(Customer.user_id == alice_user.id).first()
    )
    alice_cust.is_verified = True
    db_session.commit()

    # Create Customer Bob
    bob_user = register_user(
        UserRegisterRequest(
            email="bob@realty.com",
            password="Bob#Password2026",
            role="customer",
            full_name="Bob Jones",
            phone="+91-9222222222",
        ),
        db_session,
        req,
    )
    bob_cust = (
        db_session.query(Customer).filter(Customer.user_id == bob_user.id).first()
    )

    # Alice creates requirements
    alice_req = CustomerRequirementUpdateRequest(
        preferred_city="Bengaluru",
        preferred_location="Whitefield",
        preferred_configuration="3BHK",
        budget_min=Decimal(12000000),
        budget_max=Decimal(18000000),
        currency="INR",
        purchase_timeline="immediate",
        required_amenities=["Clubhouse", "Gym"],
    )
    update_customer_requirements(alice_req, current_customer=alice_cust, db=db_session)

    # Bob fetches requirements -> MUST receive his own, NOT Alice's
    bob_view = get_customer_requirements(current_customer=bob_cust, db=db_session)
    assert bob_view is None

    # Bob's own leads list is empty, Alice has 1 lead
    assert len(list_customer_leads(current_customer=bob_cust, db=db_session)) == 0
    alice_leads = list_customer_leads(current_customer=alice_cust, db=db_session)
    assert len(alice_leads) == 1
    assert alice_leads[0].customer_id == alice_cust.id
    assert alice_leads[0].preferred_location == "Whitefield"
    assert alice_leads[0].preferred_config == "3BHK"


# =============================================================================
# 7. Admin Views, Priority Ordering, and Zero-Leakage Tests
# =============================================================================


def test_admin_conversation_priority_ordering_and_zero_leakage(db_session: Session):
    admin = User(email="admin.triage@realty.com", role="admin", hashed_password="x")
    db_session.add(admin)

    cust = Customer(full_name="Priority Client", phone="+91-9333333333")
    db_session.add(cust)
    db_session.flush()

    now = datetime.now(UTC)

    # Seed conversations across priorities and timestamps
    conv_low = Conversation(
        session_id="conv-low",
        customer_id=cust.id,
        duration_seconds=120,
        conversation_priority="low",
        encrypted_transcript=encrypt_transcript("Secret low priority transcript"),
        created_at=now - timedelta(minutes=10),
    )
    conv_high_old = Conversation(
        session_id="conv-high-old",
        customer_id=cust.id,
        duration_seconds=300,
        conversation_priority="high",
        encrypted_transcript=encrypt_transcript("Secret high priority old transcript"),
        created_at=now - timedelta(minutes=20),
    )
    conv_high_new = Conversation(
        session_id="conv-high-new",
        customer_id=cust.id,
        duration_seconds=350,
        conversation_priority="high",
        encrypted_transcript=encrypt_transcript("Secret high priority new transcript"),
        created_at=now - timedelta(minutes=5),
    )
    conv_med = Conversation(
        session_id="conv-medium",
        customer_id=cust.id,
        duration_seconds=180,
        conversation_priority="medium",
        encrypted_transcript=encrypt_transcript("Secret medium transcript"),
        created_at=now - timedelta(minutes=15),
    )
    conv_urgent = Conversation(
        session_id="conv-urgent",
        customer_id=cust.id,
        duration_seconds=400,
        conversation_priority="urgent",
        encrypted_transcript=encrypt_transcript("Secret urgent transcript"),
        created_at=now - timedelta(minutes=2),
    )
    db_session.add_all([conv_low, conv_high_old, conv_high_new, conv_med, conv_urgent])
    db_session.commit()

    # Query Conversation Priority Table
    items = list_conversation_priority_table(current_user=admin, db=db_session)
    assert len(items) == 5

    # VERIFY SORT ORDER: Urgent -> High (newest first) -> Medium -> Low
    expected_order = [
        "conv-urgent",  # Urgent priority (1)
        "conv-high-new",  # High priority, newer (5 mins ago)
        "conv-high-old",  # High priority, older (20 mins ago)
        "conv-medium",  # Medium priority
        "conv-low",  # Low priority
    ]
    actual_order = [item.session_id for item in items]
    assert actual_order == expected_order

    # VERIFY ZERO LEAKAGE: Neither transcript nor audio fields exist in the response
    for item in items:
        item_dict = item.model_dump()
        assert "encrypted_transcript" not in item_dict
        assert "decrypted_transcript" not in item_dict
        assert "transcript" not in item_dict
        assert "audio_storage_path" not in item_dict
        assert "audio_stream_url" not in item_dict

    # VERIFY TOTAL CUSTOMER DETAILS TABLE SORTS CONSISTENTLY: Urgent -> High -> Medium -> Low
    c_urgent = Customer(full_name="Urgent Cust", phone="+91-1111111111")
    c_low = Customer(full_name="Low Cust", phone="+91-2222222222")
    c_high = Customer(full_name="High Cust", phone="+91-3333333333")
    db_session.add_all([c_urgent, c_low, c_high])
    db_session.flush()

    db_session.add(Lead(customer_id=c_urgent.id, lead_priority="urgent"))
    db_session.add(Lead(customer_id=c_low.id, lead_priority="low"))
    db_session.add(Lead(customer_id=c_high.id, lead_priority="high"))
    db_session.commit()

    cust_items = list_total_customer_details_table(current_user=admin, db=db_session)
    priorities = [c.lead_priority for c in cust_items if c.lead_priority]
    assert priorities == ["urgent", "high", "low"]


# =============================================================================
# 8. Admin Strict Rejection from Transcripts, Audio & Customer Private Routes
# =============================================================================


def test_admin_strict_rejection_from_privileged_and_private_routes(db_session: Session):
    admin = User(
        id=uuid.uuid4(),
        email="admin.auditor@realty.com",
        role="admin",
        hashed_password="x",
    )
    db_session.add(admin)
    db_session.commit()

    # 1. Admin rejected by Super Owner role gate
    super_gate = require_role(["super_owner"])
    with pytest.raises(HTTPException) as exc1:
        super_gate(admin)
    assert exc1.value.status_code == 403

    # 2. Admin rejected by Customer role gate
    customer_gate = require_role(["customer"])
    with pytest.raises(HTTPException) as exc2:
        customer_gate(admin)
    assert exc2.value.status_code == 403

    # 3. HTTP endpoint level verification with TestClient
    from app.db.session import get_db

    app.dependency_overrides[get_db] = lambda: db_session

    try:
        admin_token = create_access_token(
            {"sub": str(admin.id), "role": admin.role, "email": admin.email}
        )
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Super Owner transcript endpoint returns 403 for Admin
        resp_transcript = client.get(
            "/api/v1/super-owner/conversations/any-session/transcript", headers=headers
        )
        assert resp_transcript.status_code == 403

        # Super Owner audio endpoint returns 403 for Admin
        resp_audio = client.get(
            "/api/v1/super-owner/conversations/any-session/audio", headers=headers
        )
        assert resp_audio.status_code == 403

        # Super Owner audit-logs endpoint returns 403 for Admin
        resp_audit = client.get("/api/v1/super-owner/audit-logs", headers=headers)
        assert resp_audit.status_code == 403

        # Customer profile endpoint returns 403 for Admin
        resp_cust = client.get("/api/v1/customer/profile", headers=headers)
        assert resp_cust.status_code == 403
    finally:
        app.dependency_overrides.clear()


# =============================================================================
# 9. Super Owner Privileged Access & Tamper-Evident Audit Logging
# =============================================================================


def test_super_owner_transcript_access_and_auditing(db_session: Session):
    super_owner = User(
        id=uuid.uuid4(),
        email="owner@enterprise.com",
        role="super_owner",
        hashed_password="x",
    )
    db_session.add(super_owner)

    cust = Customer(full_name="VIP Client", phone="+91-9444444444")
    db_session.add(cust)
    db_session.flush()

    raw_transcript = "[Customer]: Looking for luxury villa in Whitefield.\n[Assistant]: I found 3 luxury villas."
    conv = Conversation(
        session_id="session-vip-101",
        customer_id=cust.id,
        duration_seconds=180,
        conversation_priority="high",
        encrypted_transcript=encrypt_transcript(raw_transcript),
        audio_storage_path="storage/audio/session-vip-101.raw",
    )
    db_session.add(conv)
    db_session.commit()

    dummy_req = DummyRequest("172.16.0.25")

    # Super Owner reads transcript
    transcript_resp = read_private_transcript(
        session_id="session-vip-101",
        request=dummy_req,
        current_user=super_owner,
        db=db_session,
    )
    assert transcript_resp.session_id == "session-vip-101"
    assert transcript_resp.decrypted_transcript == raw_transcript
    assert transcript_resp.access_audited is True

    # Verify immutable audit log record created
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "ACCESS_PRIVATE_TRANSCRIPT",
            AuditLog.resource_id == "session-vip-101",
        )
        .first()
    )
    assert audit is not None
    assert audit.user_id == super_owner.id
    assert audit.user_role == "super_owner"
    assert audit.ip_address == "172.16.0.25"

    # Super Owner requests audio stream URL
    audio_resp = stream_private_audio(
        session_id="session-vip-101",
        request=dummy_req,
        current_user=super_owner,
        db=db_session,
    )
    assert audio_resp.audio_stream_url == "storage/audio/session-vip-101.raw"
    assert audio_resp.access_audited is True

    # Verify audio audit log created
    audio_audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "STREAM_PRIVATE_AUDIO",
            AuditLog.resource_id == "session-vip-101",
        )
        .first()
    )
    assert audio_audit is not None
    assert audio_audit.user_id == super_owner.id


# =============================================================================
# 10. Audit Log Immutability (Database & ORM Level)
# =============================================================================


def test_audit_log_immutability(db_session: Session):
    audit = AuditLog(
        user_role="super_owner",
        action="TEST_IMMUTABLE_ACTION",
        resource_type="system",
        resource_id="res-1",
        timestamp=datetime.now(UTC),
    )
    db_session.add(audit)
    db_session.commit()

    # Attempt ORM-level update -> Must raise AuditLogTamperingError
    audit.action = "TAMPERED_ACTION"
    with pytest.raises(
        AuditLogTamperingError, match="strictly immutable and cannot be updated"
    ):
        db_session.commit()
    db_session.rollback()

    # Attempt ORM-level delete -> Must raise AuditLogTamperingError
    audit_fresh = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "TEST_IMMUTABLE_ACTION")
        .first()
    )
    db_session.delete(audit_fresh)
    with pytest.raises(
        AuditLogTamperingError, match="strictly immutable and cannot be deleted"
    ):
        db_session.commit()
    db_session.rollback()

    # Attempt raw SQL update on SQLite trigger -> Must raise exception
    with pytest.raises(Exception):
        db_session.execute(
            text(
                "UPDATE audit_logs SET action = 'SQL_TAMPERED' WHERE resource_id = 'res-1'"
            )
        )
        db_session.commit()
    db_session.rollback()

    # Attempt raw SQL delete on SQLite trigger -> Must raise exception
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM audit_logs WHERE resource_id = 'res-1'"))
        db_session.commit()
    db_session.rollback()


# =============================================================================
# 11. WebSocket Customer Session Anti-Hijacking Test
# =============================================================================


def test_websocket_session_hijacking_rejection(db_session: Session):
    # Customer Alice
    alice_user = User(email="alice.ws@realty.com", role="customer", hashed_password="x")
    db_session.add(alice_user)
    db_session.flush()
    alice_cust = Customer(
        user_id=alice_user.id,
        full_name="Alice WS",
        phone="+91-9555555555",
        email=alice_user.email,
    )
    db_session.add(alice_cust)
    db_session.flush()

    # Customer Bob
    bob_user = User(email="bob.ws@realty.com", role="customer", hashed_password="x")
    db_session.add(bob_user)
    db_session.flush()
    bob_cust = Customer(
        user_id=bob_user.id,
        full_name="Bob WS",
        phone="+91-9666666666",
        email=bob_user.email,
    )
    db_session.add(bob_cust)
    db_session.flush()

    # Existing conversation owned by Alice
    session_id = "alice-private-voice-session"
    conv = Conversation(
        session_id=session_id,
        customer_id=alice_cust.id,
        duration_seconds=60,
        conversation_priority="medium",
        encrypted_transcript=encrypt_transcript("[Alice]: Private conversation."),
    )
    db_session.add(conv)
    db_session.commit()

    # Bob tries to connect to Alice's session_id via WebSocket
    bob_token = create_access_token(
        {"sub": str(bob_user.id), "role": "customer", "email": bob_user.email}
    )

    from app.api.v1 import voice_ws

    original_get_db = voice_ws.get_db_session
    voice_ws.get_db_session = lambda: db_session

    try:
        client = TestClient(app)
        # Attempt connection with initial auth handshake
        with client.websocket_connect(f"/api/v1/ws/voice/{session_id}") as ws:
            # Handshake with Bob's token
            ws.send_text(json.dumps({"type": "auth", "token": bob_token}))
            # The WebSocket MUST close with code 1008 Policy Violation
            msg = ws.receive()
            assert msg["type"] == "websocket.close"
            assert msg["code"] == 1008
    finally:
        voice_ws.get_db_session = original_get_db


def test_websocket_query_string_token_disabled(db_session: Session):
    """
    Verifies that WebSocket connections ignore/reject query-string tokens and require
    an explicit initial JSON handshake {"type": "auth", "token": "..."}.
    """
    client = TestClient(app)
    # Connecting with query string token and immediately sending a non-auth frame must be closed
    with client.websocket_connect(
        "/api/v1/ws/voice/sess_query_reject?token=fake_token"
    ) as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 1008
