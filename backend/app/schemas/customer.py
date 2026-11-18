import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

# ============================================================
# COMMON PHONE NORMALIZATION
# ============================================================


def normalize_customer_phone(value: str) -> str:
    """
    Normalize customer phone numbers.

    Example:
        +91-98765-43210 -> +919876543210

    This preserves the existing application's
    phone normalization behavior.
    """

    clean = re.sub(r"[^\d+]", "", value.strip())
    digits = re.sub(r"\D", "", clean)

    if len(digits) < 7:
        raise ValueError("Phone number must contain at least 7 digits.")

    return clean


# ============================================================
# CUSTOMER ONBOARDING
# ============================================================


class CustomerOnboardRequest(BaseModel):
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Customer's full name",
    )

    phone: str = Field(
        ...,
        min_length=7,
        max_length=50,
        description="Customer's contact phone number",
    )

    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="Customer's email address",
    )

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        clean = value.strip()

        if len(clean) < 2:
            raise ValueError("Full name must be at least 2 characters.")

        return clean

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        clean = value.strip().lower()

        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            clean,
        ):
            raise ValueError("Invalid email address format.")

        return clean

    @field_validator("phone")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        return normalize_customer_phone(value)


# ============================================================
# CUSTOMER SESSION RESPONSE
# ============================================================


class CustomerSessionResponse(BaseModel):
    access_token: str

    token_type: str = "bearer"

    expires_in: int = 900

    customer_id: uuid.UUID

    full_name: str

    phone: str

    email: str | None = None

    role: str = "customer"

    is_verified: bool = False


# ============================================================
# OTP DELIVERY CHANNEL
# ============================================================

OTPChannel = Literal["email", "sms"]


# ============================================================
# CUSTOMER OTP REQUEST
# ============================================================


class CustomerOTPRequest(BaseModel):
    """
    Request an OTP using the customer's registered
    Email or SMS destination.

    The actual destination must be read from the
    customer record in the database.

    Default channel is SMS to preserve compatibility
    with existing tests and API callers.
    """

    phone: str = Field(
        ...,
        min_length=7,
        max_length=50,
    )

    channel: OTPChannel = Field(
        default="sms",
        description="OTP delivery channel: email or sms",
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_customer_phone(value)


# ============================================================
# CUSTOMER OTP VERIFICATION
# ============================================================


class CustomerOTPVerifyRequest(BaseModel):
    """
    Verify the OTP for the selected delivery channel.

    The backend must verify the code against the
    active challenge and its recorded channel.

    Default SMS preserves existing test compatibility.
    """

    phone: str = Field(
        ...,
        min_length=7,
        max_length=50,
    )

    otp_code: str = Field(
        ...,
        min_length=4,
        max_length=10,
    )

    channel: OTPChannel = Field(
        default="sms",
        description="Channel used when requesting the OTP",
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_customer_phone(value)

    @field_validator("otp_code")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        clean = value.strip()

        if not clean:
            raise ValueError("OTP code cannot be empty.")

        return clean


# ============================================================
# CUSTOMER PROFILE RESPONSE
# ============================================================


class CustomerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    user_id: uuid.UUID | None = None

    full_name: str

    email: str | None = None

    phone: str

    is_verified: bool = False

    created_at: datetime


# ============================================================
# CUSTOMER LEAD RESPONSE
# ============================================================


class CustomerLeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    customer_id: uuid.UUID

    project_id: uuid.UUID | None = None

    preferred_config: str | None = None

    budget_min: Decimal | None = None

    budget_max: Decimal | None = None

    preferred_location: str | None = None

    lead_priority: str

    qualification_status: str

    source: str = "voice_ai"

    notes: str | None = None

    created_at: datetime


# ============================================================
# CUSTOMER REQUIREMENT UPDATE
# ============================================================


class CustomerRequirementUpdateRequest(BaseModel):
    preferred_city: str | None = None

    preferred_location: str | None = None

    preferred_configuration: str | None = None

    budget_min: Decimal | None = Field(
        None,
        ge=0,
    )

    budget_max: Decimal | None = Field(
        None,
        ge=0,
    )

    currency: str | None = "INR"

    purchase_timeline: str | None = None

    required_amenities: list[str] | None = None


# ============================================================
# CUSTOMER SITE VISIT RESPONSE
# ============================================================


class CustomerSiteVisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    project_id: uuid.UUID

    unit_id: uuid.UUID | None = None

    scheduled_start: datetime

    scheduled_end: datetime

    status: str

    notes: str | None = None

    created_at: datetime
