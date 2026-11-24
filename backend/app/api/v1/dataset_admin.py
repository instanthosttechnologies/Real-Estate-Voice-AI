import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.company import Company
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.models.user import User
from app.schemas.dataset import (
    DatasetApprovalRequest,
    DatasetDetailResponse,
    DatasetInspectionResponse,
    DatasetPreviewQueryRequest,
    DatasetPreviewQueryResponse,
    DatasetPreviewRecord,
    DatasetSummaryResponse,
)
from app.services.dataset.inspector import inspect_dataset_workbook
from app.services.dataset.manager import (
    activate_dataset,
    approve_dataset_schema,
    get_active_dataset,
    rollback_dataset,
    upload_and_import_dataset,
)

router = APIRouter(prefix="/datasets", tags=["Dynamic Dataset Management"])


def resolve_tenant_company(
    current_user: User,
    db: Session,
    requested_company_id: Optional[uuid.UUID] = None,
    allow_platform_for_super_owner: bool = False,
) -> Optional[uuid.UUID]:
    """
    Derives the authorized tenant company identity.
    
    SECURITY ENFORCEMENT:
    1. Normal Admin (role='admin'):
       - Derived strictly from current_user.company_id.
       - Any arbitrary requested_company_id parameter supplied by an Admin is rejected.
       - Fails closed (403 Forbidden) if the user account is not associated with an authorized company.
    2. Super Owner (role='super_owner'):
       - May target a specific company if provided, or defaults to their associated company / primary registered company.
       - When no tenant company exists, allows platform-level dataset management if allow_platform_for_super_owner=True.
    """
    if current_user.role == "admin":
        if not current_user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin user account is not associated with an authorized tenant company. Access denied.",
            )
        # Prevent tenant spoofing
        if requested_company_id and requested_company_id != current_user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot operate on arbitrary tenant companies. Tenant isolation enforced.",
            )
        return current_user.company_id

    elif current_user.role == "super_owner":
        if requested_company_id:
            comp = db.get(Company, requested_company_id)
            if not comp:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target company {requested_company_id} does not exist.",
                )
            return comp.id
        if current_user.company_id:
            return current_user.company_id
        # Fall back to first company
        first_comp = db.execute(select(Company)).scalars().first()
        if first_comp:
            return first_comp.id
        if allow_platform_for_super_owner:
            return None
        # Platform management fallback for unassigned super owner
        return None

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Unauthorized role for dataset operations.",
    )


def _serialize_dataset_detail(d: DynamicDataset) -> DatasetDetailResponse:
    return DatasetDetailResponse(
        id=d.id,
        company_id=d.company_id,
        name=d.name,
        filename=d.filename,
        file_hash=d.file_hash,
        version=d.version,
        is_active=d.is_active,
        status=d.status,
        primary_sheet=d.primary_sheet,
        total_rows=d.total_rows,
        approved_fields=d.approved_fields,
        field_labels=d.field_labels,
        display_identifier=d.display_identifier,
        domain_name=d.domain_name,
        welcome_greeting=d.welcome_greeting,
        metadata_registry=d.metadata_registry,
        created_at=d.created_at.isoformat(),
        activated_at=d.activated_at.isoformat() if d.activated_at else None,
    )


def _serialize_dataset_summary(d: DynamicDataset) -> DatasetSummaryResponse:
    return DatasetSummaryResponse(
        id=d.id,
        company_id=d.company_id,
        name=d.name,
        filename=d.filename,
        file_hash=d.file_hash,
        version=d.version,
        is_active=d.is_active,
        status=d.status,
        primary_sheet=d.primary_sheet,
        total_rows=d.total_rows,
        approved_fields=d.approved_fields,
        display_identifier=d.display_identifier,
        domain_name=d.domain_name,
        created_at=d.created_at.isoformat(),
        activated_at=d.activated_at.isoformat() if d.activated_at else None,
    )


@router.post("/inspect", response_model=DatasetInspectionResponse)
async def inspect_uploaded_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
):
    """
    Dry-run inspection of an uploaded Excel or CSV file.
    Discovers worksheets, columns, inferred data types, sample values, null counts,
    and cross-sheet relationships without committing or activating data.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        res = inspect_dataset_workbook(content, file.filename or "dataset.xlsx")
        meta = res["metadata_registry"]
        return DatasetInspectionResponse(
            filename=meta["filename"],
            file_size_bytes=meta["file_size_bytes"],
            primary_sheet=meta["primary_sheet"],
            total_primary_rows=meta["total_primary_rows"],
            total_worksheets=meta["total_worksheets"],
            worksheets=meta["worksheets"],
            relationships=meta["relationships"],
            candidate_identifiers=res["candidate_identifiers"],
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to inspect dataset: {str(exc)}",
        )


@router.post("/upload", response_model=DatasetDetailResponse)
async def upload_new_dataset(
    file: UploadFile = File(...),
    dataset_name: Optional[str] = Form(None),
    company_id: Optional[uuid.UUID] = Form(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Uploads a new dataset version scoped to the authorized tenant company.
    Stores records in 'pending_approval' status.
    Requires Admin review and approval before activation.
    """
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        dataset = upload_and_import_dataset(
            db=db,
            file_bytes=content,
            filename=file.filename or "dataset.xlsx",
            company_id=tenant_company_id,
            user_id=current_user.id,
            dataset_name=dataset_name,
        )
        return _serialize_dataset_detail(dataset)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dataset upload failed: {str(exc)}",
        )


@router.post("/{dataset_id}/approve", response_model=DatasetDetailResponse)
def approve_dataset_schema_endpoint(
    dataset_id: uuid.UUID,
    req: DatasetApprovalRequest,
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Admin schema review and confirmation contract:
    Whitelists approved fields, sets display identifier, and generates voice/search indices
    exclusively from the approved subset. Rejects unapproved fields from AI leakage.
    """
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    try:
        approved_dataset = approve_dataset_schema(
            db=db,
            dataset_id=dataset_id,
            company_id=tenant_company_id,
            approval=req,
        )
        return _serialize_dataset_detail(approved_dataset)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve dataset schema: {str(exc)}",
        )


@router.post("/{dataset_id}/activate", response_model=DatasetSummaryResponse)
def activate_dataset_endpoint(
    dataset_id: uuid.UUID,
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Company-scoped dataset activation.
    Activates the approved dataset for the authorized company only.
    Guarantees that other companies' datasets are unaffected.
    Fails if the dataset has not been reviewed and approved.
    """
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    try:
        dataset = activate_dataset(db, dataset_id, company_id=tenant_company_id)
        return _serialize_dataset_summary(dataset)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate dataset: {str(exc)}",
        )


@router.get("", response_model=List[DatasetSummaryResponse])
def list_datasets(
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Lists all dataset versions registered for the authorized company."""
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    stmt = select(DynamicDataset).order_by(desc(DynamicDataset.version), desc(DynamicDataset.created_at))
    if tenant_company_id is not None:
        stmt = stmt.where(DynamicDataset.company_id == tenant_company_id)
    elif current_user.role != "super_owner":
        stmt = stmt.where(DynamicDataset.company_id.is_(None))

    datasets = db.execute(stmt).scalars().all()
    return [_serialize_dataset_summary(d) for d in datasets]


@router.get("/active", response_model=Optional[DatasetDetailResponse])
def get_currently_active_dataset(
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Returns the currently active dataset for the authorized tenant company."""
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    d = get_active_dataset(db, company_id=tenant_company_id)
    if not d:
        return None
    return _serialize_dataset_detail(d)


@router.get("/companies", response_model=List[Dict[str, Any]])
def list_available_companies(
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Lists companies accessible to the user."""
    if current_user.role == "admin":
        if not current_user.company_id:
            return []
        c = db.get(Company, current_user.company_id)
        return [{"id": str(c.id), "name": c.name, "contact_email": c.contact_email}] if c else []

    comps = db.execute(select(Company).order_by(Company.name)).scalars().all()
    return [{"id": str(c.id), "name": c.name, "contact_email": c.contact_email} for c in comps]


@router.post("/preview-query", response_model=DatasetPreviewQueryResponse)
def preview_dataset_query_endpoint(
    req: DatasetPreviewQueryRequest,
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """
    Offline Query Preview:
    Executes a sample query against the approved/active dataset strictly in offline mode.
    Tests dynamic token scoring, multi-field filtering, voice summary synthesis,
    and guarantees unapproved fields are stripped. Zero Bedrock / AWS calls.
    """
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )
    from app.services.dataset.retrieval import query_universal_dataset

    try:
        result = query_universal_dataset(
            db=db,
            company_id=tenant_company_id,
            dataset_id=req.dataset_id,
            query_text=req.query_text,
            filters=req.filters,
            sort_by=req.sort_by,
            sort_order=req.sort_order,
            limit=req.limit or 5,
        )
        return DatasetPreviewQueryResponse(
            dataset_id=str(result.get("dataset_id") or (req.dataset_id or "")),
            dataset_name=str(result.get("dataset_name", "")),
            dataset_version=int(result.get("dataset_version", 1)),
            total_matches=int(result.get("total_matches", 0)),
            records=[
                DatasetPreviewRecord(
                    id=str(r.get("record_id") or r.get("id", "")),
                    sheet_name=str(r.get("sheet_name", "Sheet1")),
                    display_title=str(r.get("display_identifier") or r.get("display_title", "")),
                    voice_summary=str(r.get("voice_summary", "")),
                    attributes=r.get("raw_attributes") or r.get("attributes", {}),
                )
                for r in result.get("records", [])
            ],
            voice_grounding=str(result.get("voice_grounding", "")),
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preview query failed: {str(exc)}",
        )


@router.get("/{dataset_id}", response_model=DatasetDetailResponse)
def get_dataset_by_id(
    dataset_id: uuid.UUID,
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Retrieves full details for a dataset belonging to the authorized company."""
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    stmt = select(DynamicDataset).where(DynamicDataset.id == dataset_id)
    if tenant_company_id is not None:
        stmt = stmt.where(DynamicDataset.company_id == tenant_company_id)

    d = db.execute(stmt).scalar_one_or_none()

    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found.")
    return _serialize_dataset_detail(d)


@router.post("/{dataset_id}/rollback")
def rollback_dataset_endpoint(
    dataset_id: uuid.UUID,
    company_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(require_role(["super_owner", "admin"])),
    db: Session = Depends(get_db),
):
    """Reverts to the previous approved dataset version within the company boundary."""
    tenant_company_id = resolve_tenant_company(
        current_user, db, requested_company_id=company_id, allow_platform_for_super_owner=True
    )

    try:
        return rollback_dataset(db, dataset_id, company_id=tenant_company_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rollback failed: {str(exc)}",
        )
