import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, utc_now
from app.db.types import GUID, JSONCompat


class IngestionBatch(Base):
    """
    Maintains provenance, file metadata, error summary and rollback eligibility for each import batch.
    """
    __tablename__ = "ingestion_batches"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)  # 'csv', 'excel', 'json', 'pdf'
    file_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending_mapping", index=True, nullable=False
    )  # 'pending_mapping', 'processing', 'completed', 'failed', 'conflict_review', 'rolled_back'
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONCompat(), nullable=True)
    mapping_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONCompat(), nullable=True)
    can_rollback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    records: Mapped[List["IngestionRecord"]] = relationship(
        "IngestionRecord", back_populates="batch", cascade="all, delete-orphan"
    )


class IngestionRecord(Base):
    """
    Granular provenance tracking per affected entity. Stores previous state for atomic rollback.
    """
    __tablename__ = "ingestion_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("ingestion_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True, nullable=False)
    source_row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action_taken: Mapped[str] = mapped_column(String(50), nullable=False)  # 'INSERT', 'UPDATE', 'SKIP'
    previous_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONCompat(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    batch: Mapped["IngestionBatch"] = relationship("IngestionBatch", back_populates="records")
