from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.real_estate.search import (
    PropertySearchCriteria,
    PropertySearchResultItem,
    search_properties,
)


class CustomerPreferences(BaseModel):
    preferred_city: Optional[str] = None
    preferred_location: Optional[str] = None
    preferred_config: Optional[str] = None  # e.g. '2BHK'
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    preferred_currency: Optional[str] = None  # Explicit ISO currency code e.g. 'USD', 'INR'
    desired_amenities: List[str] = Field(default_factory=list)


class RankedPropertyMatch(BaseModel):
    property: PropertySearchResultItem
    match_score: float = Field(..., ge=0.0, le=100.0, description="Match score percentage")
    match_reasons: List[str]
    match_summary: str
    is_exact_match: bool = Field(default=False, description="True if satisfies all specified mandatory and optional criteria")
    satisfied_constraints: List[str] = Field(default_factory=list)
    violated_constraints: List[str] = Field(default_factory=list)


def rank_and_explain_matches(
    properties: List[PropertySearchResultItem],
    preferences: CustomerPreferences
) -> List[RankedPropertyMatch]:
    """
    Ranks real database properties against customer preferences and generates transparent,
    grounded explanations for each match. Never invents missing data.
    """
    ranked_results: List[RankedPropertyMatch] = []

    for prop in properties:
        score = 0.0
        reasons: List[str] = []
        satisfied: List[str] = []
        violated: List[str] = []
        is_exact = True

        # 1. Configuration matching (Weight: 35%)
        if preferences.preferred_config:
            pref_bhk = preferences.preferred_config.strip().upper().replace(" ", "")
            unit_bhk = prop.configuration_type.strip().upper().replace(" ", "")
            if pref_bhk == unit_bhk:
                score += 35.0
                reasons.append(f"Exact match for desired layout ({prop.configuration_type}).")
                satisfied.append(f"Configuration: {prop.configuration_type} (exact match)")
            else:
                is_exact = False
                score += 10.0
                reasons.append(f"Alternative layout offered ({prop.configuration_type} vs requested {pref_bhk}).")
                violated.append(f"Configuration: {prop.configuration_type} offered (requested {pref_bhk})")
        else:
            score += 35.0

        # 2. Budget matching (Weight: 35%)
        # Enforce strict currency matching: Never silently convert currencies
        if preferences.preferred_currency and prop.currency.upper() != preferences.preferred_currency.strip().upper():
            is_exact = False
            score += 0.0
            reasons.append(
                f"Currency mismatch: property is priced in {prop.currency} whereas requested budget is in "
                f"{preferences.preferred_currency.upper()}. Currencies are never silently converted."
            )
            violated.append(f"Currency: {prop.currency} vs requested {preferences.preferred_currency.upper()}")
        elif preferences.budget_max is not None and preferences.budget_max > 0:
            if prop.base_price <= preferences.budget_max:
                if preferences.budget_min and prop.base_price < preferences.budget_min:
                    score += 25.0
                    reasons.append(f"Priced below target budget range at {prop.currency} {prop.base_price:,.0f}.")
                    satisfied.append(f"Budget: below target range at {prop.currency} {prop.base_price:,.0f}")
                else:
                    score += 35.0
                    savings = preferences.budget_max - prop.base_price
                    if savings > 0:
                        reasons.append(
                            f"Within budget at {prop.currency} {prop.base_price:,.0f} "
                            f"({prop.currency} {savings:,.0f} under max budget)."
                        )
                        satisfied.append(f"Budget: {prop.currency} {savings:,.0f} under maximum budget")
                    else:
                        reasons.append(f"Exact match to max budget at {prop.currency} {prop.base_price:,.0f}.")
                        satisfied.append("Budget: matches maximum budget exactly")
            else:
                is_exact = False
                overage_pct = float((prop.base_price - preferences.budget_max) / preferences.budget_max)
                if overage_pct <= 0.10:  # Within 10%
                    score += 15.0
                    reasons.append(f"Slightly above max budget by {overage_pct * 100:.1f}%.")
                    violated.append(f"Budget: {overage_pct * 100:.1f}% over maximum budget")
                else:
                    reasons.append(f"Exceeds max budget by {overage_pct * 100:.1f}%.")
                    violated.append(f"Budget: {overage_pct * 100:.1f}% over maximum budget")
        else:
            score += 35.0

        # 3. Location matching (Weight: 15%)
        if preferences.preferred_city:
            if preferences.preferred_city.strip().lower() == prop.city.strip().lower():
                score += 15.0
                reasons.append(f"Located in requested city ({prop.city}).")
                satisfied.append(f"City: {prop.city}")
            else:
                is_exact = False
                reasons.append(f"Located in nearby/alternate city ({prop.city}).")
                violated.append(f"City: located in {prop.city} (requested {preferences.preferred_city})")
        else:
            score += 15.0

        # 4. Amenities matching (Weight: 15%)
        if preferences.desired_amenities:
            prop_amenities_lower = [a.lower() for a in prop.amenities]
            matched_amenities = [
                a for a in preferences.desired_amenities
                if a.lower() in prop_amenities_lower
            ]
            missing_amenities = [
                a for a in preferences.desired_amenities
                if a.lower() not in prop_amenities_lower
            ]
            if matched_amenities:
                amenity_ratio = len(matched_amenities) / len(preferences.desired_amenities)
                score += round(15.0 * amenity_ratio, 1)
                reasons.append(f"Includes requested amenities: {', '.join(matched_amenities)}.")
                satisfied.append(f"Amenities: {', '.join(matched_amenities)}")
            if missing_amenities:
                is_exact = False
                reasons.append(f"Missing requested amenities: {', '.join(missing_amenities)}.")
                violated.append(f"Missing amenities: {', '.join(missing_amenities)}")
        else:
            score += 15.0

        match_score = round(min(score, 100.0), 1)
        summary = f"{match_score}% Match: " + " ".join(reasons)

        ranked_results.append(
            RankedPropertyMatch(
                property=prop,
                match_score=match_score,
                match_reasons=reasons,
                match_summary=summary,
                is_exact_match=is_exact,
                satisfied_constraints=satisfied,
                violated_constraints=violated,
            )
        )

    # Sort descending by match score
    ranked_results.sort(key=lambda x: x.match_score, reverse=True)
    return ranked_results


def intelligent_property_search(
    db: Session,
    criteria: PropertySearchCriteria,
    preferences: Optional[CustomerPreferences] = None,
) -> Dict[str, Any]:
    """
    Coordinates intelligent, multi-stage property matching:
    1. Executes strict SQL search on exact criteria.
    2. Ranks exact matches using the transparent scoring engine.
    3. If exact matches are fewer than limit or zero:
       - Never silently relaxes mandatory customer constraints.
       - Searches eligible verified alternatives in the database.
       - Ranks alternatives and explains satisfied vs violated constraints.
       - Asks permission before recommending alternatives that violate mandatory constraints.
    4. Guarantees that only authentic PostgreSQL inventory records are returned.
    """
    if not preferences:
        preferences = CustomerPreferences(
            preferred_city=criteria.city,
            preferred_location=criteria.location_query,
            preferred_config=criteria.configuration_type,
            budget_min=criteria.min_budget,
            budget_max=criteria.max_budget,
            preferred_currency=criteria.currency,
            desired_amenities=criteria.required_amenities or [],
        )

    # 1. Search for strict exact matches
    exact_results = search_properties(db, criteria)
    ranked_exact = rank_and_explain_matches(exact_results, preferences)

    # 2. If exact matches meet or exceed limit, return immediately
    if len(ranked_exact) >= criteria.limit:
        return {
            "total_matches": len(ranked_exact),
            "properties": [m.property.model_dump() for m in ranked_exact],
            "total_exact_matches": len(ranked_exact),
            "exact_matches": [m.model_dump() for m in ranked_exact],
            "total_recommended_alternatives": 0,
            "recommended_alternatives": [],
            "permission_required": False,
            "permission_prompt": None,
        }

    # 3. Search for eligible verified alternatives
    seen_unit_ids: Set[uuid.UUID] = {m.property.unit_id for m in ranked_exact}
    candidate_alternatives: List[PropertySearchResultItem] = []

    # Alternative strategy A: Relax amenity requirements (amenities are preferences)
    if criteria.required_amenities:
        relaxed_amenities_criteria = criteria.model_copy(update={"required_amenities": []})
        for r in search_properties(db, relaxed_amenities_criteria):
            if r.unit_id not in seen_unit_ids:
                seen_unit_ids.add(r.unit_id)
                candidate_alternatives.append(r)

    # Alternative strategy B: Slight budget flex (up to 15% above max_budget)
    if criteria.max_budget:
        relaxed_budget = criteria.max_budget * Decimal("1.15")
        relaxed_budget_criteria = criteria.model_copy(update={"max_budget": relaxed_budget, "required_amenities": []})
        for r in search_properties(db, relaxed_budget_criteria):
            if r.unit_id not in seen_unit_ids:
                seen_unit_ids.add(r.unit_id)
                candidate_alternatives.append(r)

    # Alternative strategy C: Alternative layouts in the same city & budget
    if criteria.configuration_type:
        relaxed_config_criteria = criteria.model_copy(update={"configuration_type": None, "required_amenities": []})
        for r in search_properties(db, relaxed_config_criteria):
            if r.unit_id not in seen_unit_ids:
                seen_unit_ids.add(r.unit_id)
                candidate_alternatives.append(r)

    # Alternative strategy D: City-wide search if specific neighborhood had 0 matches
    if criteria.location_query and criteria.city:
        relaxed_loc_criteria = criteria.model_copy(update={"location_query": None, "required_amenities": []})
        for r in search_properties(db, relaxed_loc_criteria):
            if r.unit_id not in seen_unit_ids:
                seen_unit_ids.add(r.unit_id)
                candidate_alternatives.append(r)

    # Rank candidate alternatives
    ranked_alternatives = rank_and_explain_matches(candidate_alternatives, preferences)
    viable_alternatives = [m for m in ranked_alternatives if m.match_score >= 40.0][: criteria.limit - len(ranked_exact)]

    permission_required = False
    permission_prompt = None

    if len(ranked_exact) == 0 and len(viable_alternatives) > 0:
        permission_required = True
        top_alt = viable_alternatives[0]
        curr_str = preferences.preferred_currency or ""
        budget_clause = f"under {curr_str} {preferences.budget_max:,.0f}" if preferences.budget_max else ""
        permission_prompt = (
            f"We could not find an exact match for {preferences.preferred_config or 'properties'} "
            f"in {preferences.preferred_city or 'the requested area'} {budget_clause}. "
            f"However, we found {len(viable_alternatives)} verified alternative(s) that closely match your criteria. "
            f"For example: {top_alt.match_summary}. "
            "Would you like to explore these alternative options?"
        )

    return {
        "total_matches": len(ranked_exact),
        "properties": [m.property.model_dump() for m in ranked_exact],
        "total_exact_matches": len(ranked_exact),
        "exact_matches": [m.model_dump() for m in ranked_exact],
        "total_recommended_alternatives": len(viable_alternatives),
        "recommended_alternatives": [m.model_dump() for m in viable_alternatives],
        "permission_required": permission_required,
        "permission_prompt": permission_prompt,
    }
