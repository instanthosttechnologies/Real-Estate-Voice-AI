import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.services.dataset.manager import get_active_dataset

logger = logging.getLogger("dataset_retrieval")

# Location synonyms mapping for Indian real estate markets
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

# Configuration aliases
CONFIG_ALIASES: Dict[str, str] = {
    "1bhk": "1 BHK",
    "2bhk": "2 BHK",
    "3bhk": "3 BHK",
    "4bhk": "4 BHK",
    "5bhk": "5 BHK",
    "penthouse": "Penthouse",
    "villa": "Villa",
    "plot": "Plot",
    "office": "Office",
}


STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "after",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "tell", "me", "show", "what", "which", "who", "whom",
    "where", "when", "why", "how", "can", "could", "would", "should", "looking",
    "want", "need", "give", "some", "any", "please", "help", "project", "projects",
    "property", "properties", "available", "there", "their"
}


def _tokenize_text(text: str) -> List[str]:
    """Extracts non-stopword content tokens from search input."""
    raw = [w.lower() for w in re.findall(r"\b[A-Za-z0-9\-\_]{2,}\b", text)]
    filtered = [w for w in raw if w not in STOP_WORDS]
    return filtered if filtered else raw


def _normalize_location_terms(tokens: List[str]) -> List[str]:
    """Expands city/location synonyms."""
    expanded = list(tokens)
    for canonical, synonyms in LOCATION_SYNONYMS.items():
        if any(syn in tokens for syn in synonyms):
            if canonical not in expanded:
                expanded.append(canonical)
            for syn in synonyms:
                if syn not in expanded:
                    expanded.append(syn)
    return expanded


def score_record_match(
    record: DynamicDatasetRecord,
    query_tokens: List[str],
    meta_summary: Dict[str, Any],
    original_token_count: Optional[int] = None,
) -> float:
    """
    Computes relevancy score between query terms and a record's normalized fields.
    Gives higher weight to Project Name, Developer Name, Location, and Configuration.
    """
    norm = record.normalized_search or {}
    all_tokens = norm.get("_all_tokens", "")

    if not query_tokens:
        return 0.5  # Neutral default for empty/broad queries

    score = 0.0
    token_matches = 0

    dev_col = (meta_summary.get("developers_column") or "").lower()
    proj_col = (meta_summary.get("projects_column") or "").lower()
    loc_col = (meta_summary.get("location_column") or "").lower()
    cfg_col = (meta_summary.get("config_column") or "").lower()

    dev_val = norm.get(dev_col, "")
    proj_val = norm.get(proj_col, "")
    loc_val = norm.get(loc_col, "")
    cfg_val = norm.get(cfg_col, "")

    for t in query_tokens:
        t_clean = t.lower()
        matched = False

        # Strongest weight: Project Name match
        if proj_val and t_clean in proj_val:
            score += 15.0
            matched = True

        # Strong weight: Developer/Company match
        if dev_val and t_clean in dev_val:
            score += 12.0
            matched = True

        # Medium weight: City / Location match
        if loc_val and t_clean in loc_val:
            score += 8.0
            matched = True

        # Medium weight: Configuration match
        if cfg_val and t_clean in cfg_val:
            score += 8.0
            matched = True

        # General token match across all columns (word boundary match)
        if bool(re.search(r"\b" + re.escape(t_clean) + r"\b", all_tokens)):
            score += 4.0
            matched = True

        if matched:
            token_matches += 1

    if token_matches == 0:
        return 0.0

    # Ratio of matched query tokens relative to original user terms
    base_count = original_token_count or len(query_tokens)
    coverage = min(1.0, token_matches / max(base_count, 1))
    if base_count >= 3 and coverage < 0.35:
        return 0.0

    final_score = score * (1.0 + coverage)
    return round(final_score, 2)


def query_dynamic_dataset(
    db: Session,
    query_text: str,
    filters: Optional[Dict[str, Any]] = None,
    dataset_id: Optional[uuid.UUID] = None,
    limit: int = 4,
) -> Dict[str, Any]:
    """
    Executes safe, grounded retrieval across the active dynamic dataset.
    Never executes unrestricted SQL. Strictly confines searches to the active dataset ID.
    Handles spelling variations, location synonyms, multi-field ranking, and formats
    concise summaries for Amazon Nova 2.5 Sonic voice grounding.
    """
    # 1. Resolve target dataset
    target_dataset: Optional[DynamicDataset] = None
    if dataset_id:
        target_dataset = db.execute(
            select(DynamicDataset).where(DynamicDataset.id == dataset_id)
        ).scalar_one_or_none()
    else:
        target_dataset = get_active_dataset(db)

    if not target_dataset:
        return {
            "found": False,
            "message": "No active real estate dataset is currently registered. Please upload or activate a dataset.",
            "total_matches": 0,
            "records": [],
            "voice_grounding": "I am currently updating our real estate property dataset. Please check back shortly.",
        }

    meta = target_dataset.metadata_registry or {}
    meta_summary = meta.get("summary", {})
    primary_sheet = target_dataset.primary_sheet

    # 2. Extract and expand tokens
    raw_tokens = _tokenize_text(query_text)
    expanded_tokens = _normalize_location_terms(raw_tokens)

    # 3. Retrieve records from primary sheet
    # Safe parameterized query over isolated dataset
    records_query = select(DynamicDatasetRecord).where(
        DynamicDatasetRecord.dataset_id == target_dataset.id,
        DynamicDatasetRecord.sheet_name == primary_sheet,
    )
    all_records = db.execute(records_query).scalars().all()

    if not all_records:
        return {
            "found": False,
            "message": f"Dataset '{target_dataset.name}' (v{target_dataset.version}) contains no records.",
            "total_matches": 0,
            "records": [],
            "voice_grounding": "No property listings are currently available in the active dataset.",
        }

    # 4. Score records
    scored_records: List[Tuple[float, DynamicDatasetRecord]] = []
    for rec in all_records:
        score = score_record_match(rec, expanded_tokens, meta_summary, original_token_count=len(raw_tokens))
        if score > 0:
            scored_records.append((score, rec))

    # Sort descending by relevancy score
    scored_records.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored_records[:limit]

    if not top_matches:
        # Graceful no-match handling (Anti-hallucination)
        return {
            "found": False,
            "dataset_name": target_dataset.name,
            "dataset_version": target_dataset.version,
            "query": query_text,
            "total_matches": 0,
            "records": [],
            "voice_grounding": (
                f"I searched our verified {target_dataset.name} dataset, but could not find properties "
                f"matching '{query_text}'. Would you like me to check a different location, developer, or layout?"
            ),
        }

    # 5. Build grounded structured results and voice response
    matched_records = []
    voice_snippets = []

    for score, rec in top_matches:
        raw = rec.raw_data
        matched_records.append({
            "record_id": rec.record_identifier,
            "relevance_score": score,
            "voice_summary": rec.voice_summary,
            "raw_attributes": raw,
        })
        # Add concise summary for voice
        voice_snippets.append(rec.voice_summary)

    # Format synthesized voice summary for Nova Sonic (2-3 sentences max)
    voice_grounding = " ".join(voice_snippets[:2])
    if len(top_matches) > 2:
        voice_grounding += f" We also have {len(top_matches) - 2} other matching option(s) in this portfolio."

    return {
        "found": True,
        "dataset_name": target_dataset.name,
        "dataset_version": target_dataset.version,
        "query": query_text,
        "total_matches": len(scored_records),
        "returned_matches": len(matched_records),
        "records": matched_records,
        "voice_grounding": voice_grounding,
    }
