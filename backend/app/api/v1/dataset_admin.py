import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.models.user import User
from app.services.dataset.inspector import inspect_dataset_workbook
from app.services.dataset.manager import (
    activate_dataset,
    get_active_dataset,
    rollback_dataset,
    upload_and_import_dataset,
)
from app.services.dataset.retrieval import query_dynamic_dataset

router = APIRouter(prefix="/datasets", tags=["Dynamic Dataset Management"])


class DatasetSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    filename: str
    file_hash: str
    version: int
    is_active: bool
    status: str
    primary_sheet: str
    total_rows: int
    created_at: str
    activated_at: Optional[str] = None


class DatasetDetailResponse(DatasetSummaryResponse):
    metadata_registry: Dict[str, Any]


class QueryDatasetRequest(BaseModel):
    query: str = Field(..., description="Natural language search inquiry")
    dataset_id: Optional[uuid.UUID] = None
    limit: int = Field(default=4, ge=1, le=20)


@router.post("/inspect")
async def inspect_uploaded_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
):
    """
    Inspects an uploaded Excel (.xlsx, .xls) or CSV file:
    Detects worksheets, columns, data types, sample values, candidate identifiers,
    and cross-sheet relationships without committing to database.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        res = inspect_dataset_workbook(content, file.filename or "dataset.xlsx")
        return {
            "filename": file.filename,
            "primary_sheet": res["primary_sheet"],
            "total_primary_rows": res["total_rows"],
            "metadata_registry": res["metadata_registry"],
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to inspect dataset: {str(exc)}"
        )


@router.post("/upload", response_model=DatasetDetailResponse)
async def upload_new_dataset(
    file: UploadFile = File(...),
    dataset_name: Optional[str] = Form(None),
    auto_activate: bool = Form(False),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Uploads, inspects, and stores a new dynamic dataset version.
    Preserves exact original records, builds normalized search indices,
    and isolates datasets by version.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        dataset = upload_and_import_dataset(
            db=db,
            file_bytes=content,
            filename=file.filename or "dataset.xlsx",
            user_id=current_user.id,
            auto_activate=auto_activate,
            dataset_name=dataset_name,
        )
        return DatasetDetailResponse(
            id=dataset.id,
            name=dataset.name,
            filename=dataset.filename,
            file_hash=dataset.file_hash,
            version=dataset.version,
            is_active=dataset.is_active,
            status=dataset.status,
            primary_sheet=dataset.primary_sheet,
            total_rows=dataset.total_rows,
            metadata_registry=dataset.metadata_registry,
            created_at=dataset.created_at.isoformat(),
            activated_at=dataset.activated_at.isoformat() if dataset.activated_at else None,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dataset import failed: {str(exc)}"
        )


@router.get("", response_model=List[DatasetSummaryResponse])
def list_datasets(
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Lists all registered datasets, versions, and active statuses."""
    datasets = db.execute(
        select(DynamicDataset).order_by(desc(DynamicDataset.created_at))
    ).scalars().all()

    return [
        DatasetSummaryResponse(
            id=d.id,
            name=d.name,
            filename=d.filename,
            file_hash=d.file_hash,
            version=d.version,
            is_active=d.is_active,
            status=d.status,
            primary_sheet=d.primary_sheet,
            total_rows=d.total_rows,
            created_at=d.created_at.isoformat(),
            activated_at=d.activated_at.isoformat() if d.activated_at else None,
        )
        for d in datasets
    ]


@router.get("/active", response_model=Optional[DatasetDetailResponse])
def get_currently_active_dataset(
    db: Session = Depends(get_db),
):
    """Returns the currently active dataset used for customer voice grounding."""
    d = get_active_dataset(db)
    if not d:
        return None
    return DatasetDetailResponse(
        id=d.id,
        name=d.name,
        filename=d.filename,
        file_hash=d.file_hash,
        version=d.version,
        is_active=d.is_active,
        status=d.status,
        primary_sheet=d.primary_sheet,
        total_rows=d.total_rows,
        metadata_registry=d.metadata_registry,
        created_at=d.created_at.isoformat(),
        activated_at=d.activated_at.isoformat() if d.activated_at else None,
    )


@router.get("/{dataset_id}", response_model=DatasetDetailResponse)
def get_dataset_by_id(
    dataset_id: uuid.UUID,
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Retrieves full metadata registry and schema for a specific dataset version."""
    d = db.execute(
        select(DynamicDataset).where(DynamicDataset.id == dataset_id)
    ).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found.")
    return DatasetDetailResponse(
        id=d.id,
        name=d.name,
        filename=d.filename,
        file_hash=d.file_hash,
        version=d.version,
        is_active=d.is_active,
        status=d.status,
        primary_sheet=d.primary_sheet,
        total_rows=d.total_rows,
        metadata_registry=d.metadata_registry,
        created_at=d.created_at.isoformat(),
        activated_at=d.activated_at.isoformat() if d.activated_at else None,
    )


@router.post("/{dataset_id}/activate", response_model=DatasetSummaryResponse)
def activate_dataset_endpoint(
    dataset_id: uuid.UUID,
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Designates the dataset as the active source of truth.
    Deactivates any previously active datasets, ensuring zero cross-dataset leakage.
    """
    try:
        dataset = activate_dataset(db, dataset_id)
        return DatasetSummaryResponse(
            id=dataset.id,
            name=dataset.name,
            filename=dataset.filename,
            file_hash=dataset.file_hash,
            version=dataset.version,
            is_active=dataset.is_active,
            status=dataset.status,
            primary_sheet=dataset.primary_sheet,
            total_rows=dataset.total_rows,
            created_at=dataset.created_at.isoformat(),
            activated_at=dataset.activated_at.isoformat() if dataset.activated_at else None,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{dataset_id}/rollback")
def rollback_dataset_endpoint(
    dataset_id: uuid.UUID,
    current_user: User = Depends(require_role(["super_owner"])),
    db: Session = Depends(get_db),
):
    """Rolls back the specified dataset and reverts to the previous version."""
    try:
        return rollback_dataset(db, dataset_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/query")
def query_dataset_endpoint(
    req: QueryDatasetRequest,
    db: Session = Depends(get_db),
):
    """
    Safe structured query endpoint testing dataset retrieval and voice grounding.
    Returns matched records and concise natural language voice summary.
    """
    return query_dynamic_dataset(
        db=db,
        query_text=req.query,
        dataset_id=req.dataset_id,
        limit=req.limit,
    )
