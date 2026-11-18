from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.api.v1.auth import (
    login_user,
    onboard_customer,
    request_customer_otp,
    verify_customer_otp,
)
from app.api.v1.customer import (
    get_customer_requirements,
    list_customer_leads,
    list_customer_site_visits,
)
from app.core.security import decode_access_token, hash_password
from app.db.base import Base
from app.models import Customer, Lead, Project, SiteVisit, User
from app.models.company import Company
from app.models.location import Location
from app.schemas.auth import UserLoginRequest
from app.schemas.customer import (
    CustomerOnboardRequest,
    CustomerOTPRequest,
    CustomerOTPVerifyRequest,
)
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class DummyRequest:
    def __init__(self, ip: str = "127.0.0.1"):
        class Client:
            host = ip

        self.client = Client()
        self.headers = {"user-agent": "pytest-customer-onboarding/1.0"}


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


# ============================================================
# 1. CUSTOMER ONBOARDING TESTS
# ============================================================


def test_customer_onboard_success(db_session: Session):
    req = DummyRequest("192.168.1.100")

    onboard_req = CustomerOnboardRequest(
        full_name="Priya Sharma",
        phone="+91-98765-43210",
        email="Priya.Sharma@Example.COM",
    )

    resp = onboard_customer(
        onboard_req,
        db=db_session,
        req=req,
    )

    assert resp.customer_id is not None
    assert resp.full_name == "Priya Sharma"
    assert resp.phone == "+919876543210"
    assert resp.email == "priya.sharma@example.com"
    assert resp.role == "customer"
    assert resp.is_verified is False
    assert resp.token_type == "bearer"

    payload = decode_access_token(resp.access_token)

    assert payload["role"] == "customer"
    assert payload["customer_id"] == str(resp.customer_id)
    assert payload["is_verified"] is False
    # Unverified JWTs must not contain personal information.
    assert "full_name" not in payload
    assert "email" not in payload
    assert "phone" not in payload
    assert payload.get("otp_session") is not None

    db_cust = db_session.get(
        Customer,
        resp.customer_id,
    )

    assert db_cust is not None
    assert db_cust.user_id is None


def test_customer_onboard_validation_errors():

    # Invalid name
    with pytest.raises(ValueError):
        CustomerOnboardRequest(
            full_name="A",
            phone="+919876543210",
            email="test@example.com",
        )

    # Invalid phone number
    with pytest.raises(ValueError):
        CustomerOnboardRequest(
            full_name="Test User",
            phone="12345",
            email="test@example.com",
        )

    # Invalid email
    with pytest.raises(ValueError):
        CustomerOnboardRequest(
            full_name="Test User",
            phone="+919876543210",
            email="invalid-email-format",
        )


# ============================================================
# 2. RETURNING CUSTOMER SECURITY TESTS
# ============================================================


def test_customer_onboard_returning_customer_unverified(
    db_session: Session,
):
    """
    Entering an existing customer's phone/email must not
    automatically grant access to their previous records.
    """

    req = DummyRequest("192.168.1.105")

    existing_cust = Customer(
        full_name="Vikram Seth",
        phone="+919888877777",
        email="vikram@realty.com",
        is_verified=False,
    )

    db_session.add(existing_cust)
    db_session.flush()

    lead = Lead(
        customer_id=existing_cust.id,
        preferred_config="3 BHK",
        preferred_location="Adyar",
        budget_min=Decimal(15000000),
        budget_max=Decimal(20000000),
        lead_priority="high",
        qualification_status="qualified",
    )

    db_session.add(lead)
    db_session.commit()

    onboard_req = CustomerOnboardRequest(
        full_name="Vikram Seth",
        phone="+91 98888 77777",
        email="vikram@realty.com",
    )

    resp = onboard_customer(
        onboard_req,
        db=db_session,
        req=req,
    )

    assert resp.customer_id == existing_cust.id
    assert resp.is_verified is False


def test_unverified_customer_anti_disclosure_routes(
    db_session: Session,
):
    """
    Unverified customers must not see private leads,
    saved requirements, or site visits.
    """

    cust = Customer(
        full_name="Sneha Reddy",
        phone="+919111122222",
        email="sneha@realty.com",
        is_verified=False,
    )

    db_session.add(cust)
    db_session.flush()

    # Private customer lead
    lead = Lead(
        customer_id=cust.id,
        preferred_config="4 BHK Luxury Villa",
        preferred_location="ECR",
        lead_priority="urgent",
        qualification_status="qualified",
    )

    db_session.add(lead)

    # Create company
    company = Company(
        name="Seaside Haven Developers",
        contact_email="contact@seasidehaven.test",
    )

    db_session.add(company)
    db_session.flush()

    # Create project location
    location = Location(
        address_line_1="ECR Main Road",
        city="Chennai",
        state="Tamil Nadu",
        postal_code="600041",
        country="India",
        latitude=Decimal("12.9000000"),
        longitude=Decimal("80.2200000"),
    )

    db_session.add(location)
    db_session.flush()

    # Create project using required foreign keys
    proj = Project(
        company_id=company.id,
        location_id=location.id,
        name="Seaside Haven",
        description="Luxury Villas",
        status="active",
    )

    db_session.add(proj)
    db_session.flush()

    # Private site visit
    visit = SiteVisit(
        customer_id=cust.id,
        project_id=proj.id,
        scheduled_start=(datetime.now(UTC) + timedelta(days=2)),
        scheduled_end=(datetime.now(UTC) + timedelta(days=2, hours=1)),
        status="scheduled",
    )

    db_session.add(visit)
    db_session.commit()

    # Private leads must remain hidden
    leads_result = list_customer_leads(
        current_customer=cust,
        db=db_session,
    )

    assert leads_result == []

    # Saved requirements must remain hidden
    reqs_result = get_customer_requirements(
        current_customer=cust,
        db=db_session,
    )

    assert reqs_result is None

    # Private site visits must remain hidden
    visits_result = list_customer_site_visits(
        current_customer=cust,
        db=db_session,
    )

    assert visits_result == []


# ============================================================
# 3. VOICE AGENT PRIVACY TEST
# ============================================================


@pytest.mark.asyncio
async def test_voice_orchestrator_anti_disclosure_preamble(
    db_session: Session,
):
    """
    The voice AI must not reveal previous customer
    preferences when identity is unverified.
    """

    cust = Customer(
        full_name="Ananya Sen",
        phone="+919333344444",
        email="ananya@realty.com",
        is_verified=False,
    )

    db_session.add(cust)
    db_session.flush()

    lead = Lead(
        customer_id=cust.id,
        preferred_config="2 BHK Penthouse",
        preferred_location="Anna Nagar",
        budget_max=Decimal(12000000),
        lead_priority="high",
        qualification_status="qualified",
    )

    db_session.add(lead)
    db_session.commit()

    driver = MockVoiceDriver()

    orchestrator = VoiceSessionOrchestrator(
        session_id="unverified-sess-001",
        driver=driver,
        db=db_session,
        customer_id=cust.id,
        user_role="customer",
        is_verified=False,
    )

    await orchestrator.start()

    # Corrected: MockVoiceDriver stores prompts by session ID.
    preamble = driver._session_preambles["unverified-sess-001"]

    assert "2 BHK Penthouse" not in preamble
    assert "Anna Nagar" not in preamble

    assert "Unverified session" in preamble or "Fresh session" in preamble


# ============================================================
# 4. CUSTOMER OTP VERIFICATION TEST
# ============================================================


def test_customer_otp_request_and_verification(
    db_session: Session,
    monkeypatch,
):
    """
    Verify secure OTP using a customer bearer token.

    OTP delivery is mocked:
    - No paid SMS or email
    - No plaintext OTP stored
    - No OTP returned by the API
    - Wrong OTP rejected
    - Correct OTP accepted
    """

    from app.api.v1 import auth
    from fastapi.security import HTTPAuthorizationCredentials

    # Use a test-only OTP hashing secret.
    monkeypatch.setenv(
        "OTP_HMAC_SECRET",
        "offline-test-secret-" + "a" * 64,
    )

    # Never call a real SMS provider during this test.
    sent_messages = []

    def fake_send_otp(channel, destination, code):
        sent_messages.append((channel, destination, code))

    monkeypatch.setattr(
        auth,
        "send_otp",
        fake_send_otp,
    )

    # 1. Existing customer record
    cust = Customer(
        full_name="Rajesh Gupta",
        phone="+919555566666",
        email="rajesh@realty.com",
        is_verified=False,
    )

    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)

    # 2. Start an unverified customer session.
    session_response = onboard_customer(
        CustomerOnboardRequest(
            full_name="Rajesh Gupta",
            phone="+919555566666",
            email="rajesh@realty.com",
        ),
        db=db_session,
        req=DummyRequest(),
    )

    assert session_response.is_verified is False

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=session_response.access_token,
    )

    # 3. Request OTP using the bearer token.
    otp_resp = request_customer_otp(
        CustomerOTPRequest(
            phone="+919555566666",
            channel="sms",
        ),
        db=db_session,
        credentials=credentials,
    )

    # Security: Never return OTP to the API caller.
    assert "dev_otp" not in otp_resp

    # Mock delivery received one OTP.
    assert len(sent_messages) == 1

    channel, destination, valid_otp = sent_messages[0]

    assert channel == "sms"
    assert destination == "+919555566666"
    assert len(valid_otp) == 6
    assert valid_otp.isdigit()

    # 4. Verify OTP is hashed in the database.
    db_session.refresh(cust)

    assert cust.otp_code is None
    assert cust.otp_hash is not None
    assert cust.otp_hash != valid_otp
    assert cust.otp_expires_at is not None

    # 5. Wrong OTP must fail.
    wrong_otp = "000000" if valid_otp != "000000" else "000001"

    with pytest.raises(HTTPException) as exc:
        verify_customer_otp(
            CustomerOTPVerifyRequest(
                phone="+919555566666",
                otp_code=wrong_otp,
                channel="sms",
            ),
            db=db_session,
            credentials=credentials,
        )

    assert exc.value.status_code == 400

    db_session.refresh(cust)
    assert cust.otp_attempts == 1

    # 6. Correct OTP must succeed.
    verify_resp = verify_customer_otp(
        CustomerOTPVerifyRequest(
            phone="+919555566666",
            otp_code=valid_otp,
            channel="sms",
        ),
        db=db_session,
        credentials=credentials,
    )

    assert verify_resp.is_verified is True
    assert verify_resp.customer_id == cust.id

    db_session.refresh(cust)

    assert cust.is_verified is True

    # Single-use OTP must be cleared.
    assert cust.otp_code is None
    assert cust.otp_hash is None
    assert cust.otp_expires_at is None
    assert cust.otp_challenge_id is None

    # 7. Verified JWT must reflect successful verification.
    verified_payload = decode_access_token(verify_resp.access_token)

    assert verified_payload["is_verified"] is True
    assert verified_payload["customer_id"] == str(cust.id)


def test_verified_customer_unlocks_history(
    db_session: Session,
):
    """
    A verified customer may access their own
    previously saved leads.
    """

    cust = Customer(
        full_name="Karthik Iyer",
        phone="+919777788888",
        email="karthik@realty.com",
        is_verified=True,
    )

    db_session.add(cust)
    db_session.flush()

    lead = Lead(
        customer_id=cust.id,
        preferred_config="3 BHK",
        preferred_location="Velachery",
        budget_max=Decimal(11000000),
        lead_priority="high",
        qualification_status="qualified",
    )

    db_session.add(lead)
    db_session.commit()

    leads = list_customer_leads(
        current_customer=cust,
        db=db_session,
    )

    assert len(leads) == 1
    assert leads[0].preferred_config == "3 BHK"
    assert leads[0].preferred_location == "Velachery"


# ============================================================
# 5. ADMIN AUTHENTICATION TESTS
# ============================================================


def test_admin_login_success(db_session: Session):

    req = DummyRequest("10.0.0.5")

    admin_user = User(
        email="admin@realty.com",
        hashed_password=hash_password("AdminSecure#2026"),
        role="admin",
        is_active=True,
    )

    db_session.add(admin_user)
    db_session.commit()

    login_resp = login_user(
        UserLoginRequest(
            email="admin@realty.com",
            password="AdminSecure#2026",
            is_admin_login=True,
        ),
        db=db_session,
        req=req,
    )

    assert login_resp.role == "admin"
    assert login_resp.user_id == admin_user.id
    assert login_resp.access_token is not None


def test_customer_credential_rejected_on_admin_login(
    db_session: Session,
):

    req = DummyRequest("10.0.0.6")

    cust_user = User(
        email="customer@realty.com",
        hashed_password=hash_password("CustomerPass#2026"),
        role="customer",
        is_active=True,
    )

    db_session.add(cust_user)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        login_user(
            UserLoginRequest(
                email="customer@realty.com",
                password="CustomerPass#2026",
                is_admin_login=True,
            ),
            db=db_session,
            req=req,
        )

    assert exc.value.status_code == 403

    assert "cannot access the administrator portal" in exc.value.detail


@pytest.mark.parametrize(
    "restricted_role",
    ["admin", "super_owner"],
)
def test_public_registration_blocks_privileged_roles(
    db_session: Session,
    restricted_role: str,
):
    from app.api.v1.auth import register_user
    from app.schemas.auth import UserRegisterRequest

    request = UserRegisterRequest(
        email=f"blocked_{restricted_role}@example.com",
        password="SecureTest#2026",
        role=restricted_role,
        full_name="Unauthorized User",
        phone="+919999999999",
    )

    with pytest.raises(HTTPException) as exc:
        register_user(
            request,
            db=db_session,
            req=DummyRequest(),
        )

    assert exc.value.status_code == 403

    # Ensure no privileged account was created.
    user = db_session.execute(
        select(User).where(User.email == request.email)
    ).scalar_one_or_none()

    assert user is None
