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
    currency: str = Field(default="INR", description="ISO 4217 currency code. Defaults to 'INR' for Indian real estate.")
    is_budget_scale_ambiguous: bool = False
    ambiguous_budget_value: Optional[int] = None
    desired_amenities: List[str] = Field(default_factory=list)
    purchase_timeline: Optional[str] = None  # 'immediate', '1_month', '1_3_months', 'exploring'
    is_complete: bool = False
    missing_fields: List[str] = Field(default_factory=list)
    clarification_prompt: Optional[str] = None


DEV_DIGIT_MAP = str.maketrans("०१२३४५६७८९", "0123456789")

HINDI_NUMBER_WORD_MAP = {
    # Fractions & Multipliers
    "आधा": "0.5",
    "डेढ़": "1.5",
    "dedh": "1.5",
    "ढाई": "2.5",
    "dhai": "2.5",
    "साढ़े तीन": "3.5",
    "साढ़े चार": "4.5",
    # 1 - 10
    "एक": "1",
    "दो": "2",
    "तीन": "3",
    "चार": "4",
    "पांच": "5",
    "पाँच": "5",
    "छह": "6",
    "छः": "6",
    "सात": "7",
    "आठ": "8",
    "नौ": "9",
    "दस": "10",
    # Tens
    "बीस": "20",
    "पच्चीस": "25",
    "तीस": "30",
    "पैंतीस": "35",
    "चालीस": "40",
    "पैंतालीस": "45",
    "पचास": "50",
    "साठ": "60",
    "सत्तर": "70",
    "पचहत्तर": "75",
    "अस्सी": "80",
    "नब्बे": "90",
    "सौ": "100",
}


def parse_numeric_budget(text: str) -> Optional[Decimal]:
    """
    Parses currency amounts supporting both international (M, k, thousand, million),
    Indian numbering systems (Crore/Cr, Lakh/Lacs/L), Hindi Devanagari numerals,
    and spoken Hindi word-numbers (e.g. पचास लाख, डेढ़ करोड़, 75L, 2Cr).
    Guards against matching words like 'months'.
    """
    # 1. Translate Devanagari digits to ASCII digits
    text = text.translate(DEV_DIGIT_MAP)
    text = text.replace(",", "").strip().lower()

    # 2. English word numbers
    word_number_map = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "twenty": "20", "twenty-five": "25", "thirty": "30", "thirty-five": "35",
        "forty": "40", "forty-five": "45", "fifty": "50", "fifty-five": "55",
        "sixty": "60", "sixty-five": "65", "seventy": "70", "seventy-five": "75",
        "eighty": "80", "eighty-five": "85", "ninety": "90", "hundred": "100",
    }
    for word, num in word_number_map.items():
        text = re.sub(rf"\b{word}\b", num, text)

    # 3. Hindi word numbers
    for word, num in HINDI_NUMBER_WORD_MAP.items():
        text = text.replace(word, num)

    # Indian Crore match: e.g. 1.5 cr, 2 crore, 3 crores, 2Cr, 1.5Cr, डेढ़ करोड़, दो करोड़
    cr_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cr|crore|crores|करोड़|करोड)(?=\s|[.,!?]|$)", text, re.IGNORECASE)
    if cr_match:
        return Decimal(cr_match.group(1)) * Decimal(10_000_000)

    # Indian Lakh match: e.g. 75 lakh, 50 lakhs, 60 lac, 80 lacs, 80 lakhs, 75L, 50L, पचास लाख, अस्सी लाख
    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|l|लाख)(?=\s|[.,!?]|$)", text, re.IGNORECASE)
    if lakh_match:
        return Decimal(lakh_match.group(1)) * Decimal(100_000)

    # Million match: e.g. 1.5m, 1.5 million (excluding 'month')
    m_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:m|mn|mil|million)\b(?!\s*month)", text, re.IGNORECASE)
    if m_match:
        return Decimal(m_match.group(1)) * Decimal(1_000_000)

    # Thousand match: e.g. 750k, 500 thousand, हज़ार
    k_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:k|thousand|हज़ार|हजार)\b", text, re.IGNORECASE)
    if k_match:
        return Decimal(k_match.group(1)) * Decimal(1_000)

    # Raw numbers: e.g. $750000 or ₹9000000 or 10000000
    num_match = re.search(r"[₹$€£]?\s*(\d{4,12})\b", text)
    if num_match:
        return Decimal(num_match.group(1))

    return None


def check_ambiguous_budget_scale(text: str) -> Optional[int]:
    """
    Detects if the user provided a bare numeric budget without scale or currency
    (e.g., 'My budget is 80', 'I have 75', 'around 80', 'बजट 80 है').
    Such values are genuinely ambiguous in real estate (could mean 80 lakhs or 80k).
    """
    t = text.translate(DEV_DIGIT_MAP).replace(",", "").strip().lower()
    # If explicit scale or currency symbol exists, it is not ambiguous
    if re.search(r"(?:cr|crore|crores|करोड़|करोड|lakh|lakhs|lac|lacs|लाख|\bl\b|k|thousand|million|mn|m\b|\$|₹|inr|rs|rupee|रुपये|रुपए|रुपया|dollar)", t, re.IGNORECASE):
        return None
    # Check for bare number in budget context: e.g. 'budget is 80', 'can spend 80', 'budget 80', 'बजट 80'
    m = re.search(r"(?:budget\s+(?:is\s+|of\s+)?|spend\s+|around\s+|have\s+|बजट\s+)?(\d{1,3})\b", t, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 10 <= val <= 999:
            return val
    return None


def format_natural_spoken_budget(amount: Union[Decimal, float, int], currency: str = "INR", language: str = "en-US") -> str:
    """Formats numeric budget into natural conversational speech for real estate in English or Hindi."""
    if not amount:
        return ""
    val = float(amount)
    curr = (currency or "INR").upper()
    is_hindi = str(language).lower().startswith("hi")

    if curr == "INR":
        if val >= 10_000_000:
            cr = val / 10_000_000
            cr_str = f"{cr:.2f}".rstrip("0").rstrip(".")
            return f"{cr_str} करोड़ रुपये" if is_hindi else f"{cr_str} crore"
        elif val >= 100_000:
            lakh = val / 100_000
            lakh_str = f"{lakh:.2f}".rstrip("0").rstrip(".")
            return f"{lakh_str} लाख रुपये" if is_hindi else f"{lakh_str} lakh rupees"
        else:
            return f"₹{val:,.0f}"
    elif curr == "USD":
        return f"${val:,.0f}"
    else:
        return f"{val:,.0f} {curr}"


def detect_currency_from_text(text: str, city: Optional[str] = None) -> str:
    """
    Detects ISO 4217 currency code from text tokens, symbols, and denomination units.
    Defaults to INR for Indian real estate conversations unless a foreign currency
    (USD, EUR, GBP, AED, CAD, AUD) is explicitly specified.
    """
    t = text.lower()
    # Explicit foreign symbols and terms
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

    # Infer from foreign city geography if explicitly stated
    if city:
        city_lower = city.strip().lower()
        if city_lower in ["seattle", "austin", "miami", "denver", "chicago", "san francisco", "dallas", "boston", "phoenix", "new york"]:
            return "USD"
        if city_lower in ["london"]:
            return "GBP"
        if city_lower in ["dubai"]:
            return "AED"

    # Default to INR for all Indian real estate conversations
    return "INR"


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

    # 2. Configuration / BHK (supports digits and word forms: "two BHK", "two bedroom", "2BHK flat", "three BHK", "3BHK", "तीन बीएचके", "2 बीएचके")
    word_to_digit = {
        "one": "1", "single": "1", "1": "1", "एक": "1",
        "two": "2", "double": "2", "2": "2", "दो": "2",
        "three": "3", "triple": "3", "3": "3", "तीन": "3",
        "four": "4", "4": "4", "चार": "4",
        "five": "5", "5": "5", "पांच": "5", "पाँच": "5",
    }
    bhk_match = re.search(
        r"(one|two|three|four|five|एक|दो|तीन|चार|पांच|पाँच|\d)\s*(?:[- ]?bhk(?:[- ]?flat)?|[- ]?बीएचके(?:[- ]?फ्लैट)?|[- ]?bed(?:room)?s?(?:[- ]?flat)?|[- ]?बेडरूम)(?=\s|[.,!?]|$)",
        text,
        re.IGNORECASE
    )
    if bhk_match:
        digit = word_to_digit.get(bhk_match.group(1), bhk_match.group(1))
        req.configuration_type = f"{digit}BHK"
    elif "studio" in text or "स्टूडियो" in text:
        req.configuration_type = "Studio"
    elif "penthouse" in text or "पेंटहाउस" in text:
        req.configuration_type = "Penthouse"
    elif "villa" in text or "विला" in text:
        req.configuration_type = "Villa"

    # 3. Property Type
    if any(w in text for w in ["apartment", "flat", "condo", "अपार्टमेंट", "फ्लैट"]):
        req.property_type = "apartment"
    elif any(w in text for w in ["villa", "independent house", "bungalow", "विला", "कोठी"]):
        req.property_type = "villa"
    elif any(w in text for w in ["commercial", "office", "retail", "कमर्शियल", "दुकान"]):
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
    range_match = re.search(
        r"(?:between|from)?\s*([₹$€£]?\s*\d+(?:\.\d+)?\s*(?:cr|crore|crores|lakh|lakhs|lac|lacs|l|k|m|million|thousand)?)\s*(?:to|-|and)\s*([₹$€£]?\s*\d+(?:\.\d+)?\s*(?:cr|crore|crores|lakh|lakhs|lac|lacs|l|k|m|million|thousand)?)\b",
        text,
        re.IGNORECASE
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
            req.is_budget_scale_ambiguous = False
            req.ambiguous_budget_value = None
        else:
            # Check if customer gave a bare number without currency or scale (e.g. 'My budget is 80')
            ambig = check_ambiguous_budget_scale(text)
            if ambig is not None:
                req.is_budget_scale_ambiguous = True
                req.ambiguous_budget_value = ambig
                req.clarification_prompt = f"Just to confirm, did you mean {ambig} lakhs?"

    # 6. Cities / Locations (Common real estate hubs - Global & Indian, English & Devanagari Hindi)
    city_found = False
    hindi_city_map = {
        "चेन्नई": "Chennai", "चेन्नै": "Chennai",
        "मुंबई": "Mumbai", "बंबई": "Mumbai",
        "बैंगलोर": "Bengaluru", "बेंगलुरु": "Bengaluru", "बंगलौर": "Bengaluru",
        "दिल्ली": "Delhi", "नई दिल्ली": "Delhi",
        "हैदराबाद": "Hyderabad",
        "पुणे": "Pune",
        "कोलकाता": "Kolkata", "कलकत्ता": "Kolkata",
        "नोएडा": "Noida",
        "गुड़गांव": "Gurugram", "गुरुग्राम": "Gurugram",
    }
    for h_city, canon in hindi_city_map.items():
        if h_city in text:
            req.preferred_city = canon
            city_found = True
            break

    if not city_found:
        for city in [
            "seattle", "austin", "miami", "denver", "chicago", "san francisco", "dallas", "boston", "phoenix", "new york",
            "mumbai", "bangalore", "bengaluru", "delhi", "hyderabad", "pune", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
            "london", "dubai"
        ]:
            if re.search(rf"\b{city}\b", text):
                req.preferred_city = city.title()
                city_found = True
                break

    # 6b. Hindi Locality / Neighborhood detection
    hindi_loc_map = {
        "ओएमआर": "OMR",
        "व्हाइटफील्ड": "Whitefield",
        "कोरमंगला": "Koramangala",
        "इलेक्ट्रॉनिक सिटी": "Electronic City",
        "बांद्रा": "Bandra",
        "अंधेरी": "Andheri",
        "अन्ना नगर": "Anna Nagar",
        "अडयार": "Adyar",
        "वेलचेरी": "Velachery",
        "थोरईपक्कम": "Thoraipakkam",
        "पेरुम्बक्कम": "Perumbakkam",
    }
    for h_loc, canon_loc in hindi_loc_map.items():
        if h_loc in text:
            req.preferred_location = canon_loc
            if not req.preferred_city:
                if canon_loc in ["OMR", "Anna Nagar", "Adyar", "Velachery", "Thoraipakkam", "Perumbakkam"]:
                    req.preferred_city = "Chennai"
                elif canon_loc in ["Whitefield", "Koramangala", "Electronic City"]:
                    req.preferred_city = "Bengaluru"
                elif canon_loc in ["Bandra", "Andheri"]:
                    req.preferred_city = "Mumbai"
            break

    # 6c. Locality / Neighborhood detection e.g. "in OMR", "in Whitefield", "near Downtown"
    if not req.preferred_location:
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

    # 8. Amenities (English & Hindi)
    amenity_keywords = {
        "swimming pool": "Swimming Pool",
        "pool": "Swimming Pool",
        "स्विमिंग पूल": "Swimming Pool",
        "पूल": "Swimming Pool",
        "gym": "Gym",
        "fitness": "Gym",
        "जिम": "Gym",
        "जिमनेजियम": "Gym",
        "parking": "Covered Parking",
        "garage": "Covered Parking",
        "पार्किंग": "Covered Parking",
        "security": "24/7 Security",
        "सुरक्षा": "24/7 Security",
        "सिक्योरिटी": "24/7 Security",
        "ev charging": "EV Charging",
        "balcony": "Balcony",
        "बालकनी": "Balcony",
        "clubhouse": "Clubhouse",
        "क्लब हाउस": "Clubhouse",
        "क्लबहाउस": "Clubhouse",
        "garden": "Garden",
        "बगीचा": "Garden",
        "गार्डन": "Garden",
        "play area": "Children Play Area",
        "children play area": "Children Play Area",
        "बच्चों का खेलने का क्षेत्र": "Children Play Area",
        "प्ले एरिया": "Children Play Area",
        "बच्चों का पार्क": "Children Play Area",
        "power backup": "Power Backup",
        "पावर बैकअप": "Power Backup",
        "बिजली बैकअप": "Power Backup",
    }
    for kw, canon in amenity_keywords.items():
        if re.search(rf"\b{re.escape(kw)}\b", text):
            if canon not in req.desired_amenities:
                req.desired_amenities.append(canon)

    # 9. Check completeness & identify missing critical fields (Never require currency clarification for Indian real estate)
    missing: List[str] = []
    if not req.preferred_city and not req.preferred_location:
        missing.append("location")
    if not req.configuration_type:
        missing.append("configuration (e.g. 2BHK, 3BHK)")
    if not req.budget_max and not req.is_budget_scale_ambiguous:
        missing.append("budget")

    req.missing_fields = missing
    req.is_complete = len(missing) == 0

    if req.is_budget_scale_ambiguous and req.clarification_prompt:
        pass
    elif missing:
        req.clarification_prompt = (
            f"To help find the best options, could you please specify your preferred {', '.join(missing)}?"
        )
    else:
        req.clarification_prompt = None

    return req
