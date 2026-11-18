import re
from typing import Any, Dict, List, Optional, Tuple
from app.schemas.ingestion import ColumnMappingItem, MappingStatus

# Canonical field target synonyms map
CANONICAL_SYNONYMS: Dict[str, List[str]] = {
    "company_name": ["company", "developer", "builder", "promoter", "firm", "company_name"],
    "project_name": ["project", "project_name", "society", "community", "development", "estate_name"],
    "city": ["city", "town", "metro", "municipality"],
    "state": ["state", "province", "region"],
    "postal_code": ["postal_code", "zip", "zipcode", "postal", "pincode", "pin"],
    "address_line_1": ["address", "street", "street_address", "location_address", "address_line_1"],
    "property_name": ["tower", "block", "wing", "building", "phase", "property_name"],
    "unit_number": ["unit", "unit_number", "flat", "flat_no", "flat_number", "door_no", "apartment_no", "villa_no", "unit_no"],
    "configuration_type": ["configuration", "config", "bhk", "bedrooms", "beds", "layout", "type", "unit_type"],
    "carpet_area_sqft": ["area", "carpet_area", "carpet_sqft", "sqft", "area_sqft", "size", "sft"],
    "super_built_up_area_sqft": ["super_area", "sba", "super_built_up", "super_sqft", "built_up_area"],
    "base_price": ["price", "base_price", "cost", "rate", "asking_price", "value", "amount", "listing_price"],
    "availability_status": ["status", "availability", "availability_status", "unit_status", "vacant"],
    "amenities": ["amenities", "facilities", "features"],
}


def _clean_header(header: str) -> str:
    return re.sub(r"[_\s\-\./\(\)]+", "", header.strip().lower())


def match_column(header: str, sample_values: List[Any]) -> Tuple[Optional[str], float]:
    """
    Computes best matching canonical field and confidence score for a source header.
    """
    cleaned = _clean_header(header)
    best_field = None
    best_score = 0.0

    for canonical_field, synonyms in CANONICAL_SYNONYMS.items():
        # Exact match to canonical name
        if cleaned == _clean_header(canonical_field):
            return (canonical_field, 1.0)
        
        # Match against known synonyms
        for syn in synonyms:
            syn_clean = _clean_header(syn)
            if cleaned == syn_clean:
                score = 0.95
            elif syn_clean in cleaned or cleaned in syn_clean:
                # Substring overlap
                ratio = len(syn_clean) / max(len(cleaned), len(syn_clean))
                score = round(0.75 + (0.20 * ratio), 2)
            else:
                score = 0.0

            if score > best_score:
                best_score = score
                best_field = canonical_field

    # Contextual inference from sample values if header was ambiguous
    if best_score < 0.85 and sample_values:
        samples_str = " ".join([str(v) for v in sample_values if v is not None]).upper()
        if any(b in samples_str for b in ["1BHK", "2BHK", "3BHK", "STUDIO", "PENTHOUSE"]):
            best_field = "configuration_type"
            best_score = max(best_score, 0.90)

    return (best_field if best_score >= 0.50 else None, best_score)


def propose_mappings(
    headers: List[str],
    preview_rows: List[Dict[str, Any]]
) -> List[ColumnMappingItem]:
    """
    Analyzes all headers and preview rows to generate mapping proposals with confidence scores.
    """
    items: List[ColumnMappingItem] = []
    
    for h in headers:
        sample_vals = [row.get(h) for row in preview_rows[:5] if row.get(h) is not None]
        target, score = match_column(h, sample_vals)
        status = MappingStatus.AUTO_CONFIRMED if score >= 0.85 else MappingStatus.REQUIRES_CONFIRMATION
        
        items.append(
            ColumnMappingItem(
                source_column=h,
                target_field=target,
                confidence_score=score,
                status=status,
                sample_values=sample_vals[:3],
            )
        )
    return items
