import uuid
from collections.abc import Callable

import jwt
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.customer import Customer
from app.models.user import User
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

security_scheme = HTTPBearer(auto_error=False)


# ============================================================
# COMMON AUTHENTICATION HELPERS
# ============================================================


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_credentials(
    credentials: HTTPAuthorizationCredentials | None,
) -> dict:
    """Validate the bearer access token."""

    if not credentials or not credentials.credentials:
        raise _authentication_error("Missing or invalid authentication credentials")

    try:
        payload = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError, TypeError):
        raise _authentication_error("Could not validate credentials or token expired")

    if not isinstance(payload, dict):
        raise _authentication_error("Invalid authentication token")

    return payload


def _parse_uuid(value, claim_name: str) -> uuid.UUID:
    """Safely parse a UUID from a JWT claim."""

    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise _authentication_error(f"Invalid or missing {claim_name} claim")


# ============================================================
# RESTRICTED UNVERIFIED CUSTOMER CONTEXT
# ============================================================


class UnverifiedCustomer:
    """
    Restricted customer context.

    An unverified JWT must never expose the saved Customer
    database record, even if the customer verified a
    different session previously.

    Only id and is_verified are available so existing
    routes can safely return empty private-history results.
    """

    __slots__ = ("id", "is_verified")

    def __init__(self, customer_id: uuid.UUID):
        self.id = customer_id
        self.is_verified = False

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "OTP verification is required before "
                "accessing customer profile information."
            ),
        )

    def __repr__(self) -> str:
        return "<UnverifiedCustomer>"


# ============================================================
# 1. CURRENT AUTHENTICATED USER
# ============================================================


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve a credential-authenticated user.

    Customer onboarding tokens cannot be treated as
    administrator/user account credentials.
    """

    payload = _decode_credentials(credentials)

    user_id = _parse_uuid(
        payload.get("sub"),
        "subject",
    )

    token_role = payload.get("role")

    if not isinstance(token_role, str):
        raise _authentication_error("Token missing a valid role")

    user = db.get(User, user_id)

    if not user:
        raise _authentication_error("Authenticated user account not found")

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    # The signed JWT role must match the current DB role.
    if token_role != user.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token role does not match account role",
        )

    return user


# ============================================================
# 2. ROLE-BASED ACCESS CONTROL
# ============================================================


def require_role(
    allowed_roles: list[str],
) -> Callable[[User], User]:
    """
    Allow only the specified account roles.
    """

    def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:

        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"Operation not permitted. Required roles: {allowed_roles}."),
            )

        return current_user

    return role_checker


# ============================================================
# 3. CURRENT CUSTOMER
# ============================================================


def get_current_customer(
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
    db: Session = Depends(get_db),
):
    """
    Resolve a customer using a validated access token.

    Supports:
      1. Passwordless OTP customer sessions
      2. Legacy customer user-linked sessions

    Security rules:
      - Signed JWT must have role='customer'
      - Customer ID must match the token identity
      - No customer lookup fallback using email
      - Unverified sessions cannot access saved PII
      - OTP verification is scoped to the current JWT
    """

    payload = _decode_credentials(credentials)

    if payload.get("role") != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Operation not permitted. Required role: customer."),
        )

    subject_id = _parse_uuid(
        payload.get("sub"),
        "subject",
    )

    customer_id_claim = payload.get("customer_id")

    # --------------------------------------------------------
    # A. PASSWORDLESS CUSTOMER SESSION
    # --------------------------------------------------------

    if customer_id_claim is not None:
        customer_id = _parse_uuid(
            customer_id_claim,
            "customer_id",
        )

        # Passwordless tokens use the customer ID as sub.
        if subject_id != customer_id:
            raise _authentication_error("Customer identity mismatch in token")

        customer = db.get(
            Customer,
            customer_id,
        )

    # --------------------------------------------------------
    # B. LEGACY USER-LINKED CUSTOMER SESSION
    # --------------------------------------------------------

    else:
        user = db.get(
            User,
            subject_id,
        )

        if user is None or not user.is_active or user.role != "customer":
            raise _authentication_error("Invalid customer account session")

        customer = db.execute(
            select(Customer).where(Customer.user_id == user.id)
        ).scalar_one_or_none()

    # --------------------------------------------------------
    # C. CHECK CUSTOMER EXISTS
    # --------------------------------------------------------

    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=("Customer profile not found for the authenticated session."),
        )

    # --------------------------------------------------------
    # D. SESSION-SCOPED OTP VERIFICATION
    # --------------------------------------------------------

    token_verified = payload.get("is_verified") is True

    database_verified = customer.is_verified is True

    session_verified = token_verified and database_verified

    # A previously verified database record is NOT enough.
    # The current signed JWT must also prove verification.
    if not session_verified:
        return UnverifiedCustomer(customer_id=customer.id)

    # --------------------------------------------------------
    # E. FULLY VERIFIED CUSTOMER
    # --------------------------------------------------------

    # The actual ORM object is returned only when both
    # verification checks have passed.
    return customer
