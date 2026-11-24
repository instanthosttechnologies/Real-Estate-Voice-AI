import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, utc_now
from app.db.types import GUID, JSONCompat


class DynamicDataset(Base):
    """
    Metadata Registry and provenance tracking for dynamic uploaded datasets.
    Supports secure tenant isolation (company_id), versioning, dynamic schema inspection,
    explicit Admin field whitelisting, and safe company-scoped activation.
    """
    __tablename__ = "dynamic_datasets"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending_approval", nullable=False
    )  # 'pending_approval', 'approved', 'active', 'archived', 'rolled_back'
    uploaded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    primary_sheet: Mapped[str] = mapped_column(String(100), default="Primary_Dataset", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Dynamic Schema Approval & Whitelisting
    approved_fields: Mapped[Optional[List[str]]] = mapped_column(JSONCompat(), nullable=True)
    field_labels: Mapped[Optional[Dict[str, str]]] = mapped_column(JSONCompat(), nullable=True)
    display_identifier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    domain_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    welcome_greeting: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    
    metadata_registry: Mapped[Dict[str, Any]] = mapped_column(JSONCompat(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    company: Mapped["Company"] = relationship("Company", back_populates="datasets")
    records: Mapped[List["DynamicDatasetRecord"]] = relationship(
        "DynamicDatasetRecord", back_populates="dataset", cascade="all, delete-orphan"
    )


class DynamicDatasetRecord(Base):
    """
    Flexible storage for records of arbitrary dynamic schemas.
    Preserves exact raw values for audit/provenance, while strictly restricting
    normalized search tokens and voice summaries to Admin-approved fields.
    """
    __tablename__ = "dynamic_dataset_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("dynamic_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sheet_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    record_identifier: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    raw_data: Mapped[Dict[str, Any]] = mapped_column(JSONCompat(), nullable=False)
    normalized_search: Mapped[Dict[str, Any]] = mapped_column(JSONCompat(), nullable=False)
    voice_summary: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    dataset: Mapped["DynamicDataset"] = relationship("DynamicDataset", back_populates="records")
