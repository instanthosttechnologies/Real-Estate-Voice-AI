import uuid
from datetime import datetime

from app.db.base import Base, TimestampMixin
from app.db.types import GUID
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    # ========================================================
    # CUSTOMER IDENTITY
    # ========================================================

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    phone: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
    )

    # ========================================================
    # LEGACY OTP FIELDS
    # ========================================================
    # Retained temporarily for compatibility with the
    # existing backend and automated tests.
    #
    # Production OTP verification must use otp_hash instead
    # of storing readable verification codes.

    otp_code: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    otp_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # SECURE OTP FIELDS
    # ========================================================

    # Hash of the OTP, never the readable OTP itself.
    otp_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Channel used to deliver the OTP.
    # Allowed values are validated in the API:
    # "email" or "sms".
    otp_channel: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    # Number of incorrect OTP verification attempts.
    otp_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    # Time when the latest OTP request was accepted.
    # Used to enforce a resend cooldown.
    otp_last_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Temporary OTP lockout after repeated failures.
    otp_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Random identifier for the OTP challenge.
    # A later API update will bind it to the requesting
    # customer's authenticated session.
    otp_challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    user = relationship(
        "User",
        back_populates="customer_profile",
    )

    leads: Mapped[list["Lead"]] = relationship(
        "Lead",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    site_visits: Mapped[list["SiteVisit"]] = relationship(
        "SiteVisit",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="customer",
    )
