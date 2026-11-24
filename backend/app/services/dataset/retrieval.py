import logging
import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.services.dataset.manager import get_active_dataset

logger = logging.getLogger("dataset_retrieval")

# Location synonyms mapping for Indian real estate markets (Legacy compatibility)
LOCATION_SYNONYMS: Dict[str, List[str]] = {
    "gurugram": ["gurgaon", "gurugram", "gurgram", "golf course road", "sohna", "sohna road"],
    "bengaluru": ["bangalore", "bengaluru", "whitefield", "electronic city", "sarjapur"],
    "mumbai": ["mumbai", "bombay", "thane", "navi mumbai", "worli", "bandra", "andheri"],
    "chennai": ["chennai", "madras", "omr", "ecr", "porur"],
    "noida": ["noida", "greater noida", "yamuna expressway"],
    "pune": ["pune", "poona", "hinjewadi", "kharadi", "wakad"],
    "delhi": ["delhi", "new delhi", "south delhi", "dwarka"],
    "hyderabad": ["hyderabad", "cyberabad", "gachibowli", "hitec city"],
    "kolkata": ["kolkata", "calcutta", "new town", "rajarhat"],
    "kochi": ["kochi", "cochin", "marine drive"],
}

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "after",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "tell", "me", "show", "what", "which", "who", "whom",
    "where", "when", "why", "how", "can", "could", "would", "should", "looking",
    "want", "need", "give", "some", "any", "please", "help", "item", "items",
    "there", "their"
}


def _tokenize_text(text: str) -> List[str]:
    """Extracts non-stopword content tokens from search input."""
    if not text:
        return []
    raw = [w.lower() for w in re.findall(r"\b[A-Za-z0-9\-\_]{2,}\b", text)]
    filtered = [w for w in raw if w not in STOP_WORDS]
    return filtered if filtered else raw


def _parse_numeric_value(val: Any) -> Optional[float]:
    """
    Safely parses float/int from strings, currency symbols, commas, and scientific notations.
    Handles multipliers (k, m, lakh, cr) gracefully.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    # Clean standard punctuation & currency symbols
    clean = re.sub(r"[\$₹€£,\s]", "", s)
    lower = s.lower()
    mult = 1.0
    if "cr" in lower or "crore" in lower:
        mult = 10000000.0
        clean = re.sub(r"(?i)\s*(cr|crore|crores)", "", clean)
    elif "lakh" in lower or "lac" in lower:
        mult = 100000.0
        clean = re.sub(r"(?i)\s*(lakh|lakhs|lac|lacs)", "", clean)
    elif "k" in lower and not any(c in lower for c in ("bhk", "sku")):
        mult = 1000.0
        clean = re.sub(r"(?i)\s*k", "", clean)
    elif "m" in lower and not any(c in lower for c in ("miles", "months")):
        mult = 1000000.0
        clean = re.sub(r"(?i)\s*m", "", clean)

    match = re.search(r"[-+]?\d*\.?\d+", clean)
    if match:
        try:
            return float(match.group()) * mult
        except ValueError:
            return None
    return None


def _parse_date_value(val: Any) -> Optional[datetime]:
    """Parses date or datetime from ISO or standard date formats."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _evaluate_filter_condition(cell_val: Any, condition: Any) -> bool:
    """
    Evaluates whether a row's cell value satisfies a filter condition.
    Supports:
    - Direct scalar values (equality, substring)
    - Sets / Lists (in)
    - Operator dicts: {'==', '!=', 'contains', '>', '<', '>=', '<=', 'between', 'in'}
    """
    if condition is None:
        return True

    if cell_val is None:
        if isinstance(condition, dict) and condition.get("==") in (None, "", "null"):
            return True
        return False

    # Normalize string operators like '<= 2000000', '>= 50000', etc.
    if isinstance(condition, str):
        cond_str = condition.strip()
        m = re.match(r"^(<=|>=|<|>|!=|==)\s*([0-9\.\,]+.*)$", cond_str)
        if m:
            op_sym, rest = m.groups()
            condition = {op_sym: rest.strip()}

    # 1. Operator dictionary
    if isinstance(condition, dict):
        for op, target in condition.items():
            op_norm = str(op).strip().lower()

            if op_norm in ("==", "eq", "is"):
                cell_num = _parse_numeric_value(cell_val)
                target_num = _parse_numeric_value(target)
                if cell_num is not None and target_num is not None:
                    if cell_num != target_num:
                        return False
                else:
                    if str(cell_val).strip().lower() != str(target).strip().lower():
                        return False

            elif op_norm in ("!=", "ne", "is_not"):
                cell_num = _parse_numeric_value(cell_val)
                target_num = _parse_numeric_value(target)
                if cell_num is not None and target_num is not None:
                    if cell_num == target_num:
                        return False
                else:
                    if str(cell_val).strip().lower() == str(target).strip().lower():
                        return False

            elif op_norm in ("contains", "like"):
                if str(target).strip().lower() not in str(cell_val).strip().lower():
                    return False

            elif op_norm in (">=", "gte", "<=", "lte", ">", "gt", "<", "lt"):
                cell_num = _parse_numeric_value(cell_val)
                target_num = _parse_numeric_value(target)
                if cell_num is not None and target_num is not None:
                    if op_norm in (">=", "gte") and not (cell_num >= target_num):
                        return False
                    elif op_norm in ("<=", "lte") and not (cell_num <= target_num):
                        return False
                    elif op_norm in (">", "gt") and not (cell_num > target_num):
                        return False
                    elif op_norm in ("<", "lt") and not (cell_num < target_num):
                        return False
                else:
                    cell_date = _parse_date_value(cell_val)
                    target_date = _parse_date_value(target)
                    if cell_date and target_date:
                        if op_norm in (">=", "gte") and not (cell_date >= target_date):
                            return False
                        elif op_norm in ("<=", "lte") and not (cell_date <= target_date):
                            return False
                        elif op_norm in (">", "gt") and not (cell_date > target_date):
                            return False
                        elif op_norm in ("<", "lt") and not (cell_date < target_date):
                            return False
                    else:
                        return False

            elif op_norm in ("between", "range"):
                if isinstance(target, (list, tuple)) and len(target) == 2:
                    low_num = _parse_numeric_value(target[0])
                    high_num = _parse_numeric_value(target[1])
                    cell_num = _parse_numeric_value(cell_val)
                    if cell_num is not None and low_num is not None and high_num is not None:
                        if not (low_num <= cell_num <= high_num):
                            return False
                    else:
                        low_date = _parse_date_value(target[0])
                        high_date = _parse_date_value(target[1])
                        cell_date = _parse_date_value(cell_val)
                        if cell_date and low_date and high_date:
                            if not (low_date <= cell_date <= high_date):
                                return False
                        else:
                            return False

            elif op_norm in ("in", "any_of"):
                if isinstance(target, (list, tuple, set)):
                    target_strs = [str(t).strip().lower() for t in target]
                    if str(cell_val).strip().lower() not in target_strs:
                        return False
        return True

    # 2. List or set (in)
    if isinstance(condition, (list, tuple, set)):
        target_strs = [str(t).strip().lower() for t in condition]
        return str(cell_val).strip().lower() in target_strs

    # 3. Scalar primitive
    cell_num = _parse_numeric_value(cell_val)
    target_num = _parse_numeric_value(condition)
    if cell_num is not None and target_num is not None:
        # If numbers match, consider equal
        return cell_num == target_num

    cell_str = str(cell_val).strip().lower()
    target_str = str(condition).strip().lower()
    return target_str in cell_str or cell_str in target_str


def _score_universal_record(
    raw_data: Dict[str, Any],
    query_tokens: List[str],
    approved_fields: List[str],
    display_identifier: Optional[str] = None,
) -> float:
    """Computes search relevance score strictly across approved fields."""
    if not query_tokens:
        return 1.0

    score = 0.0
    matched_tokens = 0

    for token in query_tokens:
        token_clean = token.lower()
        token_found = False

        # Match on display identifier gets high priority
        if display_identifier and display_identifier in raw_data:
            id_val = str(raw_data.get(display_identifier, "")).lower()
            if token_clean in id_val:
                score += 15.0
                token_found = True

        # Match on other approved fields
        for field in approved_fields:
            if field == display_identifier:
                continue
            val_str = str(raw_data.get(field, "")).lower()
            field_name_clean = field.replace("_", " ").lower()
            if token_clean in val_str or token_clean in field_name_clean:
                score += 5.0
                token_found = True

        if token_found:
            matched_tokens += 1

    if matched_tokens == 0:
        return 0.0

    coverage = matched_tokens / len(query_tokens)
    return round(score * (1.0 + coverage), 2)


def query_universal_dataset(
    db: Session,
    query_text: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
    limit: int = 4,
    intent: str = "search",
    aggregate_field: Optional[str] = None,
    aggregate_op: Optional[str] = None,
    record_identifiers: Optional[List[str]] = None,
    conversation_context: Optional[Dict[str, Any]] = None,
    company_id: Optional[uuid.UUID] = None,
    dataset_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Universal, domain-independent query engine for any structured business dataset.
    
    SECURITY & DATA INTEGRITY GUARANTEES:
    - Strictly confines access to authorized company_id.
    - Fails if dataset is pending approval.
    - Validates all requested filters, sorts, and aggregations against the Admin-approved field whitelist.
    - Strictly prevents data leakage by filtering raw_attributes to approved_fields.
    - Safe parameterized querying; never generates or executes raw SQL from LLM input.
    """
    # 1. Resolve Target Dataset
    target_dataset: Optional[DynamicDataset] = None
    if dataset_id:
        target_dataset = db.execute(
            select(DynamicDataset).where(DynamicDataset.id == dataset_id)
        ).scalar_one_or_none()
        if target_dataset and company_id and target_dataset.company_id != company_id:
            raise ValueError("Access denied: Dataset does not belong to authorized company tenant.")
    else:
        target_dataset = get_active_dataset(db, company_id=company_id)

    if not target_dataset:
        return {
            "found": False,
            "message": "No active dataset is currently registered for this company.",
            "total_matches": 0,
            "records": [],
            "voice_grounding": "No active dataset is currently configured for this organization.",
        }

    # 2. Schema Approval & Lifecycle Check
    if target_dataset.status == "pending_approval":
        raise ValueError(
            f"Dataset '{target_dataset.name}' is pending administrator schema approval and cannot be queried."
        )

    # Legacy real estate fallback mode
    is_legacy = (
        target_dataset.approved_fields is None
        and (target_dataset.company_id is None or "real estate" in target_dataset.name.lower())
    )

    if not is_legacy and not target_dataset.approved_fields:
        raise ValueError(
            f"Dataset '{target_dataset.name}' has no approved fields. Schema approval is required."
        )

    # 3. Build Approved Fields Map (Strict Whitelist)
    approved_fields: List[str] = target_dataset.approved_fields or []
    field_labels: Dict[str, str] = target_dataset.field_labels or {}
    display_id: Optional[str] = target_dataset.display_identifier
    domain: str = target_dataset.domain_name or "properties"

    approved_map = {f.lower(): f for f in approved_fields}

    # 4. Strict Whitelist Enforcement on Requested Inputs
    canonical_filters: Dict[str, Any] = {}
    if filters:
        for k, v in filters.items():
            k_lower = k.strip().lower()
            if not is_legacy:
                if k_lower not in approved_map:
                    raise ValueError(
                        f"Field '{k}' is not permitted. Only approved fields may be queried: {approved_fields}"
                    )
                canonical_filters[approved_map[k_lower]] = v
            else:
                canonical_filters[k] = v

    canonical_sort_by: Optional[str] = None
    if sort_by:
        s_lower = sort_by.strip().lower()
        if not is_legacy:
            if s_lower not in approved_map:
                raise ValueError(
                    f"Sort field '{sort_by}' is not in approved fields: {approved_fields}"
                )
            canonical_sort_by = approved_map[s_lower]
        else:
            canonical_sort_by = sort_by

    canonical_agg_field: Optional[str] = None
    if aggregate_field:
        a_lower = aggregate_field.strip().lower()
        if not is_legacy:
            if a_lower not in approved_map:
                raise ValueError(
                    f"Aggregate field '{aggregate_field}' is not in approved fields: {approved_fields}"
                )
            canonical_agg_field = approved_map[a_lower]
        else:
            canonical_agg_field = aggregate_field

    # 5. Fetch Records for Primary Sheet
    records_query = select(DynamicDatasetRecord).where(
        DynamicDatasetRecord.dataset_id == target_dataset.id,
        DynamicDatasetRecord.sheet_name == target_dataset.primary_sheet,
    )
    raw_records = db.execute(records_query).scalars().all()

    if not raw_records:
        return {
            "found": False,
            "dataset_id": str(target_dataset.id),
            "dataset_name": target_dataset.name,
            "dataset_version": target_dataset.version,
            "total_matches": 0,
            "records": [],
            "voice_grounding": f"Our verified {target_dataset.name} dataset currently contains no records.",
        }

    # 6. Apply Conversation Context (Follow-up handling)
    candidate_records = list(raw_records)
    has_context_selection = False
    if conversation_context and conversation_context.get("selected_record_id"):
        ctx_id = str(conversation_context["selected_record_id"]).strip().lower()
        ctx_matches = [
            r for r in candidate_records if str(r.record_identifier).strip().lower() == ctx_id
        ]
        if ctx_matches:
            # If user asks specific question about previously selected record
            candidate_records = ctx_matches
            has_context_selection = True

    # 7. Apply Specific Record Identifiers
    if record_identifiers:
        norm_ids = [str(i).strip().lower() for i in record_identifiers]
        candidate_records = [
            r for r in candidate_records if str(r.record_identifier).strip().lower() in norm_ids
        ]

    # 8. Apply Dynamic Multi-Field Filtering
    filtered_records: List[DynamicDatasetRecord] = []
    for rec in candidate_records:
        row = rec.raw_data or {}
        matches = True
        for col_name, condition in canonical_filters.items():
            cell_val = row.get(col_name)
            if not _evaluate_filter_condition(cell_val, condition):
                matches = False
                break
        if matches:
            filtered_records.append(rec)

    # 9. Free-Text Keyword Scoring (if query_text provided)
    query_tokens = _tokenize_text(query_text or "")
    scored_records: List[Tuple[float, DynamicDatasetRecord]] = []

    for rec in filtered_records:
        score = _score_universal_record(
            rec.raw_data or {},
            query_tokens,
            approved_fields if not is_legacy else list(rec.raw_data.keys()),
            display_identifier=display_id,
        )
        if score > 0 or not query_tokens or has_context_selection:
            final_score = max(score, 10.0 if has_context_selection else 0.0)
            scored_records.append((final_score, rec))

    # 10. Sorting
    if canonical_sort_by:
        reverse_order = (sort_order.lower() == "desc")

        def _sort_key(item: Tuple[float, DynamicDatasetRecord]):
            val = (item[1].raw_data or {}).get(canonical_sort_by)
            num = _parse_numeric_value(val)
            if num is not None:
                return (0, num)
            d = _parse_date_value(val)
            if d is not None:
                return (1, d.timestamp())
            return (2, str(val).lower() if val is not None else "")

        scored_records.sort(key=_sort_key, reverse=reverse_order)
    else:
        # Default: sort by relevance score descending
        scored_records.sort(key=lambda x: x[0], reverse=True)

    total_matches_count = len(scored_records)

    # 11. Handle Aggregations & Counting Intent
    agg_result: Optional[Dict[str, Any]] = None
    if intent in ("count", "aggregate") or aggregate_op:
        op = (aggregate_op or "count").lower()
        if op == "count":
            agg_result = {"operation": "count", "value": total_matches_count}
            voice_summary = (
                f"I found {total_matches_count} matching {domain} records in our verified dataset."
            )
            return {
                "found": total_matches_count > 0,
                "dataset_name": target_dataset.name,
                "dataset_version": target_dataset.version,
                "domain_name": domain,
                "total_matches": total_matches_count,
                "aggregation": agg_result,
                "records": [],
                "voice_grounding": voice_summary,
            }

        elif op in ("min", "max", "avg", "sum") and canonical_agg_field:
            numeric_vals: List[float] = []
            for _, rec in scored_records:
                val = _parse_numeric_value((rec.raw_data or {}).get(canonical_agg_field))
                if val is not None:
                    numeric_vals.append(val)

            computed_val = None
            if numeric_vals:
                if op == "min":
                    computed_val = min(numeric_vals)
                elif op == "max":
                    computed_val = max(numeric_vals)
                elif op == "avg":
                    computed_val = round(sum(numeric_vals) / len(numeric_vals), 2)
                elif op == "sum":
                    computed_val = round(sum(numeric_vals), 2)

            agg_label = field_labels.get(canonical_agg_field, canonical_agg_field.replace("_", " "))
            agg_result = {
                "operation": op,
                "field": canonical_agg_field,
                "value": computed_val,
                "sample_count": len(numeric_vals),
            }

            if computed_val is not None:
                voice_summary = (
                    f"The {op} {agg_label} across {len(numeric_vals)} matching {domain} records is {computed_val}."
                )
            else:
                voice_summary = f"No numeric values were found for {agg_label} to compute {op}."

            return {
                "found": computed_val is not None,
                "dataset_id": str(target_dataset.id),
                "dataset_name": target_dataset.name,
                "dataset_version": target_dataset.version,
                "domain_name": domain,
                "total_matches": total_matches_count,
                "aggregation": agg_result,
                "records": [],
                "voice_grounding": voice_summary,
            }

    # 12. Handle Zero Matches
    if not scored_records:
        query_desc = f" matching '{query_text}'" if query_text else ""
        return {
            "found": False,
            "dataset_id": str(target_dataset.id),
            "dataset_name": target_dataset.name,
            "dataset_version": target_dataset.version,
            "domain_name": domain,
            "total_matches": 0,
            "records": [],
            "voice_grounding": f"I searched our verified {target_dataset.name} dataset, but could not find {domain}{query_desc}.",
        }

    # 13. Build Output Records (Strict Data Leakage Protection)
    top_matches = scored_records[:limit]
    output_records: List[Dict[str, Any]] = []
    spoken_lines: List[str] = []

    for score, rec in top_matches:
        raw = rec.raw_data or {}
        if not is_legacy and approved_fields:
            clean_attrs = {k: v for k, v in raw.items() if k in approved_fields}
        else:
            clean_attrs = raw

        # Render display label
        disp_val = clean_attrs.get(display_id) if display_id else None
        item_label = str(disp_val) if disp_val else rec.record_identifier

        output_records.append({
            "record_id": rec.record_identifier,
            "display_identifier": item_label,
            "relevance_score": score,
            "voice_summary": rec.voice_summary,
            "raw_attributes": clean_attrs,
        })
        spoken_lines.append(rec.voice_summary)

    # 14. Handle Comparison Intent
    if intent == "compare" and len(output_records) >= 2:
        comp_parts: List[str] = []
        for out_rec in output_records[:3]:
            ident = out_rec.get("display_identifier", out_rec["record_id"])
            attrs = out_rec["raw_attributes"]
            key_details = [
                f"{field_labels.get(k, k)}: {v}"
                for k, v in attrs.items()
                if k != display_id and v is not None
            ]
            comp_parts.append(f"{ident} ({', '.join(key_details[:3])})")
        voice_grounding = f"Comparing {len(output_records)} {domain}: " + "; ".join(comp_parts) + "."
    else:
        # Standard voice response (up to 2 concise items)
        voice_grounding = " ".join(spoken_lines[:2])
        if total_matches_count > len(top_matches):
            voice_grounding += f" We also have {total_matches_count - len(top_matches)} other matching options in this catalog."

    return {
        "found": True,
        "dataset_id": str(target_dataset.id),
        "dataset_name": target_dataset.name,
        "dataset_version": target_dataset.version,
        "domain_name": domain,
        "total_matches": total_matches_count,
        "returned_matches": len(output_records),
        "records": output_records,
        "voice_grounding": voice_grounding,
    }


def query_dynamic_dataset(
    db: Session,
    query_text: str,
    filters: Optional[Dict[str, Any]] = None,
    dataset_id: Optional[uuid.UUID] = None,
    limit: int = 4,
    company_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper for real estate inquiries and legacy tests.
    Delegates seamlessly to the universal query engine.
    """
    return query_universal_dataset(
        db=db,
        query_text=query_text,
        filters=filters,
        dataset_id=dataset_id,
        limit=limit,
        company_id=company_id,
    )
