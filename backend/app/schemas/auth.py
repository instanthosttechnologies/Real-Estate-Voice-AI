import re
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import validate_password_strength
from app.schemas.customer import (
    CustomerOnboardRequest,
    CustomerSessionResponse,
    CustomerOTPRequest,
    CustomerOTPVerifyRequest,
)


class UserRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=8)
    role: str = Field(default="customer", description="customer, admin, super_owner")
    full_name: Optional[str] = Field(None, description="Required for customer role")
    phone: Optional[str] = Field(None, description="Optional phone number")

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email address format.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class UserLoginRequest(BaseModel):
    email: str
    password: str
    is_admin_login: bool = False

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        return v.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes in seconds
    role: str
    user_id: uuid.UUID


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class LogoutResponse(BaseModel):
    message: str = "Successfully logged out and session revoked."


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime

