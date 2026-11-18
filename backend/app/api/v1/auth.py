"""Real Estate AI authentication endpoints.

Customer OTP endpoints require an unverified customer bearer token obtained
from /customer-session. No OTP is returned to a caller.
"""

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import record_audit_log_sync
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    login_rate_limiter,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.models.customer import Customer
from app.models.user import User
from app.schemas.auth import (
    CustomerOnboardRequest,
    CustomerOTPRequest,
    CustomerOTPVerifyRequest,
    CustomerSessionResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.otp_delivery import OTPDeliveryError, send_otp

router = APIRouter(prefix="/auth", tags=["Authentication"])
customer_bearer = HTTPBearer(auto_error=False)

OTP_TTL_MINUTES = 10
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
OTP_LOCK_MINUTES = 15
OTP_GENERIC_FAILURE = "Invalid or expired OTP."


def _load_otp_settings() -> None:
    """Expose provider credentials from backend/.env to otp_delivery.py.

    app.core.config's .env parsing does not necessarily export os.environ.
    Loading here, after settings was initialized, prevents that discrepancy.
    """
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(dotenv_path=env_path, override=False)


def _otp_secret() -> bytes:
    _load_otp_settings()
    value = os.getenv("OTP_HMAC_SECRET", "")
    if len(value) < 32 or value.lower().startswith("change_me"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTP verification is not configured on this server.",
        )
    return value.encode("utf-8")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    # SQLite returns naive timestamps; timestamps written by this code are UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _customer_session_claims(
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[str, uuid.UUID]:
    """Validate an unverified, OTP-only customer session token."""
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer onboarding bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(credentials.credentials)
        customer_id = uuid.UUID(str(claims["customer_id"]))
        session_id = str(uuid.UUID(str(claims["otp_session"])))
        valid = (
            claims.get("role") == "customer"
            and claims.get("is_verified") is False
            and claims.get("sub") == str(customer_id)
        )
        if not valid:
            raise ValueError("Invalid customer onboarding session")
        return session_id, customer_id
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired customer onboarding token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _hash_otp(
    customer_id: uuid.UUID,
    challenge_id: uuid.UUID,
    session_id: str,
    channel: str,
    code: str,
    secret: bytes,
) -> str:
    # Keyed HMAC prevents offline guessing of six-digit values from a DB leak.
    message = f"{customer_id}:{challenge_id}:{session_id}:{channel}:{code}"
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


def _clear_pending_otp(customer: Customer) -> None:
    customer.otp_code = None  # legacy plaintext field must never be populated
    customer.otp_hash = None
    customer.otp_channel = None
    customer.otp_challenge_id = None
    customer.otp_expires_at = None


def _customer_token(customer: Customer, verified: bool) -> str:
    claims = {
        "sub": str(customer.id),
        "customer_id": str(customer.id),
        "role": "customer",
        "is_verified": verified,
    }
    if verified:
        claims.update({
            "full_name": customer.full_name,
            "email": customer.email,
            "phone": customer.phone,
        })
    else:
        # A fresh, unpredictable identifier binds the OTP challenge to this
        # particular onboarding token, rather than any token for the account.
        claims["otp_session"] = str(uuid.uuid4())
    return create_access_token(data=claims)


# ============================================================
# 1. CUSTOMER ONBOARDING
# ============================================================

@router.post(
    "/customer-session",
    response_model=CustomerSessionResponse,
    status_code=status.HTTP_200_OK,
)
def onboard_customer(
    request: CustomerOnboardRequest,
    db: Session = Depends(get_db),
    req: Request = None,
):
    """Start an unverified onboarding session without leaking stored PII."""
    clean_phone = request.phone
    clean_email = request.email.strip().lower()
    clean_name = request.full_name.strip()

    # Never resolve by email OR phone alone: doing so could bind a claimant to
    # an unrelated existing account if the two identifiers disagree.
    by_phone = db.execute(
        select(Customer).where(Customer.phone == clean_phone)
    ).scalars().first()
    by_email = db.execute(
        select(Customer).where(Customer.email == clean_email)
    ).scalars().first()

    if ((by_phone and by_phone.email.lower() != clean_email)
            or (by_email and by_email.phone != clean_phone)
            or (by_phone and by_email and by_phone.id != by_email.id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="These contact details cannot be used together. Contact support.",
        )

    customer = by_phone or by_email
    if customer is None:
        customer = Customer(
            full_name=clean_name,
            phone=clean_phone,
            email=clean_email,
            is_verified=False,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    token = _customer_token(customer, verified=False)
    client_ip = req.client.host if req and getattr(req, "client", None) else None
    record_audit_log_sync(
        db=db,
        user_id=None,
        user_role="customer",
        action="CUSTOMER_ONBOARDED",
        resource_type="customer",
        resource_id=str(customer.id),
        ip_address=client_ip,
        meta_info={"phone_suffix": clean_phone[-4:], "is_verified": False},
    )

    return CustomerSessionResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        customer_id=customer.id,
        # Only echo the caller's input, NEVER the existing DB profile details.
        full_name=clean_name,
        phone=clean_phone,
        email=clean_email,
        role="customer",
        is_verified=False,
    )


# ============================================================
# 2. REQUEST EMAIL/SMS OTP
# ============================================================

@router.post("/customer-otp-request", status_code=status.HTTP_200_OK)
def request_customer_otp(
    request: CustomerOTPRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(customer_bearer),
):
    """Send a six-digit OTP to a saved contact; never return it in JSON."""
    session_id, customer_id = _customer_session_claims(credentials)
    secret = _otp_secret()  # fail closed if not configured
    channel = getattr(request, "channel", "sms")
    if channel not in ("sms", "email"):
        raise HTTPException(status_code=422, detail="Invalid OTP channel.")

    customer = db.execute(
        select(Customer).where(Customer.id == customer_id).with_for_update()
    ).scalar_one_or_none()
    if customer is None or customer.phone != request.phone:
        raise HTTPException(status_code=400, detail="Invalid customer session.")

    now = datetime.now(UTC)
    locked_until = _utc(customer.otp_locked_until)
    if locked_until and locked_until > now:
        raise HTTPException(
            status_code=429,
            detail="Too many OTP attempts. Try again later.",
        )
    if locked_until and locked_until <= now:
        customer.otp_locked_until = None
        customer.otp_attempts = 0

    last = _utc(customer.otp_last_requested_at)
    if last and (now - last).total_seconds() < OTP_RESEND_SECONDS:
        retry = max(1, int(OTP_RESEND_SECONDS - (now - last).total_seconds()) + 1)
        raise HTTPException(
            status_code=429,
            detail="Please wait before requesting another OTP.",
            headers={"Retry-After": str(retry)},
        )

    # The destination is obtained ONLY from the saved customer record.
    destination = customer.email if channel == "email" else customer.phone
    if not destination:
        raise HTTPException(status_code=400, detail="OTP destination unavailable.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = uuid.uuid4()
    customer.otp_hash = _hash_otp(
        customer.id, challenge_id, session_id, channel, code, secret
    )
    customer.otp_channel = channel
    customer.otp_challenge_id = challenge_id
    customer.otp_expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)
    customer.otp_last_requested_at = now
    customer.otp_code = None
    # Don't reset failed attempts when simply requesting a fresh OTP.

    try:
        db.flush()
        _load_otp_settings()
        send_otp(channel, destination, code)
        db.commit()
    except OTPDeliveryError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OTP delivery failed. Please try later.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {"message": "If delivery is available, the OTP has been sent."}


# ============================================================
# 3. VERIFY OTP AND ISSUE CUSTOMER ACCESS
# ============================================================

@router.post(
    "/customer-otp-verify",
    response_model=CustomerSessionResponse,
    status_code=status.HTTP_200_OK,
)
def verify_customer_otp(
    request: CustomerOTPVerifyRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(customer_bearer),
):
    """Check the session-bound, single-use OTP and issue verified JWT."""
    session_id, customer_id = _customer_session_claims(credentials)
    secret = _otp_secret()
    channel = getattr(request, "channel", "sms")

    customer = db.execute(
        select(Customer).where(Customer.id == customer_id).with_for_update()
    ).scalar_one_or_none()
    if customer is None or customer.phone != request.phone:
        raise HTTPException(status_code=400, detail=OTP_GENERIC_FAILURE)

    now = datetime.now(UTC)
    locked_until = _utc(customer.otp_locked_until)
    if locked_until and locked_until > now:
        raise HTTPException(status_code=429, detail="OTP verification temporarily locked.")
    if locked_until and locked_until <= now:
        customer.otp_attempts = 0
        customer.otp_locked_until = None

    expiry = _utc(customer.otp_expires_at)
    if (not customer.otp_hash or not customer.otp_challenge_id
            or not expiry or expiry <= now or customer.otp_channel != channel):
        _clear_pending_otp(customer)
        db.commit()
        raise HTTPException(status_code=400, detail=OTP_GENERIC_FAILURE)

    code = str(request.otp_code)
    expected = _hash_otp(
        customer.id, customer.otp_challenge_id,
        session_id, channel, code, secret,
    )
    correct = len(code) == 6 and code.isascii() and code.isdecimal() and hmac.compare_digest(
        customer.otp_hash, expected
    )
    if not correct:
        customer.otp_attempts = (customer.otp_attempts or 0) + 1
        if customer.otp_attempts >= OTP_MAX_ATTEMPTS:
            customer.otp_locked_until = now + timedelta(minutes=OTP_LOCK_MINUTES)
            _clear_pending_otp(customer)
        db.commit()  # persist the failure / lock even though we return 400 or 429
        raise HTTPException(status_code=400, detail=OTP_GENERIC_FAILURE)

    customer.is_verified = True
    customer.otp_attempts = 0
    customer.otp_locked_until = None
    _clear_pending_otp(customer)
    db.commit()
    db.refresh(customer)

    access_token = _customer_token(customer, verified=True)
    return CustomerSessionResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        customer_id=customer.id,
        full_name=customer.full_name,
        phone=customer.phone,
        email=customer.email,
        role="customer",
        is_verified=True,
    )


# ============================================================
# 4. USER REGISTRATION
# ============================================================


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    request: UserRegisterRequest,
    db: Session = Depends(get_db),
    req: Request = None,
):
    """
    Existing user registration flow.

    WARNING:
    The original public registration endpoint supports
    privileged roles. Restrict these roles before production.
    """

    # Check existing user.
    existing = db.execute(
        select(User).where(User.email == request.email.lower())
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("A user with this email address is already registered."),
        )

    # Preserve existing role validation.

    if request.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Public registration is restricted to customer accounts. "
                "Administrator accounts must be created by an "
                "authorized system administrator."
            ),
        )

    user = User(
        email=request.email.lower(),
        hashed_password=hash_password(request.password),
        role=request.role,
        is_active=True,
    )

    db.add(user)
    db.flush()

    # Create linked customer profile if needed.
    if request.role == "customer":
        full_name = request.full_name or request.email.split("@")[0].title()

        phone = request.phone or f"+91-{str(user.id).replace('-', '')[:10]}"

        customer_profile = Customer(
            user_id=user.id,
            full_name=full_name,
            email=user.email,
            phone=phone,
        )

        db.add(customer_profile)

    db.commit()
    db.refresh(user)

    client_ip = req.client.host if req and getattr(req, "client", None) else None

    record_audit_log_sync(
        db=db,
        user_id=user.id,
        user_role=user.role,
        action="USER_REGISTERED",
        resource_type="user",
        resource_id=str(user.id),
        ip_address=client_ip,
        meta_info={
            "email": user.email,
            "role": user.role,
        },
    )

    return user


# ============================================================
# 5. ADMIN / USER LOGIN
# ============================================================


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login_user(
    request: UserLoginRequest,
    db: Session = Depends(get_db),
    req: Request = None,
):
    """
    Credential-based login.

    Validates:
        - Login rate limit
        - Email/password
        - Active account
        - Admin portal permission

    Generates JWT access and refresh tokens.
    """

    client_ip = req.client.host if req and getattr(req, "client", None) else "unknown"

    rate_key = f"{request.email}:{client_ip}"

    # ========================================================
    # 1. RATE LIMITING
    # ========================================================

    is_locked, remaining_secs = login_rate_limiter.is_locked(rate_key)

    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed login attempts. "
                f"Account temporarily locked for "
                f"{remaining_secs} seconds."
            ),
        )

    # ========================================================
    # 2. VERIFY CREDENTIALS
    # ========================================================

    user = db.execute(
        select(User).where(User.email == request.email.lower())
    ).scalar_one_or_none()

    if not user or not verify_password(
        request.password,
        user.hashed_password,
    ):
        remaining_attempts = login_rate_limiter.record_failure(rate_key)

        record_audit_log_sync(
            db=db,
            user_id=user.id if user else None,
            user_role=(user.role if user else "unauthenticated"),
            action="LOGIN_FAILED",
            resource_type="user",
            resource_id=request.email,
            ip_address=client_ip,
            meta_info={
                "remaining_attempts": remaining_attempts,
            },
        )

        if remaining_attempts == 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many failed login attempts. Account locked for 15 minutes."
                ),
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ========================================================
    # 3. CHECK ACCOUNT STATUS
    # ========================================================

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    # ========================================================
    # 4. CHECK ADMIN ACCESS
    # ========================================================

    if request.is_admin_login and user.role not in [
        "admin",
        "super_owner",
    ]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Customer accounts cannot access "
                "the administrator portal. "
                "Please explore properties via "
                "the voice assistant."
            ),
        )

    # ========================================================
    # 5. RESET LOGIN RATE LIMIT
    # ========================================================

    login_rate_limiter.reset(rate_key)

    # ========================================================
    # 6. GENERATE TOKENS
    # ========================================================

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role,
            "email": user.email,
        }
    )

    refresh_token = create_refresh_token(
        db,
        user.id,
    )

    # ========================================================
    # 7. RECORD SUCCESSFUL LOGIN
    # ========================================================

    record_audit_log_sync(
        db=db,
        user_id=user.id,
        user_role=user.role,
        action="LOGIN_SUCCESS",
        resource_type="user",
        resource_id=str(user.id),
        ip_address=client_ip,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        role=user.role,
        user_id=user.id,
    )


# ============================================================
# 6. REFRESH SESSION
# ============================================================


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
def refresh_session(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
    req: Request = None,
):
    """
    Rotate refresh token and create a new access token.
    """

    client_ip = req.client.host if req and getattr(req, "client", None) else None

    try:
        user, new_refresh_token = rotate_refresh_token(
            db,
            request.refresh_token,
        )

    except ValueError as exc:
        record_audit_log_sync(
            db=db,
            user_id=None,
            user_role="unknown",
            action="TOKEN_ROTATION_FAILED",
            resource_type="refresh_token",
            resource_id="unknown",
            ip_address=client_ip,
            meta_info={"error": str(exc)},
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    new_access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role,
            "email": user.email,
        }
    )

    record_audit_log_sync(
        db=db,
        user_id=user.id,
        user_role=user.role,
        action="TOKEN_ROTATED",
        resource_type="refresh_token",
        resource_id=str(user.id),
        ip_address=client_ip,
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        role=user.role,
        user_id=user.id,
    )


# ============================================================
# 7. LOGOUT
# ============================================================


@router.post(
    "/logout",
    response_model=LogoutResponse,
)
def logout_user(
    request: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    req: Request = None,
):
    """
    Revoke refresh token and log out the user.
    """

    if request.refresh_token:
        revoke_refresh_token(
            db,
            request.refresh_token,
        )

    client_ip = req.client.host if req and getattr(req, "client", None) else None

    record_audit_log_sync(
        db=db,
        user_id=current_user.id,
        user_role=current_user.role,
        action="USER_LOGOUT",
        resource_type="user",
        resource_id=str(current_user.id),
        ip_address=client_ip,
    )

    return LogoutResponse(message=("Successfully logged out and session revoked."))


# ============================================================
# 8. CURRENT AUTHENTICATED USER
# ============================================================


@router.get(
    "/me",
    response_model=UserResponse,
)
def read_current_user(
    current_user: User = Depends(get_current_user),
):
    """
    Return authenticated user details.
    """

    return current_user
