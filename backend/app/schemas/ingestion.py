from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class MappingStatus(str, Enum):
    AUTO_CONFIRMED = "auto_confirmed"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class ConflictResolutionStrategy(str, Enum):
    SKIP = "SKIP"
    OVERWRITE = "OVERWRITE"
    NEW_VERSION = "NEW_VERSION"


class ColumnMappingItem(BaseModel):
    source_column: str
    target_field: Optional[str] = None
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    status: MappingStatus
    sample_values: List[Any] = Field(default_factory=list)


class IngestionPreviewResponse(BaseModel):
    filename: str
    file_format: str
    file_hash: str
    total_preview_rows: int
    detected_headers: List[str]
    preview_rows: List[Dict[str, Any]]
    suggested_mappings: List[ColumnMappingItem]
    requires_manual_confirmation: bool


class ConfirmMappingRequest(BaseModel):
    file_hash: str
    filename: str
    column_mappings: Dict[str, str] = Field(
        ..., description="Map of source_column_name -> canonical_field_name"
    )
    conflict_strategy: ConflictResolutionStrategy = Field(
        default=ConflictResolutionStrategy.NEW_VERSION,
        description="Strategy when unit already exists: SKIP, OVERWRITE, or NEW_VERSION"
    )


class IngestionResultResponse(BaseModel):
    batch_id: UUID
    status: str
    total_rows: int
    imported_rows: int
    skipped_rows: int
    failed_rows: int
    error_summary: Optional[List[Dict[str, Any]]] = None
    can_rollback: bool


class RollbackResponse(BaseModel):
    batch_id: UUID
    status: str
    message: str
    reverted_records_count: int
