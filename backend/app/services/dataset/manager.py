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
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.services.dataset.inspector import inspect_dataset_workbook

logger = logging.getLogger("dataset_manager")


def _normalize_string(val: Any) -> str:
    """Normalizes string for search token matching while preserving raw value separately."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("null", "none", "n/a", "na", ""):
        return ""
    # Strip excessive punctuation for normalized token matching
    s = re.sub(r"[\t\r\n]+", " ", s)
    return s


def build_voice_summary(row: Dict[str, Any], meta_summary: Dict[str, Any]) -> str:
    """
    Renders a concise, factual, spoken-language summary for Amazon Nova 2.5 Sonic.
    Prioritizes pre-built NOVA_SONIC_VOICE_CONTEXT if present in dataset.
    Otherwise builds a concise natural grounding without null/hallucinated fields.
    """
    # 1. Use pre-built context if available (like in Unified_AI_Dataset)
    if "NOVA_SONIC_VOICE_CONTEXT" in row and row["NOVA_SONIC_VOICE_CONTEXT"]:
        ctx = str(row["NOVA_SONIC_VOICE_CONTEXT"]).strip()
        if ctx.lower() not in ("null", "none", ""):
            return ctx[:1000]

    # 2. Dynamic generation based on detected columns
    parts = []
    comp_col = meta_summary.get("developers_column")
    proj_col = meta_summary.get("projects_column")
    loc_col = meta_summary.get("location_column")
    cfg_col = meta_summary.get("config_column")
    stat_col = meta_summary.get("status_column")
    amen_col = meta_summary.get("amenities_column")

    comp = str(row.get(comp_col, "")).strip() if comp_col and row.get(comp_col) else ""
    proj = str(row.get(proj_col, "")).strip() if proj_col and row.get(proj_col) else ""
    loc = str(row.get(loc_col, "")).strip() if loc_col and row.get(loc_col) else ""
    cfg = str(row.get(cfg_col, "")).strip() if cfg_col and row.get(cfg_col) else ""
    stat = str(row.get(stat_col, "")).strip() if stat_col and row.get(stat_col) else ""
    amen = str(row.get(amen_col, "")).strip() if amen_col and row.get(amen_col) else ""

    if not proj:
        for k in row:
            if any(term in k.upper() for term in ["NAME", "TITLE", "FACILITY", "PROJECT"]) and row[k]:
                val = str(row[k]).strip()
                if val.lower() not in ("null", "none"):
                    proj = val
                    break

    if proj and proj.lower() not in ("null", "none"):
        parts.append(f"Project: {proj}")
    if comp and comp.lower() not in ("null", "none"):
        parts.append(f"Developer: {comp}")
    if loc and loc.lower() not in ("null", "none"):
        parts.append(f"Location: {loc}")
    if cfg and cfg.lower() not in ("null", "none", "not stated in overview"):
        parts.append(f"Configuration: {cfg}")
    if stat and stat.lower() not in ("null", "none"):
        parts.append(f"Status: {stat}")
    if amen and amen.lower() not in ("null", "none", "refer to official project brochure"):
        parts.append(f"Amenities: {amen[:150]}")

    if not parts:
        # Fallback to key-value pairs of first 4 non-null columns
        for k, v in list(row.items())[:5]:
            if v and str(v).lower() not in ("null", "none", ""):
                parts.append(f"{k}: {v}")

    return ". ".join(parts) + "." if parts else "Real estate dataset record."


def upload_and_import_dataset(
    db: Session,
    file_bytes: bytes,
    filename: str,
    user_id: Optional[uuid.UUID] = None,
    auto_activate: bool = False,
    dataset_name: Optional[str] = None,
) -> DynamicDataset:
    """
    Imports any dynamic dataset (Excel or CSV), inspects schemas and cross-sheet relationships,
    creates metadata registry, preserves exact raw records, builds normalized search indices,
    and isolates records by dataset version.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # 1. Inspect workbook/file
    inspection = inspect_dataset_workbook(file_bytes, filename)
    meta = inspection["metadata_registry"]
    primary_sheet = inspection["primary_sheet"]
    sheets_data = inspection["sheets_data"]
    total_rows = inspection["total_rows"]

    # 2. Determine version number
    clean_name = dataset_name or filename.rsplit(".", 1)[0]
    existing_versions = db.execute(
        select(func.max(DynamicDataset.version)).where(DynamicDataset.name == clean_name)
    ).scalar() or 0
    new_version = existing_versions + 1

    # 3. Create DynamicDataset entity
    dataset = DynamicDataset(
        name=clean_name,
        filename=filename,
        file_hash=file_hash,
        version=new_version,
        is_active=False,
        status="uploaded",
        uploaded_by_user_id=user_id,
        primary_sheet=primary_sheet,
        total_rows=total_rows,
        metadata_registry=meta,
    )
    db.add(dataset)
    db.flush()

    meta_summary = meta.get("summary", {})

    # 4. Insert records preserving exact raw data & building normalized indices
    record_objs: List[DynamicDatasetRecord] = []

    # Insert primary sheet first, then supporting sheets
    ordered_sheets = [primary_sheet] + [s for s in sheets_data if s != primary_sheet]

    for sheet_name in ordered_sheets:
        sheet_info = sheets_data[sheet_name]
        candidate_keys = sheet_info.get("candidate_identifiers", [])
        primary_key_col = candidate_keys[0] if candidate_keys else None

        for row_idx, raw_row in enumerate(sheet_info.get("records", [])):
            # Determine identifier
            rec_id = None
            if primary_key_col and raw_row.get(primary_key_col):
                rec_id = str(raw_row[primary_key_col])[:250]
            elif "RECORD_ID" in raw_row and raw_row["RECORD_ID"]:
                rec_id = str(raw_row["RECORD_ID"])[:250]
            else:
                rec_id = f"{sheet_name}_{row_idx+1}"[:250]

            # Normalized search dictionary
            norm_search = {
                k.lower(): _normalize_string(v)
                for k, v in raw_row.items()
            }
            # Combined text tokens for fast multi-field matching
            combined_tokens = " ".join(v for v in norm_search.values() if v)
            norm_search["_all_tokens"] = combined_tokens

            # Concise voice summary for Nova Sonic
            v_summary = build_voice_summary(raw_row, meta_summary)

            rec_obj = DynamicDatasetRecord(
                dataset_id=dataset.id,
                sheet_name=sheet_name,
                row_index=row_idx,
                record_identifier=rec_id,
                raw_data=raw_row,
                normalized_search=norm_search,
                voice_summary=v_summary,
            )
            record_objs.append(rec_obj)

            # Flush in batches of 500
            if len(record_objs) >= 500:
                db.add_all(record_objs)
                db.flush()
                record_objs.clear()

    if record_objs:
        db.add_all(record_objs)
        db.flush()

    logger.info(
        f"Imported DynamicDataset {dataset.name} v{dataset.version} ({dataset.id}) "
        f"with {total_rows} primary records across {len(sheets_data)} sheets."
    )

    if auto_activate:
        activate_dataset(db, dataset.id)

    db.commit()
    db.refresh(dataset)
    return dataset


def activate_dataset(db: Session, dataset_id: uuid.UUID) -> DynamicDataset:
    """
    Designates the specified dataset as the active source of truth.
    Deactivates any previously active datasets, ensuring zero cross-dataset leakage.
    """
    # 1. Deactivate all existing datasets
    db.execute(
        update(DynamicDataset)
        .where(DynamicDataset.is_active == True)
        .values(is_active=False)
    )

    # 2. Activate target dataset
    target = db.execute(
        select(DynamicDataset).where(DynamicDataset.id == dataset_id)
    ).scalar_one_or_none()

    if not target:
        raise ValueError(f"Dataset {dataset_id} not found.")

    target.is_active = True
    target.status = "active"
    target.activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(target)

    logger.info(f"Activated DynamicDataset {target.name} v{target.version} ({target.id})")
    return target


def rollback_dataset(db: Session, dataset_id: uuid.UUID) -> Dict[str, Any]:
    """
    Rolls back an active dataset and reverts to the previously activated version.
    """
    target = db.execute(
        select(DynamicDataset).where(DynamicDataset.id == dataset_id)
    ).scalar_one_or_none()

    if not target:
        raise ValueError(f"Dataset {dataset_id} not found.")

    target.is_active = False
    target.status = "rolled_back"

    # Find previous version of same dataset or latest other valid dataset
    prev = db.execute(
        select(DynamicDataset)
        .where(
            DynamicDataset.id != dataset_id,
            DynamicDataset.status != "rolled_back"
        )
        .order_by(desc(DynamicDataset.created_at))
    ).scalars().first()

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
        "status": "rolled_back",
        "reverted_to": reverted_to,
    }


def get_active_dataset(db: Session) -> Optional[DynamicDataset]:
    """Retrieves the single currently authorized active dataset."""
    return db.execute(
        select(DynamicDataset).where(DynamicDataset.is_active == True)
    ).scalar_one_or_none()
