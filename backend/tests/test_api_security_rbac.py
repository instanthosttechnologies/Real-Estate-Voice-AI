import json
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import require_role
from app.api.v1.admin import list_conversation_priority_table, list_total_customer_details_table
from app.api.v1.auth import login_user, register_user
from app.api.v1.ingestion import rollback_batch
from app.api.v1.super_owner import list_system_audit_logs, read_private_transcript, stream_private_audio
from app.core.security import encrypt_transcript, hash_password
from app.db.base import Base
from app.models import AuditLog, Conversation, Customer, User
from app.schemas.auth import UserLoginRequest, UserRegisterRequest
from app.schemas.ingestion import ConflictResolutionStrategy
from app.services.ingestion.pipeline import execute_ingestion_batch


class DummyClient:
    host = "192.168.1.100"


class DummyRequest:
    client = DummyClient()
    headers = {"user-agent": "pytest-security-suite/1.0"}


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_auth_registration_and_login(db_session: Session):
    # 1. Register
    reg_req = UserRegisterRequest(
        email="customer@realty.com",
        password="CustomerPassword2026!",
        role="customer"
    )
    registered = register_user(reg_req, db_session)
    assert registered.email == "customer@realty.com"
    assert registered.role == "customer"

    # 2. Login
    login_req = UserLoginRequest(
        email="customer@realty.com",
        password="CustomerPassword2026!"
    )
    token_resp = login_user(login_req, db_session)
    assert token_resp.access_token is not None
    assert token_resp.role == "customer"

    # 3. Wrong password fails
    wrong_req = UserLoginRequest(
        email="customer@realty.com",
        password="WrongPassword!"
    )
    with pytest.raises(HTTPException) as exc_info:
        login_user(wrong_req, db_session)
    assert exc_info.value.status_code == 401


def test_role_boundary_enforcement():
    customer = User(id=uuid.uuid4(), email="cust@realtor.com", role="customer", is_active=True, hashed_password="x")
    admin = User(id=uuid.uuid4(), email="admin@realtor.com", role="admin", is_active=True, hashed_password="x")
    super_owner = User(id=uuid.uuid4(), email="owner@realtor.com", role="super_owner", is_active=True, hashed_password="x")

    # Customer forbidden from Admin endpoints
    admin_gate = require_role(["admin", "super_owner"])
    with pytest.raises(HTTPException) as exc1:
        admin_gate(customer)
    assert exc1.value.status_code == 403

    # Admin allowed for Admin endpoints
    assert admin_gate(admin) == admin

    # Admin and Customer forbidden from Super Owner endpoints
    super_gate = require_role(["super_owner"])
    with pytest.raises(HTTPException) as exc2:
        super_gate(customer)
    assert exc2.value.status_code == 403

    with pytest.raises(HTTPException) as exc3:
        super_gate(admin)
    assert exc3.value.status_code == 403

    # Super Owner allowed for Super Owner endpoints
    assert super_gate(super_owner) == super_owner


def test_transcript_isolation_and_super_owner_auditing(db_session: Session):
    admin = User(email="agent@realtor.com", hashed_password="x", role="admin")
    super_owner = User(email="owner@realtor.com", hashed_password="x", role="super_owner")
    customer_user = User(email="alice@realtor.com", hashed_password="x", role="customer")
    db_session.add_all([admin, super_owner, customer_user])
    db_session.flush()

    customer = Customer(
        user_id=customer_user.id,
        full_name="Alice Smith",
        phone="+1-555-0199",
    )
    db_session.add(customer)
    db_session.flush()

    plaintext_transcript = "Alice: Looking for 3BHK penthouse with budget $1.5M, flexible move-in."
    conv = Conversation(
        customer_id=customer.id,
        session_id="session-confidential-007",
        duration_seconds=240,
        conversation_priority="urgent",
        audio_storage_path="storage/audio/session-confidential-007.wav",
        encrypted_transcript=encrypt_transcript(plaintext_transcript),
    )
    db_session.add(conv)
    db_session.commit()

    # 1. Admin accesses Conversation Priority Table
    admin_view = list_conversation_priority_table(current_user=admin, db=db_session)
    assert len(admin_view) == 1
    item = admin_view[0]
    assert item.session_id == "session-confidential-007"
    assert item.conversation_priority == "urgent"
    assert item.duration_seconds == 240
    # Verify transcript and audio fields do not exist on Admin schema
    assert not hasattr(item, "encrypted_transcript")
    assert not hasattr(item, "transcript")
    assert not hasattr(item, "audio_storage_path")

    # 2. Super Owner accesses private transcript -> Decrypted & Synchronously Audited
    dummy_req = DummyRequest()
    transcript_resp = read_private_transcript(
        session_id="session-confidential-007",
        request=dummy_req,
        current_user=super_owner,
        db=db_session,
    )
    assert transcript_resp.decrypted_transcript == plaintext_transcript
    assert transcript_resp.access_audited is True

    # 3. Super Owner accesses audio stream reference -> Audited
    audio_resp = stream_private_audio(
        session_id="session-confidential-007",
        request=dummy_req,
        current_user=super_owner,
        db=db_session,
    )
    assert audio_resp.audio_stream_url == "storage/audio/session-confidential-007.wav"

    # 4. Verify Audit Logs were recorded
    logs = list_system_audit_logs(current_user=super_owner, db=db_session)
    assert len(logs) == 2
    actions = [l.action for l in logs]
    assert "ACCESS_PRIVATE_TRANSCRIPT" in actions
    assert "STREAM_PRIVATE_AUDIO" in actions
    assert logs[0].resource_id == "session-confidential-007"
    assert logs[0].ip_address == "192.168.1.100"


def test_super_owner_rollback_api(db_session: Session):
    owner = User(email="owner@realty.com", hashed_password="x", role="super_owner")
    db_session.add(owner)
    db_session.commit()

    csv_data = """Developer,ProjectName,City,Zip,Tower,FlatNo,Beds,AreaSqft,Cost
DevCorp,GreenView,Denver,80202,T1,101,2BHK,900,450000
"""
    mappings = {
        "Developer": "company_name",
        "ProjectName": "project_name",
        "City": "city",
        "Zip": "postal_code",
        "Tower": "property_name",
        "FlatNo": "unit_number",
        "Beds": "configuration_type",
        "AreaSqft": "carpet_area_sqft",
        "Cost": "base_price",
    }
    ingest_res = execute_ingestion_batch(
        db=db_session,
        content=csv_data.encode("utf-8"),
        filename="test.csv",
        confirmed_mappings=mappings,
        conflict_strategy=ConflictResolutionStrategy.NEW_VERSION,
        user_id=owner.id,
    )
    assert ingest_res.imported_rows == 1

    # Execute rollback
    rb_res = rollback_batch(
        batch_id=ingest_res.batch_id,
        current_user=owner,
        db=db_session,
    )
    assert rb_res.status == "rolled_back"
    assert rb_res.reverted_records_count > 0
