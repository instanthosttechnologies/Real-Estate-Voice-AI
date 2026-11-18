import uuid
from typing import Optional
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, utc_now
from app.db.types import GUID


class Availability(Base):
    """
    Maintains unit availability state with historical change tracking.
    is_current=True flags the active availability record.
    """
    __tablename__ = "availability"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("property_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="available", index=True, nullable=False
    )  # 'available', 'reserved', 'sold', 'blocked'
    available_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hold_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    unit: Mapped["PropertyUnit"] = relationship("PropertyUnit", back_populates="availability_history")
