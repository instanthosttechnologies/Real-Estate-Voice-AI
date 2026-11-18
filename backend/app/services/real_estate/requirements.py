import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class ExtractedCustomerRequirements(BaseModel):
    intent_type: str = Field(default="buy", description="'buy', 'rent', or 'invest'")
    preferred_city: Optional[str] = None
    preferred_location: Optional[str] = None
    configuration_type: Optional[str] = None  # '1BHK', '2BHK', '3BHK', etc.
    property_type: Optional[str] = None  # 'apartment', 'villa', 'commercial'
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    currency: Optional[str] = Field(None, description="ISO 4217 currency code e.g. USD, INR, EUR, AED, GBP")
    desired_amenities: List[str] = Field(default_factory=list)
    purchase_timeline: Optional[str] = None  # 'immediate', '1_month', '1_3_months', 'exploring'
    is_complete: bool = False
    missing_fields: List[str] = Field(default_factory=list)
    clarification_prompt: Optional[str] = None


def parse_numeric_budget(text: str) -> Optional[Decimal]:
    """
    Parses currency amounts supporting both international (M, k, thousand, million)
    and Indian numbering systems (Crore/Cr, Lakh/Lacs).
    Guards against matching words like 'months'.
    """
    text = text.replace(",", "").strip().lower()

    # Indian Crore match: e.g. 1.5 cr, 2 crore, 3 crores
    cr_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)\b", text)
    if cr_match:
        return Decimal(cr_match.group(1)) * Decimal(10_000_000)

    # Indian Lakh match: e.g. 75 lakh, 50 lakhs, 60 lac, 80 lacs
    lakh_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs)\b", text)
    if lakh_match:
        return Decimal(lakh_match.group(1)) * Decimal(100_000)

    # Million match: e.g. 1.5m, 1.5 million (excluding 'month')
    m_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:m|mn|mil|million)\b(?!\s*month)", text)
    if m_match:
        return Decimal(m_match.group(1)) * Decimal(1_000_000)

    # Thousand match: e.g. 750k, 500 thousand
    k_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:k|thousand)\b", text)
    if k_match:
        return Decimal(k_match.group(1)) * Decimal(1_000)

    # Raw numbers: e.g. $750000 or ₹750000 or 750000
    num_match = re.search(r"[₹$€£]?\s*(\d{4,10})\b", text)
    if num_match:
        return Decimal(num_match.group(1))

    return None


def detect_currency_from_text(text: str, city: Optional[str] = None) -> Optional[str]:
    """
    Detects ISO 4217 currency code from text tokens, symbols, and denomination units.
    Never assumes USD or silently converts currencies.
    """
    t = text.lower()
    # Explicit symbols and denominations
    if any(s in t for s in ["₹", "inr", "rupee", "rupees", "rs.", "rs "]) or re.search(r"\b(?:cr|crore|crores|lakh|lakhs|lac|lacs)\b", t):
        return "INR"
    if "$" in t or re.search(r"\b(?:usd|dollar|dollars|bucks)\b", t):
        return "USD"
    if "€" in t or re.search(r"\b(?:eur|euro|euros)\b", t):
        return "EUR"
    if "£" in t or re.search(r"\b(?:gbp|pound|pounds)\b", t):
        return "GBP"
    if re.search(r"\b(?:aed|dirham|dirhams)\b", t):
        return "AED"
    if re.search(r"\b(?:cad)\b", t):
        return "CAD"
    if re.search(r"\b(?:aud)\b", t):
        return "AUD"

    # Infer from well-known city geography if no explicit currency stated
    if city:
        city_lower = city.strip().lower()
        if city_lower in ["seattle", "austin", "miami", "denver", "chicago", "san francisco", "dallas", "boston", "phoenix", "new york"]:
            return "USD"
        if city_lower in ["mumbai", "bangalore", "bengaluru", "delhi", "hyderabad", "pune", "chennai", "kolkata", "noida", "gurgaon", "gurugram"]:
            return "INR"
        if city_lower in ["london"]:
            return "GBP"
        if city_lower in ["dubai"]:
            return "AED"

    return None


def extract_requirements_from_text(
    user_utterance: str,
    existing_requirements: Optional[Union[ExtractedCustomerRequirements, Dict[str, Any]]] = None
) -> ExtractedCustomerRequirements:
    """
    Extracts structured real estate criteria from conversational customer utterances.
    Supports incremental updates, merges existing context, and detects missing critical fields.
    """
    if existing_requirements:
        if isinstance(existing_requirements, dict):
            req = ExtractedCustomerRequirements(**existing_requirements)
        else:
            req = existing_requirements.model_copy(deep=True)
    else:
        req = ExtractedCustomerRequirements()
    text = user_utterance.lower()

    # 1. Intent: Buy vs Rent
    if any(w in text for w in ["rent", "lease", "tenant", "renting"]):
        req.intent_type = "rent"
    elif any(w in text for w in ["buy", "purchase", "invest", "own", "ownership"]):
        req.intent_type = "buy"

    # 2. Configuration / BHK
    bhk_match = re.search(r"\b(\d)\s*(?:bhk|bed(?:room)?s?)\b", text)
    if bhk_match:
        req.configuration_type = f"{bhk_match.group(1)}BHK"
    elif "studio" in text:
        req.configuration_type = "Studio"
    elif "penthouse" in text:
        req.configuration_type = "Penthouse"
    elif "villa" in text:
        req.configuration_type = "Villa"

    # 3. Property Type
    if "apartment" in text or "flat" in text or "condo" in text:
        req.property_type = "apartment"
    elif "villa" in text or "independent house" in text or "bungalow" in text:
        req.property_type = "villa"
    elif "commercial" in text or "office" in text or "retail" in text:
        req.property_type = "commercial"

    # 4. Timeline
    if any(w in text for w in ["immediately", "ready to move", "asap", "this week", "urgent", "right now"]):
        req.purchase_timeline = "immediate"
    elif re.search(r"\b(?:within\s*)?1\s*month\b", text):
        req.purchase_timeline = "1_month"
    elif any(w in text for w in ["3 months", "few months", "quarter", "1-3 months"]):
        req.purchase_timeline = "1_3_months"
    elif any(w in text for w in ["exploring", "just looking", "browsing", "next year", "someday"]):
        req.purchase_timeline = "exploring"

    # 5. Budget extraction
    # Specific numeric range e.g. "between 600k and 800k", "500k to 700k"
    range_match = re.search(
        r"(?:between|from)?\s*(\$?\s*\d+(?:\.\d+)?\s*(?:k|m|million|thousand)?)\s*(?:to|-|and)\s*(\$?\s*\d+(?:\.\d+)?\s*(?:k|m|million|thousand)?)\b",
        text
    )
    range_found = False
    if range_match:
        min_b = parse_numeric_budget(range_match.group(1))
        max_b = parse_numeric_budget(range_match.group(2))
        if min_b and max_b and min_b != max_b:
            req.budget_min = min(min_b, max_b)
            req.budget_max = max(min_b, max_b)
            range_found = True

    if not range_found:
        # Check single cap or direct budget update
        budget_val = parse_numeric_budget(text)
        if budget_val:
            if re.search(r"\b(?:above|min|minimum|at least)\b", text):
                req.budget_min = budget_val
            else:
                req.budget_max = budget_val

    # 6. Cities / Locations (Common real estate hubs - Global & Indian)
    city_found = False
    for city in [
        "seattle", "austin", "miami", "denver", "chicago", "san francisco", "dallas", "boston", "phoenix", "new york",
        "mumbai", "bangalore", "bengaluru", "delhi", "hyderabad", "pune", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
        "london", "dubai"
    ]:
        if re.search(rf"\b{city}\b", text):
            req.preferred_city = city.title()
            city_found = True
            break

    # 6b. Locality / Neighborhood detection e.g. "in OMR", "in Whitefield", "near Downtown"
    loc_match = re.search(
        r"\b(?:in|at|near|around)\s+([a-zA-Z0-9\s]+?)(?:\s+(?:under|below|above|between|for|with|bhk|bed|cr|crore|lakh|lac|\$|₹|budget|ready|instead|please)|$)",
        text
    )
    if loc_match:
        loc_candidate = loc_match.group(1).strip()
        # Clean trailing noise words like 'instead', 'please', 'now'
        loc_candidate = re.sub(r"\b(?:instead|please|now|first|also)\b", "", loc_candidate, flags=re.IGNORECASE).strip()
        stop_words = {"a", "an", "the", "my", "our", "apartment", "villa", "flat", "house", "budget", "area"}
        if loc_candidate.lower() not in stop_words and len(loc_candidate) >= 2:
            formatted_loc = loc_candidate.upper() if len(loc_candidate) <= 4 else loc_candidate.title()
            if not city_found:
                loc_lower = loc_candidate.lower()
                if loc_lower == "omr":
                    req.preferred_city = "Chennai"
                    req.preferred_location = "OMR"
                elif loc_lower in ["whitefield", "koramangala", "indiranagar", "electronic city", "hebbal"]:
                    req.preferred_city = "Bengaluru"
                    req.preferred_location = formatted_loc
                elif loc_lower in ["ballard", "capitol hill", "belltown", "fremont"]:
                    req.preferred_city = "Seattle"
                    req.preferred_location = formatted_loc
                elif loc_lower in ["bandra", "andheri", "juhu", "worli", "powai"]:
                    req.preferred_city = "Mumbai"
                    req.preferred_location = formatted_loc
                else:
                    req.preferred_location = formatted_loc
            else:
                if loc_candidate.lower() != (req.preferred_city or "").lower():
                    req.preferred_location = formatted_loc

    # 7. Currency detection (explicit symbols, Indian denominations, or inferred from location)
    detected_currency = detect_currency_from_text(text, city=req.preferred_city)
    if detected_currency:
        req.currency = detected_currency

    # 8. Amenities
    amenity_keywords = {
        "swimming pool": "Swimming Pool",
        "pool": "Swimming Pool",
        "gym": "Gym",
        "fitness": "Gym",
        "parking": "Covered Parking",
        "garage": "Covered Parking",
        "security": "24/7 Security",
        "ev charging": "EV Charging",
        "balcony": "Balcony",
        "clubhouse": "Clubhouse",
        "garden": "Garden",
        "play area": "Children Play Area"
    }
    for kw, canon in amenity_keywords.items():
        if re.search(rf"\b{re.escape(kw)}\b", text):
            if canon not in req.desired_amenities:
                req.desired_amenities.append(canon)

    # 9. Check completeness & identify missing critical fields
    missing: List[str] = []
    if not req.preferred_city and not req.preferred_location:
        missing.append("location")
    if not req.configuration_type:
        missing.append("configuration (e.g. 2BHK, 3BHK)")
    if not req.budget_max:
        missing.append("budget")
    elif not req.currency:
        missing.append("currency (e.g. USD, INR, EUR)")

    req.missing_fields = missing
    req.is_complete = len(missing) == 0

    if missing:
        req.clarification_prompt = (
            f"To help find the best options, could you please specify your preferred {', '.join(missing)}?"
        )
    else:
        req.clarification_prompt = None

    return req
