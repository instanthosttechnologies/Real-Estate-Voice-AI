import uuid
from typing import Optional
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.db.types import GUID


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    preferred_config: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    budget_min: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    budget_max: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    preferred_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lead_priority: Mapped[str] = mapped_column(String(50), default="medium", index=True, nullable=False)
    qualification_status: Mapped[str] = mapped_column(
        String(50), default="unqualified", index=True, nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), default="voice_ai", nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="leads")
    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="leads")
