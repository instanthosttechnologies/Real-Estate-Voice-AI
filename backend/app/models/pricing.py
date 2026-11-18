import uuid
from typing import Optional
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, utc_now
from app.db.types import GUID


class Pricing(Base):
    """
    Maintains pricing details with full historical versioning.
    When a price update occurs, existing active pricing has valid_to set to now and is_active set to False,
    and a new record is created with is_active=True.
    """
    __tablename__ = "pricing"
    __table_args__ = (
        CheckConstraint("base_price >= 0", name="chk_non_negative_base_price"),
        CheckConstraint("total_estimated_price >= 0", name="chk_non_negative_total_price"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("property_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    maintenance_charge_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    parking_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    estimated_tax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    total_estimated_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    unit: Mapped["PropertyUnit"] = relationship("PropertyUnit", back_populates="pricing_history")
