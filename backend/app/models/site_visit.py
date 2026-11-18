import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.db.types import GUID


class SiteVisit(Base, TimestampMixin):
    __tablename__ = "site_visits"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("property_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="scheduled", index=True, nullable=False
    )  # 'scheduled', 'completed', 'cancelled', 'rescheduled'
    assigned_agent_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="site_visits")
    project: Mapped["Project"] = relationship("Project", back_populates="site_visits")
    unit: Mapped[Optional["PropertyUnit"]] = relationship("PropertyUnit", back_populates="site_visits")
