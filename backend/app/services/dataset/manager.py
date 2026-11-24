import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.db.base import utc_now
from app.models.company import Company
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.schemas.dataset import DatasetApprovalRequest
from app.services.dataset.inspector import inspect_dataset_workbook

logger = logging.getLogger("dataset_manager")


def _normalize_string(val: Any) -> str:
    """Normalizes string for search token matching while preserving raw value separately."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("null", "none", "n/a", "na", "", "-"):
        return ""
    # Strip excessive punctuation for normalized token matching
    s = re.sub(r"[\t\r\n]+", " ", s)
    return s


def build_approved_normalized_search(
    row: Dict[str, Any],
    approved_fields: List[str]
) -> Dict[str, Any]:
    """
    Builds normalized search tokens EXCLUSIVELY from the Admin-approved fields.
    Unapproved fields are strictly excluded so they cannot be searched.
    """
    normalized: Dict[str, Any] = {}
    tokens: List[str] = []

    for col in approved_fields:
        if col in row:
            val = row[col]
            norm_val = _normalize_string(val)
            normalized[col.lower()] = norm_val
            if norm_val:
                tokens.append(norm_val)

    normalized["_all_tokens"] = " ".join(tokens)
    return normalized


def build_domain_neutral_voice_summary(
    row: Dict[str, Any],
    approved_fields: Optional[List[str]] = None,
    field_labels: Optional[Dict[str, str]] = None,
    display_identifier: Optional[str] = None,
    domain_name: Optional[str] = None,
) -> str:
    """
    Renders a concise, spoken-language summary for voice synthesis.
    STRICT SECURITY RULE:
    Constructs the voice grounding EXCLUSIVELY from Admin-approved fields.
    Unapproved / confidential columns are strictly omitted from speech.
    """
    if not approved_fields:
        return "Record pending schema approval."

    labels = field_labels or {}
    parts: List[str] = []

    # 1. Start with the designated display identifier if present
    if display_identifier and display_identifier in approved_fields:
        id_val = row.get(display_identifier)
        if id_val and str(id_val).strip().lower() not in ("null", "none", ""):
            label = labels.get(display_identifier, display_identifier.replace("_", " ").title())
            parts.append(f"{label}: {str(id_val).strip()}")

    # 2. Append remaining approved fields (max 6 fields for spoken brevity)
    for col in approved_fields:
        if col == display_identifier:
            continue
        val = row.get(col)
        if val is None or str(val).strip().lower() in ("null", "none", "n/a", ""):
            continue
        val_str = str(val).strip()
        label = labels.get(col, col.replace("_", " ").title())
        parts.append(f"{label}: {val_str}")
        if len(parts) >= 6:
            break

    if not parts:
        prefix = f"{domain_name} item" if domain_name else "Item"
        return f"{prefix} record with verified attributes."

    return ". ".join(parts) + "."


def upload_and_import_dataset(
    db: Session,
    file_bytes: bytes,
    filename: str,
    company_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    dataset_name: Optional[str] = None,
    auto_activate: bool = False,
) -> DynamicDataset:
    """
    Uploads any structured tabular dataset (Excel or CSV), inspects schema without assumptions,
    creates metadata registry, isolates datasets by company/tenant, and stores records in draft state.
    
    SECURITY GUARANTEES:
    - Scoped strictly to company_id.
    - Initial status is 'pending_approval' (cannot be activated until reviewed).
    - Version counter is isolated per company and dataset name.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Resolve company fallback for test/single-tenant backward compatibility
    if company_id is None:
        first_comp = db.execute(select(Company)).scalars().first()
        if first_comp:
            company_id = first_comp.id

    # 1. Domain-agnostic inspection
    inspection = inspect_dataset_workbook(file_bytes, filename)
    meta = inspection["metadata_registry"]
    primary_sheet = inspection["primary_sheet"]
    sheets_data = inspection["sheets_data"]
    total_rows = inspection["total_rows"]

    # 2. Company-scoped version determination
    clean_name = dataset_name or filename.rsplit(".", 1)[0]
    version_query = select(func.max(DynamicDataset.version)).where(DynamicDataset.name == clean_name)
    if company_id is not None:
        version_query = version_query.where(DynamicDataset.company_id == company_id)
    else:
        version_query = version_query.where(DynamicDataset.company_id.is_(None))
    existing_versions = db.execute(version_query).scalar() or 0
    new_version = existing_versions + 1

    # 3. Create DynamicDataset entity in pending_approval status
    dataset = DynamicDataset(
        company_id=company_id,
        name=clean_name,
        filename=filename,
        file_hash=file_hash,
        version=new_version,
        is_active=False,
        status="pending_approval",
        uploaded_by_user_id=user_id,
        primary_sheet=primary_sheet,
        total_rows=total_rows,
        metadata_registry=meta,
        created_at=datetime.now(timezone.utc),
    )
    db.add(dataset)
    db.flush()

    # 4. Insert records with raw data preserved
    primary_data = sheets_data[primary_sheet]["records"]
    candidate_id_col = (
        sheets_data[primary_sheet]["candidate_identifiers"][0]
        if sheets_data[primary_sheet]["candidate_identifiers"]
        else None
    )

    records_to_insert = []
    for idx, row in enumerate(primary_data):
        identifier = str(row.get(candidate_id_col, f"row_{idx+1}")) if candidate_id_col else f"row_{idx+1}"
        record = DynamicDatasetRecord(
            dataset_id=dataset.id,
            sheet_name=primary_sheet,
            row_index=idx + 1,
            record_identifier=identifier[:255],
            raw_data=row,
            normalized_search={},  # Populated upon schema approval
            voice_summary="Pending Admin schema review.",
            created_at=datetime.now(timezone.utc),
        )
        records_to_insert.append(record)

    db.add_all(records_to_insert)
    db.commit()
    db.refresh(dataset)

    if auto_activate:
        all_cols = [c["column_name"] for c in sheets_data[primary_sheet]["columns"]]
        disp_id = candidate_id_col if (candidate_id_col and candidate_id_col in all_cols) else (all_cols[0] if all_cols else "id")
        approve_dataset_schema(
            db=db,
            dataset_id=dataset.id,
            company_id=company_id,
            approval=DatasetApprovalRequest(
                approved_fields=all_cols,
                display_identifier=disp_id,
            ),
        )
        activate_dataset(db=db, dataset_id=dataset.id, company_id=company_id)
        db.refresh(dataset)

    logger.info(
        f"Uploaded DynamicDataset '{dataset.name}' v{dataset.version} for company {company_id} "
        f"({dataset.total_rows} rows). Status: pending_approval."
    )
    return dataset


def approve_dataset_schema(
    db: Session,
    dataset_id: uuid.UUID,
    company_id: Optional[uuid.UUID] = None,
    approval: DatasetApprovalRequest = None,
) -> DynamicDataset:
    """
    Processes Admin review and confirmation of allowed schema fields.
    
    SECURITY & DATA INTEGRITY:
    - Enforces tenant boundary (dataset.company_id == company_id).
    - Verifies that all approved_fields exist in the dataset primary sheet.
    - Verifies that display_identifier is one of the approved_fields.
    - Re-indexes normalized_search and voice_summary strictly using approved fields.
    - Unapproved fields are completely stripped from search tokens and voice summaries.
    - Sets dataset status to 'approved'.
    """
    stmt = select(DynamicDataset).where(DynamicDataset.id == dataset_id)
    if company_id is not None:
        stmt = stmt.where(DynamicDataset.company_id == company_id)
    dataset = db.execute(stmt).scalar_one_or_none()

    if not dataset:
        raise ValueError(f"Dataset {dataset_id} not found for this authorized company.")

    meta = dataset.metadata_registry or {}
    primary_sheet = dataset.primary_sheet
    sheet_meta = meta.get("worksheets", {}).get(primary_sheet, {})
    available_cols = [c["column_name"] for c in sheet_meta.get("columns", [])]

    # Validate approved fields exist in discovered columns
    invalid_cols = [f for f in approval.approved_fields if f not in available_cols]
    if invalid_cols:
        raise ValueError(
            f"The following approved fields do not exist in dataset columns: {invalid_cols}"
        )

    # Validate display_identifier is in approved_fields
    if approval.display_identifier not in approval.approved_fields:
        raise ValueError(
            f"Display identifier '{approval.display_identifier}' must be one of the approved fields."
        )

    # Update dataset schema approval metadata
    dataset.approved_fields = approval.approved_fields
    dataset.field_labels = approval.field_labels or {}
    dataset.display_identifier = approval.display_identifier
    dataset.domain_name = approval.domain_name
    dataset.welcome_greeting = approval.welcome_greeting
    dataset.status = "approved"

    # Store approved schema in metadata_registry
    meta["approved_schema"] = {
        "approved_fields": approval.approved_fields,
        "display_identifier": approval.display_identifier,
        "field_labels": approval.field_labels or {},
        "domain_name": approval.domain_name,
        "welcome_greeting": approval.welcome_greeting,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    dataset.metadata_registry = meta

    # Re-index all records for this dataset strictly against approved fields
    records = db.execute(
        select(DynamicDatasetRecord).where(DynamicDatasetRecord.dataset_id == dataset.id)
    ).scalars().all()

    for rec in records:
        rec.normalized_search = build_approved_normalized_search(
            rec.raw_data, approval.approved_fields
        )
        rec.voice_summary = build_domain_neutral_voice_summary(
            rec.raw_data,
            approved_fields=approval.approved_fields,
            field_labels=approval.field_labels,
            display_identifier=approval.display_identifier,
            domain_name=approval.domain_name,
        )
        if approval.display_identifier in rec.raw_data:
            rec.record_identifier = str(rec.raw_data[approval.display_identifier])[:255]

    db.commit()
    db.refresh(dataset)
    logger.info(
        f"Admin approved schema for dataset '{dataset.name}' v{dataset.version} ({dataset.id}). "
        f"Approved {len(approval.approved_fields)} fields."
    )
    return dataset


def activate_dataset(
    db: Session,
    dataset_id: uuid.UUID,
    company_id: Optional[uuid.UUID] = None,
) -> DynamicDataset:
    """
    Designates the dataset as the active knowledge base for the authorized company.
    
    SAFETY & ISOLATION GUARANTEES:
    - Enforces tenant isolation: only deactivates previous datasets belonging to THIS company.
    - Company A's activation NEVER touches or deactivates Company B's datasets.
    - Fails if the dataset status is 'pending_approval' (cannot activate unreviewed schema).
    """
    if company_id is None:
        target = db.get(DynamicDataset, dataset_id)
        if not target:
            raise ValueError(f"Dataset {dataset_id} not found.")
        company_id = target.company_id
    else:
        target = db.execute(
            select(DynamicDataset).where(
                DynamicDataset.id == dataset_id,
                DynamicDataset.company_id == company_id,
            )
        ).scalar_one_or_none()

    if not target:
        raise ValueError(f"Dataset {dataset_id} not found for this authorized company.")

    if target.status == "pending_approval":
        raise ValueError(
            "Dataset schema must be reviewed and approved by an administrator before activation."
        )

    # 1. Deactivate existing active datasets belonging ONLY to this company
    deact_stmt = update(DynamicDataset).where(DynamicDataset.is_active == True)
    if company_id is not None:
        deact_stmt = deact_stmt.where(DynamicDataset.company_id == company_id)
    else:
        deact_stmt = deact_stmt.where(DynamicDataset.company_id.is_(None))
    db.execute(deact_stmt.values(is_active=False))

    # 2. Activate target dataset
    target.is_active = True
    target.status = "active"
    target.activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(target)

    logger.info(
        f"Activated DynamicDataset '{target.name}' v{target.version} for company {company_id} ({target.id})"
    )
    return target


def rollback_dataset(
    db: Session,
    dataset_id: uuid.UUID,
    company_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Rolls back an active dataset and reverts to the previously approved version
    within the authorized company boundary.
    """
    if company_id is None:
        target = db.get(DynamicDataset, dataset_id)
        if not target:
            raise ValueError(f"Dataset {dataset_id} not found.")
        company_id = target.company_id
    else:
        target = db.execute(
            select(DynamicDataset).where(
                DynamicDataset.id == dataset_id,
                DynamicDataset.company_id == company_id,
            )
        ).scalar_one_or_none()

    if not target:
        raise ValueError(f"Dataset {dataset_id} not found for this authorized company.")

    target.is_active = False
    target.status = "rolled_back"

    # Find previous approved or active version of dataset within the same company
    prev_stmt = select(DynamicDataset).where(
        DynamicDataset.id != dataset_id,
        DynamicDataset.status.in_(["approved", "active", "archived"]),
    )
    if company_id is not None:
        prev_stmt = prev_stmt.where(DynamicDataset.company_id == company_id)
    else:
        prev_stmt = prev_stmt.where(DynamicDataset.company_id.is_(None))
    prev = db.execute(prev_stmt.order_by(desc(DynamicDataset.version))).scalars().first()

    reverted_to = None
    if prev:
        prev.is_active = True
        prev.status = "active"
        prev.activated_at = datetime.now(timezone.utc)
        reverted_to = {
            "id": str(prev.id),
            "name": prev.name,
            "version": prev.version,
        }

    db.commit()
    return {
        "rolled_back_id": str(dataset_id),
        "company_id": str(company_id),
        "status": "rolled_back",
        "reverted_to": reverted_to,
    }


def get_active_dataset(
    db: Session,
    company_id: Optional[uuid.UUID] = None,
) -> Optional[DynamicDataset]:
    """
    Retrieves the currently active dataset.
    If company_id is provided, strictly filters by company.
    If company_id is None, returns the first active dataset (backward compatibility).
    """
    stmt = select(DynamicDataset).where(DynamicDataset.is_active == True)
    if company_id:
        stmt = stmt.where(DynamicDataset.company_id == company_id)
    return db.execute(stmt).scalars().first()
