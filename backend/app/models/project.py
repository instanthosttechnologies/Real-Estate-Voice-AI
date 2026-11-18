import uuid
from typing import List, Optional
from datetime import date
from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.db.types import GUID


class Amenity(Base):
    __tablename__ = "amenities"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    project_associations: Mapped[List["ProjectAmenity"]] = relationship(
        "ProjectAmenity", back_populates="amenity", cascade="all, delete-orphan"
    )


class ProjectAmenity(Base):
    __tablename__ = "project_amenities"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    amenity_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("amenities.id", ondelete="CASCADE"), primary_key=True
    )

    project: Mapped["Project"] = relationship("Project", back_populates="amenity_associations")
    amenity: Mapped["Amenity"] = relationship("Amenity", back_populates="project_associations")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_project_company_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="under_construction", nullable=False)
    launch_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    completion_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_phases: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    company: Mapped["Company"] = relationship("Company", back_populates="projects")
    location: Mapped["Location"] = relationship("Location", back_populates="projects")
    properties: Mapped[List["Property"]] = relationship(
        "Property", back_populates="project", cascade="all, delete-orphan"
    )
    amenity_associations: Mapped[List["ProjectAmenity"]] = relationship(
        "ProjectAmenity", back_populates="project", cascade="all, delete-orphan"
    )
    leads: Mapped[List["Lead"]] = relationship("Lead", back_populates="project")
    site_visits: Mapped[List["SiteVisit"]] = relationship("SiteVisit", back_populates="project")
