"""
Automated regression test suite validating Currency & Indian Budget Handling
for AWS Nova Sonic Real Estate AI.

Verifies:
1. Default currency is INR (Indian Rupees).
2. Indian expressions:
   - 50 lakhs = ₹50,00,000
   - 75L = ₹75,00,000
   - 1 crore = ₹1,00,00,000
   - 1.5 Cr = ₹1,50,00,000
   - 2 crores = ₹2,00,00,000
3. Zero currency clarification questions when customer mentions lakhs, crores, L, Cr, INR, rupees, or ₹.
4. Ambiguous scale detection when a plain numeric budget (e.g. 80) is provided.
5. Foreign currency preservation ($200,000 -> USD).
6. Natural spoken budget formatting ("75 lakh rupees", "1.5 crore").
7. Preamble instructions prohibiting unnecessary currency questions.
"""

from decimal import Decimal
import pytest

from app.services.real_estate.requirements import (
    ExtractedCustomerRequirements,
    check_ambiguous_budget_scale,
    detect_currency_from_text,
    extract_requirements_from_text,
    format_natural_spoken_budget,
    parse_numeric_budget,
)
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.mock_driver import MockVoiceDriver


# --- Test Case 1: "I want a 3 BHK in Chennai for 80 lakhs." ---

def test_case_1_chennai_3bhk_80_lakhs():
    text = "I want a 3 BHK in Chennai for 80 lakhs."
    req = extract_requirements_from_text(text)
    assert req.preferred_city == "Chennai"
    assert req.configuration_type == "3BHK"
    assert req.budget_max == Decimal("8000000")
    assert req.currency == "INR"
    assert "currency" not in str(req.missing_fields).lower()
    assert req.is_complete is True


# --- Test Case 2: "Show properties below 1.5 crore." ---

def test_case_2_below_1_point_5_crore():
    text = "Show properties below 1.5 crore."
    req = extract_requirements_from_text(text)
    assert req.budget_max == Decimal("15000000")
    assert req.currency == "INR"
    assert "currency" not in str(req.missing_fields).lower()


# --- Test Case 3: "My budget is 2Cr." ---

def test_case_3_budget_2cr():
    text = "My budget is 2Cr."
    req = extract_requirements_from_text(text)
    assert req.budget_max == Decimal("20000000")
    assert req.currency == "INR"
    assert "currency" not in str(req.missing_fields).lower()


# --- Test Case 3b: "75L" ---

def test_case_3b_budget_75l():
    text = "I am looking for a flat for 75L."
    req = extract_requirements_from_text(text)
    assert req.budget_max == Decimal("7500000")
    assert req.currency == "INR"
    assert "currency" not in str(req.missing_fields).lower()


# --- Test Case 3c: "50 lakhs" & "1 crore" ---

def test_case_3c_standard_indian_denominations():
    assert parse_numeric_budget("50 lakhs") == Decimal("5000000")
    assert parse_numeric_budget("75L") == Decimal("7500000")
    assert parse_numeric_budget("1 crore") == Decimal("10000000")
    assert parse_numeric_budget("1.5 Cr") == Decimal("15000000")
    assert parse_numeric_budget("2 crores") == Decimal("20000000")
    assert parse_numeric_budget("2Cr") == Decimal("20000000")


# --- Test Case 4: "I can spend ₹90,00,000." ---

def test_case_4_rupee_symbol_indian_comma_format():
    text = "I can spend ₹90,00,000."
    req = extract_requirements_from_text(text)
    assert req.budget_max == Decimal("9000000")
    assert req.currency == "INR"
    assert "currency" not in str(req.missing_fields).lower()


# --- Test Case 5: "My budget is 10000000 INR." ---

def test_case_5_explicit_inr_text():
    text = "My budget is 10000000 INR."
    req = extract_requirements_from_text(text)
    assert req.budget_max == Decimal("10000000")
    assert req.currency == "INR"
    assert "currency" not in str(req.missing_fields).lower()


# --- Test Case 6: "My budget is $200,000." ---

def test_case_6_explicit_foreign_currency_usd():
    text = "My budget is $200,000."
    req = extract_requirements_from_text(text)
    assert req.budget_max == Decimal("200000")
    assert req.currency == "USD"
    # Preserves USD without silently converting
    assert req.currency != "INR"


# --- Test Case 7: "My budget is 80." (Ambiguous scale check) ---

def test_case_7_ambiguous_plain_numeric_budget():
    text = "My budget is 80."
    ambig = check_ambiguous_budget_scale(text)
    assert ambig == 80

    req = extract_requirements_from_text(text)
    assert req.is_budget_scale_ambiguous is True
    assert req.ambiguous_budget_value == 80
    assert "80 lakhs" in req.clarification_prompt
    # Does not ask 'which currency?', but clarifies the scale (e.g. 'Did you mean 80 lakhs?')
    assert "currency" not in req.clarification_prompt.lower()


# --- Test Natural Spoken Budget Formatting ---

def test_natural_spoken_budget_formatting():
    assert format_natural_spoken_budget(Decimal("7500000"), "INR") == "75 lakh rupees"
    assert format_natural_spoken_budget(Decimal("15000000"), "INR") == "1.5 crore"
    assert format_natural_spoken_budget(Decimal("20000000"), "INR") == "2 crore"
    assert format_natural_spoken_budget(Decimal("200000"), "USD") == "$200,000"


# --- Test Orchestrator Preamble Instructions ---

def test_orchestrator_preamble_no_unnecessary_currency_questions():
    orch = VoiceSessionOrchestrator(
        session_id="test_curr_preamble",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    preamble = orch._build_system_preamble()
    # Verifies strict guidance prohibiting unnecessary currency questions
    assert "9. Currency & Indian Budget Handling (STRICT - NO UNNECESSARY QUESTIONS):" in preamble
    assert "Default Currency: Default to INR (Indian Rupees)" in preamble
    assert "NEVER ask 'Which currency is your budget in?'" in preamble
    assert "50 lakhs = ₹50,00,000" in preamble
    assert "75L = ₹75,00,000" in preamble
    assert "1.5 Cr = ₹1,50,00,000" in preamble
    assert "When customer mentions lakhs, crores, L, Cr, INR, rupees or ₹, search immediately without currency clarification" in preamble
    assert "NEVER include currency questions as part of the two initial property clarification questions" in preamble
