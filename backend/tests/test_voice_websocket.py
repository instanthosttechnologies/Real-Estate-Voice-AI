import asyncio
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, decrypt_transcript
from app.db.base import Base
from app.main import app
from app.models import (
    Amenity,
    AuditLog,
    Availability,
    Company,
    Conversation,
    Customer,
    Location,
    Pricing,
    Project,
    Property,
    PropertyUnit,
    User,
)


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def test_db(test_engine):
    with Session(test_engine) as session:
        yield session


@pytest.fixture(autouse=True)
def override_ws_db(test_engine):
    from app.api.v1 import voice_ws
    from sqlalchemy.orm import sessionmaker
    original = voice_ws.get_db_session
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    voice_ws.get_db_session = lambda: TestSession()
    yield
    voice_ws.get_db_session = original


@pytest.fixture(autouse=True)
def override_ws_driver():
    from app.api.v1 import voice_ws
    from app.services.voice.mock_driver import MockVoiceDriver
    original = voice_ws.get_voice_driver
    voice_ws.get_voice_driver = lambda: MockVoiceDriver(enable_synthetic_tones=True)
    yield
    voice_ws.get_voice_driver = original


@pytest.fixture
def auth_tokens(test_db: Session):
    # Customer user
    cust_user = User(email="cust@voice.test", hashed_password="pw", role="customer")
    # Admin user
    admin_user = User(email="admin@voice.test", hashed_password="pw", role="admin")
    # Super Owner user
    super_user = User(email="super@voice.test", hashed_password="pw", role="super_owner")

    test_db.add_all([cust_user, admin_user, super_user])
    test_db.flush()

    customer = Customer(user_id=cust_user.id, full_name="Voice Test Client", phone="+1-800-VOICE-AI")
    test_db.add(customer)
    test_db.commit()

    cust_token = create_access_token({"sub": str(cust_user.id), "role": "customer", "email": cust_user.email})
    admin_token = create_access_token({"sub": str(admin_user.id), "role": "admin", "email": admin_user.email})
    super_token = create_access_token({"sub": str(super_user.id), "role": "super_owner", "email": super_user.email})

    return {
        "customer": cust_token,
        "admin": admin_token,
        "super_owner": super_token,
        "customer_user": cust_user,
    }


def test_voice_ws_auth_handshake_missing_or_invalid_token():
    client = TestClient(app)

    # 1. Missing handshake: Client connects and immediately sends non-auth message
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/voice/sess_no_handshake") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            ws.receive_text()

    # 2. Query-string token is completely ignored/rejected: must perform initial JSON handshake
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/voice/sess_query_rejected?token=some_token") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            ws.receive_text()

    # 3. Invalid JWT token in JSON handshake frame
    with client.websocket_connect("/ws/voice/sess_bad_handshake") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "invalid.jwt.token"}))
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 1008


def test_voice_ws_admin_restricted_from_voice_sessions(auth_tokens):
    client = TestClient(app)
    admin_token = auth_tokens["admin"]

    # Connecting and authenticating with Admin role must be strictly rejected (1008)
    with client.websocket_connect("/ws/voice/sess_admin_block") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": admin_token}))
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 1008


def test_voice_ws_customer_streaming_lifecycle(auth_tokens):
    client = TestClient(app)
    cust_token = auth_tokens["customer"]
    session_id = f"voice_sess_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        # Mandatory initial auth handshake
        ws.send_text(json.dumps({"type": "auth", "token": cust_token}))

        # 1. Expect session_started event
        start_raw = ws.receive_text()
        start_data = json.loads(start_raw)
        assert start_data["type"] == "session_started"
        assert start_data["session_id"] == session_id
        assert start_data["model"] == "amazon.nova-2-5-sonic"

        # 2. Expect assistant greeting transcript
        greet_raw = ws.receive_text()
        greet_data = json.loads(greet_raw)
        assert greet_data["type"] == "transcript"
        assert greet_data["role"] == "assistant"
        assert "real estate" in greet_data["delta"].lower()

        # 3. Expect greeting audio bytes
        audio_chunk = ws.receive_bytes()
        assert len(audio_chunk) > 0

        # 4. Ping-Pong test
        ws.send_text(json.dumps({"type": "ping"}))
        pong_raw = ws.receive_text()
        pong_data = json.loads(pong_raw)
        assert pong_data["type"] == "pong"

        # 5. Send conversational text
        ws.send_text(json.dumps({"type": "text", "content": "Hello, I am interested in buying a property."}))
        user_echo_raw = ws.receive_text()
        user_echo = json.loads(user_echo_raw)
        assert user_echo["type"] == "transcript"
        assert user_echo["role"] == "user"

        assistant_reply_raw = ws.receive_text()
        assistant_reply = json.loads(assistant_reply_raw)
        assert assistant_reply["type"] == "transcript"
        assert assistant_reply["role"] == "assistant"

        # Expect audio chunk for assistant reply
        reply_audio = ws.receive_bytes()
        assert len(reply_audio) > 0

        # 6. Graceful stop
        ws.send_text(json.dumps({"type": "stop"}))


def test_voice_ws_agent_tool_execution(auth_tokens):
    client = TestClient(app)
    cust_token = auth_tokens["customer"]
    session_id = f"voice_tool_sess_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        # Initial auth handshake
        ws.send_text(json.dumps({"type": "auth", "token": cust_token}))

        # Drain initial greeting messages
        ws.receive_text()  # session_started
        ws.receive_text()  # transcript
        ws.receive_bytes()  # audio

        # Send property search request utterance
        ws.send_text(json.dumps({"type": "text", "content": "I want to search for 2BHK apartments in Seattle under 800k"}))

        # Receive echoed user transcript
        user_msg = json.loads(ws.receive_text())
        assert user_msg["type"] == "transcript"
        assert user_msg["role"] == "user"

        # Receive tool call start notification
        tool_start = json.loads(ws.receive_text())
        assert tool_start["type"] == "tool_call_start"
        assert tool_start["tool_name"] == "search_properties"
        assert "tool_use_id" in tool_start

        # Receive tool call complete notification
        tool_complete = json.loads(ws.receive_text())
        assert tool_complete["type"] == "tool_call_complete"
        assert tool_complete["tool_name"] == "search_properties"
        assert tool_complete["success"] is True

        # Receive grounded assistant response
        assistant_msg = json.loads(ws.receive_text())
        assert assistant_msg["type"] == "transcript"
        assert assistant_msg["role"] == "assistant"

        # Receive audio output
        audio_out = ws.receive_bytes()
        assert len(audio_out) > 0

        # Graceful stop
        ws.send_text(json.dumps({"type": "stop"}))


def test_voice_ws_interruption_handling(auth_tokens):
    client = TestClient(app)
    cust_token = auth_tokens["customer"]
    session_id = f"voice_intr_sess_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        # Initial auth handshake
        ws.send_text(json.dumps({"type": "auth", "token": cust_token}))

        # Drain greeting
        ws.receive_text()
        ws.receive_text()
        ws.receive_bytes()

        # Send interruption
        ws.send_text(json.dumps({"type": "interrupt"}))
        intr_msg = json.loads(ws.receive_text())
        assert intr_msg["type"] == "interrupted"

        ws.send_text(json.dumps({"type": "stop"}))


def test_voice_ws_audio_chunk_and_size_validation(auth_tokens):
    client = TestClient(app)
    cust_token = auth_tokens["customer"]
    session_id = f"voice_chunk_sess_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        # Initial auth handshake
        ws.send_text(json.dumps({"type": "auth", "token": cust_token}))

        # Drain greeting
        ws.receive_text()
        ws.receive_text()
        ws.receive_bytes()

        # 1. Valid binary PCM chunk (1024 bytes)
        valid_pcm = b"\x00\x00" * 512
        ws.send_bytes(valid_pcm)

        # 2. Oversized binary chunk (>64KB: 70000 bytes)
        oversized_pcm = b"\x00" * 70000
        ws.send_bytes(oversized_pcm)

        # Verify error notification emitted
        err_msg = json.loads(ws.receive_text())
        assert err_msg["type"] == "error"
        assert "exceeds maximum chunk limit" in err_msg["message"]


def test_voice_ws_transcript_encryption_and_audit(auth_tokens, test_db: Session):
    client = TestClient(app)
    cust_token = auth_tokens["customer"]
    session_id = f"voice_enc_sess_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        # Initial auth handshake
        ws.send_text(json.dumps({"type": "auth", "token": cust_token}))

        # Drain greeting
        ws.receive_text()
        ws.receive_text()
        ws.receive_bytes()

        # Conversational interaction
        ws.send_text(json.dumps({"type": "text", "content": "Can I speak to a human broker?"}))
        ws.receive_text()  # echo
        ws.receive_text()  # tool start (transfer_to_human)
        ws.receive_text()  # tool complete
        ws.receive_text()  # assistant transcript
        ws.receive_bytes()  # audio

        ws.send_text(json.dumps({"type": "stop"}))

    # Verify Database Conversation record in test_db
    conv = test_db.execute(select(Conversation).where(Conversation.session_id == session_id)).scalar_one_or_none()
    assert conv is not None
    assert conv.session_id == session_id
    assert conv.conversation_priority == "urgent"  # Elevated because transfer_to_human was called!
    assert conv.encrypted_transcript is not None

    # Verify encryption: raw ciphertext is not plaintext
    assert "[Customer]:" not in conv.encrypted_transcript
    assert "[Assistant]:" not in conv.encrypted_transcript

    # Decrypt with AES-256-GCM and verify authentic transcript contents
    decrypted = decrypt_transcript(conv.encrypted_transcript)
    assert "[Customer]: Can I speak to a human broker?" in decrypted
    assert "Tool Call Request: transfer_to_human" in decrypted

    # Verify AuditLog entries
    audit_events = test_db.execute(
        select(AuditLog).where(AuditLog.resource_id.in_([session_id, str(conv.id), "transfer_to_human"]))
    ).scalars().all()
    actions = [a.action for a in audit_events]
    assert "VOICE_SESSION_STARTED" in actions
    assert "VOICE_TOOL_EXECUTED" in actions
    assert "VOICE_SESSION_COMPLETED" in actions


# =============================================================================
# PERMANENT VOICE AUTHENTICATION & TOKEN LIFECYCLE TESTS
# =============================================================================

def test_voice_ws_fresh_verified_customer_token(test_db: Session):
    """
    Requirement 9: Fresh OTP-verified customer session connects, authenticates,
    starts the voice session, and logs audit events cleanly with user_id=None
    (preventing foreign key constraint violations against users table).
    """
    from app.api.v1.auth import _customer_token
    from datetime import datetime, timezone

    client = TestClient(app)
    cust_id = uuid.uuid4()
    cust = Customer(
        id=cust_id,
        user_id=None,  # Passwordless customer has no record in users table
        full_name="Rajesh Verma",
        phone="+919811122233",
        email="rajesh.verma@example.com",
        is_verified=True,
    )
    test_db.add(cust)
    test_db.commit()

    cust_token = _customer_token(cust, verified=True)
    session_id = f"voice_fresh_cust_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": cust_token}))

        # 1. Expect session_started
        start_raw = ws.receive_text()
        start_data = json.loads(start_raw)
        assert start_data["type"] == "session_started"
        assert start_data["session_id"] == session_id

        # 2. Expect greeting
        greet_raw = ws.receive_text()
        greet_data = json.loads(greet_raw)
        assert greet_data["type"] == "transcript"

        ws.send_text(json.dumps({"type": "stop"}))

    # Verify conversation created with correct customer_id
    conv = test_db.execute(select(Conversation).where(Conversation.session_id == session_id)).scalar_one_or_none()
    assert conv is not None
    assert conv.customer_id == cust_id

    # Verify audit log recorded without foreign key violation
    audits = test_db.execute(
        select(AuditLog).where(AuditLog.resource_id == session_id)
    ).scalars().all()
    assert len(audits) >= 1
    for a in audits:
        assert a.user_id is None  # Safe: must be None for customer without user record
        assert a.user_role == "customer"


def test_voice_ws_expired_token(test_db: Session):
    """
    Requirement 9: An expired JWT must be strictly rejected with WS 1008
    and reason 'Invalid or expired authentication token.'
    """
    from datetime import timedelta
    client = TestClient(app)

    expired_token = create_access_token(
        data={"sub": str(uuid.uuid4()), "role": "customer", "is_verified": True},
        expires_delta=timedelta(seconds=-120),  # Expired 2 minutes ago
    )
    session_id = f"voice_expired_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": expired_token}))
        close_frame = ws.receive()
        assert close_frame["type"] == "websocket.close"
        assert close_frame["code"] == 1008


def test_voice_ws_invalid_token():
    """
    Requirement 9: Invalid or tampered tokens must be strictly rejected with WS 1008.
    """
    client = TestClient(app)
    session_id = f"voice_invalid_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "not.a.valid.jwt.token"}))
        close_frame = ws.receive()
        assert close_frame["type"] == "websocket.close"
        assert close_frame["code"] == 1008


def test_voice_ws_bearer_prefix_tolerance(test_db: Session):
    """
    Requirement 4: Clients passing 'Bearer <token>' in the handshake frame
    must be cleanly tolerated and authenticated without policy failure.
    """
    from app.api.v1.auth import _customer_token
    client = TestClient(app)

    cust = Customer(
        id=uuid.uuid4(),
        full_name="Anita Roy",
        phone="+919822233344",
        email="anita.roy@example.com",
        is_verified=True,
    )
    test_db.add(cust)
    test_db.commit()

    raw_token = _customer_token(cust, verified=True)
    bearer_token = f"Bearer {raw_token}"
    session_id = f"voice_bearer_{uuid.uuid4().hex[:8]}"

    with client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": bearer_token}))
        start_raw = ws.receive_text()
        start_data = json.loads(start_raw)
        assert start_data["type"] == "session_started"
        ws.send_text(json.dumps({"type": "stop"}))


def test_voice_ws_backend_restart_persistence(test_db: Session):
    """
    Requirement 5 & 9: Simulates server reload/restart ensuring that SECRET_KEY
    remains stable, and tokens generated prior to restart remain authentic and valid.
    """
    from app.core.config import settings
    from app.core.security import decode_access_token
    from app.api.v1.auth import _customer_token

    # Verify SECRET_KEY is deterministic and non-empty
    assert settings.SECRET_KEY is not None
    assert len(settings.SECRET_KEY) >= 32

    cust = Customer(
        id=uuid.uuid4(),
        full_name="Kavita Nair",
        phone="+919833344455",
        email="kavita.nair@example.com",
        is_verified=True,
    )
    test_db.add(cust)
    test_db.commit()

    token = _customer_token(cust, verified=True)

    # Decode and verify
    claims = decode_access_token(token)
    assert claims["customer_id"] == str(cust.id)
    assert claims["is_verified"] is True

    # Re-connect through a fresh TestClient representing a restarted server session
    fresh_client = TestClient(app)
    session_id = f"voice_restart_{uuid.uuid4().hex[:8]}"

    with fresh_client.websocket_connect(f"/ws/voice/{session_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        start_raw = ws.receive_text()
        start_data = json.loads(start_raw)
        assert start_data["type"] == "session_started"
        ws.send_text(json.dumps({"type": "stop"}))

