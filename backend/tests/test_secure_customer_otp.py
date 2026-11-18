import pytest
from app.api.v1 import auth
from app.db.base import Base
from app.models import Customer
from app.schemas.auth import (
    CustomerOnboardRequest,
    CustomerOTPRequest,
    CustomerOTPVerifyRequest,
)
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session():
    """Create an isolated in-memory test database."""

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    """Prevent real OTP delivery and use a test-only secret."""

    monkeypatch.setenv(
        "OTP_HMAC_SECRET",
        "offline-test-secret-" + "a" * 64,
    )

    monkeypatch.setattr(
        auth,
        "record_audit_log_sync",
        lambda **kwargs: None,
    )


def create_customer_session(db_session):
    """Create an unverified customer session."""

    response = auth.onboard_customer(
        CustomerOnboardRequest(
            full_name="Demo Customer",
            phone="+919876543210",
            email="demo@example.com",
        ),
        db=db_session,
    )

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=response.access_token,
    )

    return response, credentials


@pytest.mark.parametrize("channel", ["sms", "email"])
def test_secure_otp_success(
    db_session,
    monkeypatch,
    channel,
):
    """Verify both channels without making network calls."""

    sent_messages = []

    def fake_send_otp(selected_channel, destination, code):
        sent_messages.append((selected_channel, destination, code))

    monkeypatch.setattr(auth, "send_otp", fake_send_otp)

    session, credentials = create_customer_session(db_session)

    assert session.is_verified is False

    result = auth.request_customer_otp(
        CustomerOTPRequest(
            phone="+919876543210",
            channel=channel,
        ),
        db=db_session,
        credentials=credentials,
    )

    assert "dev_otp" not in result
    assert len(sent_messages) == 1

    sent_channel, destination, otp = sent_messages[0]

    assert sent_channel == channel
    assert len(otp) == 6
    assert otp.isdigit()

    if channel == "sms":
        assert destination == "+919876543210"
    else:
        assert destination == "demo@example.com"

    customer = db_session.get(Customer, session.customer_id)

    assert customer.otp_code is None
    assert customer.otp_hash is not None
    assert customer.otp_hash != otp

    verified = auth.verify_customer_otp(
        CustomerOTPVerifyRequest(
            phone="+919876543210",
            otp_code=otp,
            channel=channel,
        ),
        db=db_session,
        credentials=credentials,
    )

    assert verified.is_verified is True

    db_session.refresh(customer)

    assert customer.otp_hash is None

    # OTP cannot be reused.
    with pytest.raises(HTTPException) as error:
        auth.verify_customer_otp(
            CustomerOTPVerifyRequest(
                phone="+919876543210",
                otp_code=otp,
                channel=channel,
            ),
            db=db_session,
            credentials=credentials,
        )

    assert error.value.status_code == 400


def test_wrong_otp_lock(
    db_session,
    monkeypatch,
):
    """Five incorrect attempts must lock verification."""

    sent_messages = []

    monkeypatch.setattr(
        auth,
        "send_otp",
        lambda channel, destination, code: sent_messages.append(code),
    )

    session, credentials = create_customer_session(db_session)

    auth.request_customer_otp(
        CustomerOTPRequest(
            phone="+919876543210",
            channel="sms",
        ),
        db=db_session,
        credentials=credentials,
    )

    real_otp = sent_messages[0]
    wrong_otp = "000000" if real_otp != "000000" else "000001"

    for attempt in range(5):
        with pytest.raises(HTTPException) as error:
            auth.verify_customer_otp(
                CustomerOTPVerifyRequest(
                    phone="+919876543210",
                    otp_code=wrong_otp,
                    channel="sms",
                ),
                db=db_session,
                credentials=credentials,
            )

        assert error.value.status_code == 400

    customer = db_session.get(Customer, session.customer_id)
    db_session.refresh(customer)

    assert customer.otp_attempts == 5
    assert customer.otp_locked_until is not None
    assert customer.otp_hash is None

    with pytest.raises(HTTPException) as error:
        auth.verify_customer_otp(
            CustomerOTPVerifyRequest(
                phone="+919876543210",
                otp_code=real_otp,
                channel="sms",
            ),
            db=db_session,
            credentials=credentials,
        )

    assert error.value.status_code == 429


def test_previous_verified_customer_requires_new_session_otp(
    db_session,
):
    """
    A previously verified customer must not expose
    private information through a new unverified JWT.
    """

    from app.api.deps import get_current_customer

    # Create a customer who verified an earlier session.
    customer = Customer(
        full_name="Priya Sharma",
        phone="+919876543210",
        email="priya@example.com",
        is_verified=True,
    )

    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)

    # A new session has NOT completed OTP verification.
    unverified_token = auth.create_access_token(
        data={
            "sub": str(customer.id),
            "customer_id": str(customer.id),
            "role": "customer",
            "is_verified": False,
        }
    )

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=unverified_token,
    )

    result = get_current_customer(
        credentials=credentials,
        db=db_session,
    )

    # Customer identity is resolved but remains restricted.
    assert result.id == customer.id
    assert result.is_verified is False

    # Private profile fields must not be accessible.
    with pytest.raises(HTTPException) as error:
        _ = result.email

    assert error.value.status_code == 403

    # A genuinely verified session can access the profile.
    verified_token = auth.create_access_token(
        data={
            "sub": str(customer.id),
            "customer_id": str(customer.id),
            "role": "customer",
            "is_verified": True,
        }
    )

    verified_credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=verified_token,
    )

    verified_customer = get_current_customer(
        credentials=verified_credentials,
        db=db_session,
    )

    assert verified_customer.id == customer.id
    assert verified_customer.is_verified is True
    assert verified_customer.email == "priya@example.com"


def test_http_api_prevents_unverified_customer_history_access(
    db_session,
):
    """
    A new, unverified HTTP session must not disclose
    a previously verified customer's private details.
    """

    from app.db.session import get_db
    from app.main import app
    from app.models import Lead
    from fastapi.testclient import TestClient

    phone = "+919777766665"
    email = "existing.owner@example.com"

    # Create a customer who verified an earlier session.
    existing = Customer(
        full_name="Original Private Owner",
        phone=phone,
        email=email,
        is_verified=True,
    )

    db_session.add(existing)
    db_session.flush()

    # Store a private property enquiry.
    db_session.add(
        Lead(
            customer_id=existing.id,
            preferred_location="PRIVATE-SECRET-PROPERTY",
            preferred_config="Luxury Villa",
        )
    )

    db_session.commit()

    # Force FastAPI to use the isolated test database.
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            # A new visitor enters the existing contact details.
            response = client.post(
                "/api/v1/auth/customer-session",
                json={
                    "full_name": "New Visitor",
                    "phone": phone,
                    "email": email,
                },
            )

            assert response.status_code == 200

            session_data = response.json()

            assert session_data["is_verified"] is False
            assert session_data["full_name"] == "New Visitor"

            token = session_data["access_token"]

            headers = {"Authorization": f"Bearer {token}"}

            # Check private profile access.
            profile = client.get(
                "/api/v1/customer/profile",
                headers=headers,
            )

            assert profile.status_code in (401, 403)

            # Private property enquiries must remain hidden.
            leads = client.get(
                "/api/v1/customer/leads",
                headers=headers,
            )

            assert leads.status_code in (200, 401, 403)

            if leads.status_code == 200:
                assert leads.json() == []

            # Saved requirements must remain hidden.
            requirements = client.get(
                "/api/v1/customer/requirements",
                headers=headers,
            )

            assert requirements.status_code in (200, 401, 403)

            if requirements.status_code == 200:
                assert requirements.json() is None

            # Previous site visits must remain hidden.
            visits = client.get(
                "/api/v1/customer/site-visits",
                headers=headers,
            )

            assert visits.status_code in (200, 401, 403)

            if visits.status_code == 200:
                assert visits.json() == []

    finally:
        app.dependency_overrides.pop(get_db, None)


def test_mock_otp_delivery_blocked_in_production(monkeypatch):
    """
    Ensure MOCK_OTP_DELIVERY raises OTPDeliveryError in production
    and strictly forbids writing mock OTP files or bypassing real delivery.
    """
    from app.services.otp_delivery import send_otp, OTPDeliveryError

    monkeypatch.setenv("MOCK_OTP_DELIVERY", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(OTPDeliveryError) as exc_info:
        send_otp("email", "test@example.com", "123456")

    assert "strictly prohibited in production" in str(exc_info.value)

