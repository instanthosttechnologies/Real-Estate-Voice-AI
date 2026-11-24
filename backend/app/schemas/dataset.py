import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ColumnInspectionMeta(BaseModel):
    column_name: str
    detected_type: str
    total_values: int
    null_count: int
    unique_values_count: int
    is_unique: bool
    is_candidate_identifier: bool
    example_values: List[str]
    sample_distinct: List[str]


class WorksheetInspectionMeta(BaseModel):
    sheet_name: str
    total_rows: int
    total_columns: int
    columns: List[ColumnInspectionMeta]
    candidate_identifiers: List[str]


class CrossSheetRelationship(BaseModel):
    source_sheet: str
    source_column: str
    target_sheet: str
    target_column: str
    relationship_type: str
    overlap_sample_count: int
    confidence: float


class DatasetInspectionResponse(BaseModel):
    filename: str
    file_size_bytes: int
    primary_sheet: str
    total_primary_rows: int
    total_worksheets: int
    worksheets: Dict[str, WorksheetInspectionMeta]
    relationships: List[CrossSheetRelationship]
    candidate_identifiers: List[str]


class DatasetApprovalRequest(BaseModel):
    """
    Contract for Admin approval of discovered schema:
    Admins explicitly whitelist the columns the AI is permitted to access,
    designate a display identifier, and configure domain metadata.
    """
    approved_fields: List[str] = Field(
        ...,
        min_length=1,
        description="Exact column headers explicitly approved for AI voice and search use",
    )
    display_identifier: str = Field(
        ...,
        description="Designated primary identifier/title for records; must be one of the approved_fields",
    )
    field_labels: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional dictionary mapping approved field names to human-readable spoken labels",
    )
    domain_name: Optional[str] = Field(
        default=None,
        description="Business domain name (e.g., 'Automobile Inventory', 'Consumer Electronics', 'Real Estate')",
    )
    welcome_greeting: Optional[str] = Field(
        default=None,
        description="Custom spoken greeting reflecting the business domain",
    )


class DatasetSummaryResponse(BaseModel):
    id: uuid.UUID
    company_id: Optional[uuid.UUID] = None
    name: str
    filename: str
    file_hash: str
    version: int
    is_active: bool
    status: str
    primary_sheet: str
    total_rows: int
    approved_fields: Optional[List[str]] = None
    display_identifier: Optional[str] = None
    domain_name: Optional[str] = None
    created_at: str
    activated_at: Optional[str] = None


class DatasetDetailResponse(DatasetSummaryResponse):
    field_labels: Optional[Dict[str, str]] = None
    welcome_greeting: Optional[str] = None
    metadata_registry: Dict[str, Any]


class DatasetPreviewQueryRequest(BaseModel):
    dataset_id: Optional[uuid.UUID] = None
    query_text: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    sort_by: Optional[str] = None
    sort_order: str = "asc"
    limit: int = 5


class DatasetPreviewRecord(BaseModel):
    id: str
    sheet_name: str
    display_title: str
    voice_summary: str
    attributes: Dict[str, Any]


class DatasetPreviewQueryResponse(BaseModel):
    dataset_id: str
    dataset_name: str
    dataset_version: int
    total_matches: int
    records: List[DatasetPreviewRecord]
    voice_grounding: str
