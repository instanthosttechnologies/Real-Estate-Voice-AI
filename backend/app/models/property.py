import uuid
from typing import List, Optional
from decimal import Decimal
from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.db.types import GUID


class Property(Base, TimestampMixin):
    """
    Represents a specific building, tower, block, or phase within a project.
    """
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_property_project_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    property_type: Mapped[str] = mapped_column(String(50), default="apartment", nullable=False)
    total_floors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    construction_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="properties")
    units: Mapped[List["PropertyUnit"]] = relationship(
        "PropertyUnit", back_populates="property", cascade="all, delete-orphan"
    )


class PropertyUnit(Base, TimestampMixin):
    """
    Represents an individual unit / flat / villa configuration.
    """
    __tablename__ = "property_units"
    __table_args__ = (
        UniqueConstraint("property_id", "unit_number", name="uq_unit_property_number"),
        CheckConstraint("carpet_area_sqft > 0", name="chk_positive_carpet_area"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_number: Mapped[str] = mapped_column(String(50), nullable=False)
    floor_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    configuration_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)  # '1BHK', '2BHK', etc.
    carpet_area_sqft: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    super_built_up_area_sqft: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    facing: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    balcony_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    property: Mapped["Property"] = relationship("Property", back_populates="units")
    pricing_history: Mapped[List["Pricing"]] = relationship(
        "Pricing", back_populates="unit", cascade="all, delete-orphan", order_by="desc(Pricing.valid_from)"
    )
    availability_history: Mapped[List["Availability"]] = relationship(
        "Availability", back_populates="unit", cascade="all, delete-orphan", order_by="desc(Availability.valid_from)"
    )
    site_visits: Mapped[List["SiteVisit"]] = relationship("SiteVisit", back_populates="unit")
