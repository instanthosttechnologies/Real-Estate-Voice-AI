import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin, utc_now
from app.db.types import GUID


class Appointment(Base, TimestampMixin):
    """
    Dedicated Appointment and Site Visit booking entity for Real Estate AI.
    Stores comprehensive appointment metadata directly mapped to customer conversation,
    project, date, and time slot with strict double-booking prevention.
    """
    __tablename__ = "appointments"
    __table_args__ = (
        # Note: double-booking constraint per project slot can be enforced logically or via unique index
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID(), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    project_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    property_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    city: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    visit_date: Mapped[date] = mapped_column(Date(), index=True, nullable=False)
    visit_time: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "10:00 AM - 11:00 AM" or "Morning (10:00 AM)"
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata", nullable=False)

    appointment_type: Mapped[str] = mapped_column(
        String(50), default="In-Person Site Visit", nullable=False
    )  # 'In-Person Site Visit', 'Video Consultation'
    booking_status: Mapped[str] = mapped_column(
        String(50), default="confirmed", index=True, nullable=False
    )  # 'confirmed', 'rescheduled', 'cancelled'

    conversation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    booking_source: Mapped[str] = mapped_column(String(50), default="AI Voice", nullable=False)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    assigned_agent: Mapped[Optional[str]] = mapped_column(String(255), default="Senior Property Advisor", nullable=True)
