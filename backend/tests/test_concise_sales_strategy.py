"""
Test suite validating the Concise, Customer-Led Sales Strategy for AWS Nova Sonic Real Estate Voice AI.

Scenarios tested:
A. Customer asks generally for properties (at most two dynamic clarification questions).
B. Customer provides city, BHK, and budget immediately (immediate search, no re-asking).
C. Customer requests additional amenities (amenity-filtered search, top 1-2 properties, progressive disclosure).
D. Customer asks for construction or payment plans (verified dataset facts, no proactive overwhelming).
E. Customer wants only a short summary (1-2 sentence description, 2-3 amenities, key benefit, 'Would you like to know more?').
F. Customer talks continuously for a long time (uninterrupted multi-clause input, full parameter extraction).
G. Customer books a site visit (operating hours check, slot verification, booking confirmation without pressure).
H. Customer declines additional information (natural polite close, no aggressive follow-up).
"""

import asyncio
import json
import pytest
from unittest.mock import MagicMock

from app.core.config import settings
from app.schemas.agent_tools import (
    BookSiteVisitToolInput,
    CheckVisitSlotsToolInput,
    GetPropertyDetailsToolInput,
    QueryActiveDatasetToolInput,
    SearchPropertiesToolInput,
)
from app.services.agent.tools import (
    tool_book_site_visit,
    tool_check_visit_slots,
    tool_get_property_details,
    tool_query_active_dataset,
    tool_search_properties,
)
from app.services.real_estate.demo_dataset import DemoDatasetService
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.base import VoiceEventType


@pytest.fixture(autouse=True)
def enable_demo_mode():
    orig_demo = settings.DEMO_DATASET_MODE
    orig_auto_greet = settings.ENABLE_AUTOMATIC_GREETING
    settings.DEMO_DATASET_MODE = True
    settings.ENABLE_AUTOMATIC_GREETING = True
    yield
    settings.DEMO_DATASET_MODE = orig_demo
    settings.ENABLE_AUTOMATIC_GREETING = orig_auto_greet


# --- 1. Initial Greeting Verification ---

def test_initial_greeting_exact_wording():
    """Verify that the initial greeting matches: 'Hello, I'm your property assistant. How can I help you?'"""
    orch = VoiceSessionOrchestrator(
        session_id="test_greet_exact",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    preamble = orch._build_system_preamble()
    assert "Hello, I'm your property assistant. How can I help you?" in preamble
    assert "1. Initial Greeting: Always open warmly and briefly with: 'Hello, I'm your property assistant. How can I help you?'" in preamble


def test_initial_greeting_with_customer_name():
    """Verify greeting personalization when customer name is present."""
    orch = VoiceSessionOrchestrator(
        session_id="test_greet_named",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    orch.customer_name = "Vikram"
    preamble = orch._build_system_preamble()
    assert "Hello Vikram! I'm your property assistant. How can I help you?" in preamble


# --- Scenario A: Customer asks generally for properties ---

def test_scenario_a_general_property_interest_strategy():
    """
    Scenario A: When a customer expresses broad or general property interest,
    the strategy directs the assistant to ask at most two clarification questions before presenting results.
    """
    orch = VoiceSessionOrchestrator(
        session_id="test_scenario_a",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    preamble = orch._build_system_preamble()
    assert "Maximum Two Initial Clarification Questions" in preamble
    assert "ask at most TWO high-value clarification questions" in preamble
    assert "Which area would you prefer?" in preamble
    assert "Are you looking for a 2 BHK or 3 BHK?" in preamble
    assert "Never force customers through a fixed or rigid questionnaire" in preamble


# --- Scenario B: Customer provides city, BHK and budget immediately ---

def test_scenario_b_immediate_criteria_provided_skips_clarification():
    """
    Scenario B: When customer provides city, BHK, and budget upfront,
    the assistant searches immediately without re-asking.
    """
    orch = VoiceSessionOrchestrator(
        session_id="test_scenario_b",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    preamble = orch._build_system_preamble()
    assert "If the customer already provides their city, BHK configuration, or budget upfront, IMMEDIATELY search and present matching properties without asking again" in preamble

    # Execute search directly with stated criteria
    args = SearchPropertiesToolInput(
        city="Gurugram",
        configuration_type="3BHK",
        max_budget=50000000.0,
    )
    resp = tool_search_properties(db=None, args=args)
    assert resp.success is True
    # At most 2 properties presented
    assert len(resp.data["exact_matches"]) <= 2
    assert "Would you like to know more?" in resp.data["voice_grounding"]


# --- Scenario C: Customer requests additional amenities ---

def test_scenario_c_customer_requests_additional_amenities():
    """
    Scenario C: Customer requests properties with specific amenities (e.g. gym, swimming pool).
    Search returns filtered properties, presenting 1-2 units and asking 'Would you like to know more?'.
    """
    args = SearchPropertiesToolInput(
        city="Gurugram",
        required_amenities=["Clubhouse"],
        limit=5,
    )
    resp = tool_search_properties(db=None, args=args)
    assert resp.success is True
    assert len(resp.data["exact_matches"]) <= 2
    # Verify amenities and progressive disclosure question
    assert "Key amenities include" in resp.data["voice_grounding"]
    assert "Would you like to know more?" in resp.data["voice_grounding"]


# --- Scenario D: Customer asks for construction or payment plans ---

def test_scenario_d_customer_asks_construction_or_payment_plans():
    """
    Scenario D: Customer asks for construction status or payment plans.
    The assistant retrieves verified dataset facts without proactively overwhelming.
    """
    # 1. Project details includes verified possession status & RERA
    det_args = GetPropertyDetailsToolInput(unit_id="PRJ_001")
    resp_det = tool_get_property_details(db=None, args=det_args)
    assert resp_det.success is True
    assert "possession_status" in resp_det.data
    assert "rera_number" in resp_det.data

    # 2. Query active dataset for FAQ / Payment Plan
    query_args = QueryActiveDatasetToolInput(query="What is the RERA registration and payment plan?", limit=2)
    resp_faq = tool_query_active_dataset(db=None, args=query_args)
    assert resp_faq.success is True
    assert resp_faq.data.get("faq_found") is True or "voice_grounding" in resp_faq.data


# --- Scenario E: Customer wants only a short summary ---

def test_scenario_e_customer_wants_only_short_summary():
    """
    Scenario E: Customer asks for a concise summary of a property.
    The response mentions project name, location, configuration, price, 2-3 amenities, key benefit,
    and asks 'Would you like to know more?'.
    """
    args = SearchPropertiesToolInput(project_name="Godrej Aristocrat", limit=2)
    resp = tool_search_properties(db=None, args=args)
    assert resp.success is True
    assert len(resp.data["exact_matches"]) <= 2
    grounding = resp.data["voice_grounding"]
    assert "Godrej Aristocrat" in grounding
    assert "Gurugram" in grounding
    assert "Key amenities include" in grounding
    assert "developed by GODREJ PROPERTIES LIMITED" in grounding
    assert "Would you like to know more?" in grounding


# --- Scenario F: Customer talks continuously for a long time ---

def test_scenario_f_customer_long_continuous_speech():
    """
    Scenario F: The customer speaks in full sentences with multiple requirements and pauses.
    Orchestrator guidelines guarantee uninterrupted continuous listening without fixed 15/20/30s cutoffs.
    """
    orch = VoiceSessionOrchestrator(
        session_id="test_scenario_f",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    preamble = orch._build_system_preamble()
    assert "7. Natural Listening & Continuous Ingestion:" in preamble
    assert "Preserve uninterrupted customer listening without fixed 15-, 20-, or 30-second speech cutoffs" in preamble
    assert "Support long answers, natural pauses, and customer follow-up speech" in preamble
    assert "Respond only after detecting a genuine end of customer turn" in preamble


# --- Scenario G: Customer books a site visit ---

def test_scenario_g_customer_books_site_visit():
    """
    Scenario G: Customer requests an in-person site visit.
    Verifies slot availability and schedules visit within operating hours without high-pressure tactics.
    """
    # 1. Check visit slots
    slot_args = CheckVisitSlotsToolInput(
        project_identifier="PRJ_001",
        preferred_date="2026-12-20",
    )
    slot_resp = tool_check_visit_slots(db=None, args=slot_args)
    assert slot_resp.success is True
    assert len(slot_resp.data["available_slots"]) > 0

    chosen_slot = slot_resp.data["available_slots"][0]

    # 2. Book visit
    book_args = BookSiteVisitToolInput(
        project_identifier="PRJ_001",
        customer_name="Anita Sharma",
        contact_phone="+919876543210",
        customer_email="anita.sharma@example.com",
        visit_date="2026-12-20",
        visit_time_slot=chosen_slot,
    )
    book_resp = tool_book_site_visit(db=None, args=book_args)
    assert book_resp.success is True
    assert book_resp.data.get("status") == "scheduled"
    assert "visit_id" in book_resp.data


# --- Scenario H: Customer declines additional information ---

def test_scenario_h_customer_declines_additional_information():
    """
    Scenario H: Customer says: 'No, that's all I need for now, thank you.'
    Guidelines instruct assistant to acknowledge politely, avoid hard-sell pressure, and close naturally.
    """
    orch = VoiceSessionOrchestrator(
        session_id="test_scenario_h",
        driver=MockVoiceDriver(),
        db=None,
        customer_id=None,
        user_role="customer",
    )
    preamble = orch._build_system_preamble()
    assert "Avoid abrupt topic changes, hard-sell pressure, or aggressive sales language" in preamble
    assert "Offer a site visit naturally after suitable properties are identified" in preamble
    assert "without pressuring the customer" in preamble
