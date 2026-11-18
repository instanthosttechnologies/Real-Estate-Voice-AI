import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_log
from app.models.company import Company
from app.models.location import Location
from app.models.project import Project, Amenity, ProjectAmenity
from app.models.property import Property, PropertyUnit
from app.models.pricing import Pricing
from app.models.availability import Availability
from app.models.ingestion import IngestionBatch, IngestionRecord
from app.models.audit_log import AuditLog
from app.schemas.property import NormalizedPropertyRecord
from app.schemas.ingestion import (
    ConflictResolutionStrategy,
    IngestionPreviewResponse,
    IngestionResultResponse,
    RollbackResponse,
)
from app.services.ingestion.mapper import propose_mappings
from app.services.ingestion.parsers.csv_excel import parse_csv_bytes, parse_excel_bytes
from app.services.ingestion.parsers.json_parser import parse_json_bytes
from app.services.ingestion.parsers.pdf_parser import parse_pdf_bytes


def detect_and_parse(content: bytes, filename: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Detects format from filename/extension and delegates to appropriate parser.
    """
    lower = filename.lower()
    if lower.endswith(".csv"):
        return ("csv", parse_csv_bytes(content))
    elif lower.endswith((".xlsx", ".xls")):
        return ("excel", parse_excel_bytes(content))
    elif lower.endswith((".json", ".jsonl")):
        return ("json", parse_json_bytes(content))
    elif lower.endswith(".pdf"):
        return ("pdf", parse_pdf_bytes(content))
    else:
        # Default fallback to CSV
        try:
            return ("csv", parse_csv_bytes(content))
        except Exception:
            raise ValueError(f"Unsupported file format for file: {filename}")


def generate_preview(content: bytes, filename: str) -> IngestionPreviewResponse:
    """
    Extracts first 15 rows and generates column mapping proposals without database commits.
    """
    file_hash = hashlib.sha256(content).hexdigest()
    fmt, records = detect_and_parse(content, filename)

    if not records:
        raise ValueError(f"No valid records could be extracted from {filename}")

    # Gather all unique headers
    headers = list({k for row in records[:20] for k in row.keys()})
    preview_rows = records[:15]
    proposals = propose_mappings(headers, preview_rows)

    requires_manual = any(p.status.value == "requires_confirmation" for p in proposals)

    return IngestionPreviewResponse(
        filename=filename,
        file_format=fmt,
        file_hash=file_hash,
        total_preview_rows=len(preview_rows),
        detected_headers=headers,
        preview_rows=preview_rows,
        suggested_mappings=proposals,
        requires_manual_confirmation=requires_manual,
    )


def execute_ingestion_batch(
    db: Session,
    content: bytes,
    filename: str,
    confirmed_mappings: Dict[str, str],
    conflict_strategy: ConflictResolutionStrategy,
    user_id: uuid.UUID,
) -> IngestionResultResponse:
    """
    Executes normalized batch ingestion into the relational schema.
    Enforces Pydantic validation, deduplication, conflict strategy, provenance, and rollback snapshots.
    """
    file_hash = hashlib.sha256(content).hexdigest()
    fmt, records = detect_and_parse(content, filename)

    # 1. Create IngestionBatch provenance record
    batch = IngestionBatch(
        filename=filename,
        file_format=fmt,
        file_hash=file_hash,
        uploaded_by_user_id=user_id,
        status="processing",
        total_rows=len(records),
        mapping_config=confirmed_mappings,
        can_rollback=True,
    )
    db.add(batch)
    db.flush()

    imported_count = 0
    skipped_count = 0
    failed_count = 0
    error_summary: List[Dict[str, Any]] = []

    now = datetime.now(timezone.utc)

    # 2. Process each row
    for idx, raw_row in enumerate(records):
        # Apply confirmed mappings
        mapped_row: Dict[str, Any] = {}
        for src_col, target_field in confirmed_mappings.items():
            if src_col in raw_row and target_field:
                mapped_row[target_field] = raw_row[src_col]

        # Pydantic v2 validation
        try:
            validated = NormalizedPropertyRecord(**mapped_row)
        except Exception as exc:
            failed_count += 1
            error_summary.append({
                "row_index": idx,
                "error": str(exc),
                "raw": {k: str(v) for k, v in raw_row.items()}
            })
            continue

        # Relational Hierarchy Resolution
        # Company
        company_res = db.execute(select(Company).where(Company.name == validated.company_name))
        company = company_res.scalar_one_or_none()
        if not company:
            company = Company(name=validated.company_name)
            db.add(company)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="company", entity_id=company.id,
                source_row_index=idx, action_taken="INSERT"
            ))

        # Location
        loc_res = db.execute(select(Location).where(
            Location.city == validated.city,
            Location.postal_code == validated.postal_code,
            Location.address_line_1 == validated.address_line_1
        ))
        location = loc_res.scalar_one_or_none()
        if not location:
            location = Location(
                address_line_1=validated.address_line_1,
                city=validated.city,
                state=validated.state,
                postal_code=validated.postal_code,
            )
            db.add(location)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="location", entity_id=location.id,
                source_row_index=idx, action_taken="INSERT"
            ))

        # Project
        proj_res = db.execute(select(Project).where(
            Project.company_id == company.id,
            Project.name == validated.project_name
        ))
        project = proj_res.scalar_one_or_none()
        if not project:
            project = Project(
                company_id=company.id,
                location_id=location.id,
                name=validated.project_name
            )
            db.add(project)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="project", entity_id=project.id,
                source_row_index=idx, action_taken="INSERT"
            ))

        # Property (Tower/Phase)
        prop_res = db.execute(select(Property).where(
            Property.project_id == project.id,
            Property.name == validated.property_name
        ))
        property_obj = prop_res.scalar_one_or_none()
        if not property_obj:
            property_obj = Property(
                project_id=project.id,
                name=validated.property_name,
                property_type="apartment"
            )
            db.add(property_obj)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="property", entity_id=property_obj.id,
                source_row_index=idx, action_taken="INSERT"
            ))

        # PropertyUnit (Natural key: property_id, unit_number)
        unit_res = db.execute(select(PropertyUnit).where(
            PropertyUnit.property_id == property_obj.id,
            PropertyUnit.unit_number == validated.unit_number
        ))
        unit = unit_res.scalar_one_or_none()

        if not unit:
            # New Unit insertion
            unit = PropertyUnit(
                property_id=property_obj.id,
                unit_number=validated.unit_number,
                configuration_type=validated.configuration_type,
                carpet_area_sqft=validated.carpet_area_sqft,
                super_built_up_area_sqft=validated.super_built_up_area_sqft,
                floor_number=validated.floor_number,
                facing=validated.facing,
            )
            db.add(unit)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="property_unit", entity_id=unit.id,
                source_row_index=idx, action_taken="INSERT"
            ))

            # Initial Pricing
            total_est = validated.total_estimated_price or validated.base_price
            pricing = Pricing(
                unit_id=unit.id,
                base_price=validated.base_price,
                currency=validated.currency,
                total_estimated_price=total_est,
                is_active=True,
                valid_from=now,
            )
            db.add(pricing)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="pricing", entity_id=pricing.id,
                source_row_index=idx, action_taken="INSERT"
            ))

            # Initial Availability
            avail = Availability(
                unit_id=unit.id,
                status=validated.availability_status,
                is_current=True,
                valid_from=now,
            )
            db.add(avail)
            db.flush()
            db.add(IngestionRecord(
                batch_id=batch.id, entity_type="availability", entity_id=avail.id,
                source_row_index=idx, action_taken="INSERT"
            ))

            imported_count += 1

        else:
            # Conflict / Existing Unit Detected
            if conflict_strategy == ConflictResolutionStrategy.SKIP:
                skipped_count += 1
                db.add(IngestionRecord(
                    batch_id=batch.id, entity_type="property_unit", entity_id=unit.id,
                    source_row_index=idx, action_taken="SKIP"
                ))
            else:
                # OVERWRITE or NEW_VERSION -> Preserve Pricing and Availability History
                # Fetch active pricing
                active_pricing_res = db.execute(select(Pricing).where(
                    Pricing.unit_id == unit.id,
                    Pricing.is_active == True
                ))
                active_pricing = active_pricing_res.scalar_one_or_none()
                prev_pricing_snap = None
                if active_pricing:
                    prev_pricing_snap = {
                        "pricing_id": str(active_pricing.id),
                        "base_price": float(active_pricing.base_price),
                        "is_active": active_pricing.is_active,
                        "valid_to": active_pricing.valid_to.isoformat() if active_pricing.valid_to else None,
                    }
                    active_pricing.is_active = False
                    active_pricing.valid_to = now

                # Add new active pricing
                total_est = validated.total_estimated_price or validated.base_price
                new_pricing = Pricing(
                    unit_id=unit.id,
                    base_price=validated.base_price,
                    currency=validated.currency,
                    total_estimated_price=total_est,
                    is_active=True,
                    valid_from=now,
                )
                db.add(new_pricing)
                db.flush()

                # Fetch active availability
                active_avail_res = db.execute(select(Availability).where(
                    Availability.unit_id == unit.id,
                    Availability.is_current == True
                ))
                active_avail = active_avail_res.scalar_one_or_none()
                prev_avail_snap = None
                if active_avail:
                    prev_avail_snap = {
                        "avail_id": str(active_avail.id),
                        "status": active_avail.status,
                        "is_current": active_avail.is_current,
                        "valid_to": active_avail.valid_to.isoformat() if active_avail.valid_to else None,
                    }
                    active_avail.is_current = False
                    active_avail.valid_to = now

                # Add new current availability
                new_avail = Availability(
                    unit_id=unit.id,
                    status=validated.availability_status,
                    is_current=True,
                    valid_from=now,
                )
                db.add(new_avail)
                db.flush()

                # Log update provenance with previous state snapshot
                db.add(IngestionRecord(
                    batch_id=batch.id,
                    entity_type="property_unit",
                    entity_id=unit.id,
                    source_row_index=idx,
                    action_taken="UPDATE",
                    previous_state={
                        "previous_pricing": prev_pricing_snap,
                        "previous_availability": prev_avail_snap,
                        "created_pricing_id": str(new_pricing.id),
                        "created_avail_id": str(new_avail.id),
                    }
                ))
                imported_count += 1

    # 3. Finalize IngestionBatch
    batch.status = "completed" if failed_count == 0 else "completed_with_errors"
    batch.imported_rows = imported_count
    batch.skipped_rows = skipped_count
    batch.failed_rows = failed_count
    batch.error_summary = error_summary
    batch.completed_at = datetime.now(timezone.utc)
    db.commit()

    return IngestionResultResponse(
        batch_id=batch.id,
        status=batch.status,
        total_rows=batch.total_rows,
        imported_rows=batch.imported_rows,
        skipped_rows=batch.skipped_rows,
        failed_rows=batch.failed_rows,
        error_summary=error_summary,
        can_rollback=batch.can_rollback,
    )


def execute_rollback(
    db: Session,
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
    user_role: str,
) -> RollbackResponse:
    """
    Safely rolls back an ingestion batch in reverse dependency order.
    Deletes inserted records and restores previous states for updated records.
    Records an immutable audit log.
    """
    batch_res = db.execute(select(IngestionBatch).where(IngestionBatch.id == batch_id))
    batch = batch_res.scalar_one_or_none()
    if not batch:
        raise ValueError(f"Ingestion batch {batch_id} not found.")
    if not batch.can_rollback:
        raise ValueError(f"Batch {batch_id} is not eligible for rollback (already rolled back or locked).")

    records_res = db.execute(
        select(IngestionRecord)
        .where(IngestionRecord.batch_id == batch_id)
        .order_by(IngestionRecord.created_at.desc())
    )
    records = records_res.scalars().all()

    reverted_count = 0

    for rec in records:
        if rec.action_taken == "INSERT":
            # Delete the inserted entity
            if rec.entity_type == "pricing":
                obj = db.get(Pricing, rec.entity_id)
                if obj:
                    db.delete(obj)
            elif rec.entity_type == "availability":
                obj = db.get(Availability, rec.entity_id)
                if obj:
                    db.delete(obj)
            elif rec.entity_type == "property_unit":
                obj = db.get(PropertyUnit, rec.entity_id)
                if obj:
                    db.delete(obj)
            elif rec.entity_type == "property":
                obj = db.get(Property, rec.entity_id)
                if obj and len(obj.units) == 0:
                    db.delete(obj)
            elif rec.entity_type == "project":
                obj = db.get(Project, rec.entity_id)
                if obj and len(obj.properties) == 0:
                    db.delete(obj)
            elif rec.entity_type == "location":
                obj = db.get(Location, rec.entity_id)
                if obj and len(obj.projects) == 0:
                    db.delete(obj)
            elif rec.entity_type == "company":
                obj = db.get(Company, rec.entity_id)
                if obj and len(obj.projects) == 0:
                    db.delete(obj)
            reverted_count += 1

        elif rec.action_taken == "UPDATE" and rec.previous_state:
            # Restore previous state
            snap = rec.previous_state
            # Delete newly created pricing & availability
            if "created_pricing_id" in snap:
                created_p = db.get(Pricing, uuid.UUID(snap["created_pricing_id"]))
                if created_p:
                    db.delete(created_p)
            if "created_avail_id" in snap:
                created_a = db.get(Availability, uuid.UUID(snap["created_avail_id"]))
                if created_a:
                    db.delete(created_a)

            # Reactivate previous pricing
            if "previous_pricing" in snap and snap["previous_pricing"]:
                old_p_id = uuid.UUID(snap["previous_pricing"]["pricing_id"])
                old_p = db.get(Pricing, old_p_id)
                if old_p:
                    old_p.is_active = True
                    old_p.valid_to = None

            # Reactivate previous availability
            if "previous_availability" in snap and snap["previous_availability"]:
                old_a_id = uuid.UUID(snap["previous_availability"]["avail_id"])
                old_a = db.get(Availability, old_a_id)
                if old_a:
                    old_a.is_current = True
                    old_a.valid_to = None
            reverted_count += 1

    batch.status = "rolled_back"
    batch.can_rollback = False

    # Immutable Audit Log
    db.add(AuditLog(
        user_id=user_id,
        user_role=user_role,
        action="EXECUTE_INGESTION_ROLLBACK",
        resource_type="ingestion_batch",
        resource_id=str(batch.id),
        meta_info={"reverted_records_count": reverted_count, "filename": batch.filename},
    ))
    db.commit()

    return RollbackResponse(
        batch_id=batch.id,
        status="rolled_back",
        message="Batch rollback successfully executed in reverse dependency order.",
        reverted_records_count=reverted_count,
    )
