import json
import uuid
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.ingestion import IngestionBatch
from app.models.user import User
from app.schemas.ingestion import (
    ConflictResolutionStrategy,
    IngestionPreviewResponse,
    IngestionResultResponse,
    RollbackResponse,
)
from app.services.ingestion.pipeline import (
    generate_preview,
    execute_ingestion_batch,
    execute_rollback,
)

router = APIRouter(prefix="/ingestion", tags=["Dynamic Dataset Ingestion"])


@router.post("/preview", response_model=IngestionPreviewResponse)
async def preview_uploaded_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
):
    """
    Parses dynamic file upload (Excel, CSV, JSON, PDF) and returns 15 sample preview rows
    with AI-assisted column mapping proposals without committing to the database.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        preview = generate_preview(content, file.filename or "dataset.csv")
        return preview
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Parsing error: {exc}")


@router.post("/execute", response_model=IngestionResultResponse)
async def execute_batch_ingestion(
    file: UploadFile = File(...),
    mappings_json: str = Form(..., description="JSON string of source_col -> canonical_field"),
    conflict_strategy: ConflictResolutionStrategy = Form(default=ConflictResolutionStrategy.NEW_VERSION),
    current_user: User = Depends(require_role(["super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Executes normalized batch ingestion into the relational schema.
    Strictly restricted to Super Owner role.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        confirmed_mappings = json.loads(mappings_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON in mappings_json.")

    try:
        result = execute_ingestion_batch(
            db=db,
            content=content,
            filename=file.filename or "import.csv",
            confirmed_mappings=confirmed_mappings,
            conflict_strategy=conflict_strategy,
            user_id=current_user.id,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ingestion failed: {exc}")


@router.post("/rollback/{batch_id}", response_model=RollbackResponse)
def rollback_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(["super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Safely rolls back an ingestion batch in reverse dependency order.
    Restores previous states and creates an immutable audit log.
    Strictly restricted to Super Owner role.
    """
    try:
        res = execute_rollback(
            db=db,
            batch_id=batch_id,
            user_id=current_user.id,
            user_role=current_user.role,
        )
        return res
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Rollback failed: {exc}")


@router.get("/batches", response_model=List[IngestionResultResponse])
def list_ingestion_batches(
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Lists ingestion batches, provenance, and import logs.
    """
    batches = db.execute(select(IngestionBatch).order_by(IngestionBatch.created_at.desc())).scalars().all()
    return [
        IngestionResultResponse(
            batch_id=b.id,
            status=b.status,
            total_rows=b.total_rows,
            imported_rows=b.imported_rows,
            skipped_rows=b.skipped_rows,
            failed_rows=b.failed_rows,
            error_summary=b.error_summary,
            can_rollback=b.can_rollback,
        )
        for b in batches
    ]
