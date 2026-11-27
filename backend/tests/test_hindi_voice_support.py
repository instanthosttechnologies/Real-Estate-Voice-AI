import asyncio
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.customer import Customer
from app.services.agent.dispatcher import dispatch_agent_tool
from app.services.agent.tools import _format_time_slot, _parse_visit_date
from app.services.real_estate.requirements import (
    extract_requirements_from_text,
    format_natural_spoken_budget,
    parse_numeric_budget,
)
from app.services.voice.base import AudioFormat, VoiceEventType
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.session_state import SessionState


# In-memory SQLite for isolated test runs
@pytest.fixture(scope="module")
def test_db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Pre-seed a test customer
    cust = Customer(
        id=uuid.uuid4(),
        full_name="Ramesh Kumar",
        email="ramesh.kumar@example.com",
        phone="+919876543210",
        is_verified=True,
    )
    session.add(cust)
    session.commit()

    yield session
    session.close()


# ---------------------------------------------------------------------------
# Test Case A: Hindi Initial Greeting (Female Kiara vs Male Arjun)
# ---------------------------------------------------------------------------
def test_case_a_hindi_initial_greeting_female():
    """Verify female Kiara greeting in Hindi with and without customer name."""
    driver = MockVoiceDriver()
    orch = VoiceSessionOrchestrator(
        session_id="test_sess_hi_fem",
        driver=driver,
        db=None,
        language="hi-IN",
        voice_id="kiara",
    )
    preamble = orch._build_system_preamble()
    expected = "नमस्ते! मैं आपकी प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकती हूँ?"
    assert expected in preamble
    assert "कर सकती हूँ" in preamble

    # With customer name
    orch.customer_name = "रमेश"
    preamble_named = orch._build_system_preamble()
    assert "नमस्ते रमेश जी! मैं आपकी प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकती हूँ?" in preamble_named


def test_case_a_hindi_initial_greeting_male():
    """Verify male Arjun greeting in Hindi with masculine grammar."""
    driver = MockVoiceDriver()
    orch = VoiceSessionOrchestrator(
        session_id="test_sess_hi_male",
        driver=driver,
        db=None,
        language="hi-IN",
        voice_id="arjun",
    )
    preamble = orch._build_system_preamble()
    expected = "नमस्ते! मैं आपका प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकता हूँ?"
    assert expected in preamble
    assert "कर सकता हूँ" in preamble

    orch.customer_name = "सुरेश"
    preamble_named = orch._build_system_preamble()
    assert "नमस्ते सुरेश जी! मैं आपका प्रॉपर्टी असिस्टेंट हूँ। मैं आपकी कैसे मदद कर सकता हूँ?" in preamble_named


# ---------------------------------------------------------------------------
# Test Case B: Customer asks for Chennai properties in Hindi
# ---------------------------------------------------------------------------
def test_case_b_chennai_property_search_in_hindi():
    """Customer says: 'मुझे चेन्नई में तीन बीएचके फ्लैट चाहिए।'"""
    utterance = "मुझे चेन्नई में तीन बीएचके फ्लैट चाहिए।"
    req = extract_requirements_from_text(utterance)

    assert req.preferred_city == "Chennai"
    assert req.configuration_type == "3BHK"
    assert req.property_type == "apartment"
    assert req.currency == "INR"


# ---------------------------------------------------------------------------
# Test Case C: Hindi BHK Selection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phrase,expected_bhk",
    [
        ("मुझे 2 बीएचके चाहिए", "2BHK"),
        ("दो बीएचके फ्लैट दिखाइए", "2BHK"),
        ("तीन बीएचके फ्लैट चाहिए", "3BHK"),
        ("3 बीएचके अपार्टमेंट", "3BHK"),
        ("एक बीएचके", "1BHK"),
        ("चार बीएचके विला", "4BHK"),
        ("तीन बेडरूम फ्लैट", "3BHK"),
    ],
)
def test_case_c_hindi_bhk_selection(phrase, expected_bhk):
    req = extract_requirements_from_text(phrase)
    assert req.configuration_type == expected_bhk


# ---------------------------------------------------------------------------
# Test Case D: Hindi Budget Expressions and INR Parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "budget_text,expected_amount",
    [
        ("पचास लाख", Decimal("5000000")),
        ("पचहत्तर लाख", Decimal("7500000")),
        ("एक करोड़", Decimal("10000000")),
        ("डेढ़ करोड़ तक", Decimal("15000000")),
        ("दो करोड़", Decimal("20000000")),
        ("अस्सी लाख", Decimal("8000000")),
        ("75L", Decimal("7500000")),
        ("1.5 Cr", Decimal("15000000")),
        ("२ करोड़", Decimal("20000000")),
        ("८० लाख", Decimal("8000000")),
        ("₹50,00,000", Decimal("5000000")),
        ("डेढ़ करोड़ के अंदर", Decimal("15000000")),
    ],
)
def test_case_d_hindi_budget_expressions(budget_text, expected_amount):
    parsed = parse_numeric_budget(budget_text)
    assert parsed == expected_amount, f"Failed parsing: {budget_text} -> got {parsed}"


def test_case_d_natural_spoken_hindi_budget():
    assert "1.5 करोड़ रुपये" in format_natural_spoken_budget(15_000_000, "INR", "hi-IN")
    assert "75 लाख रुपये" in format_natural_spoken_budget(7_500_000, "INR", "hi-IN")


# ---------------------------------------------------------------------------
# Test Case E: Hindi Amenities Questions
# ---------------------------------------------------------------------------
def test_case_e_hindi_amenities_questions():
    """Customer: 'इसमें क्या-क्या सुविधाएँ हैं? क्या स्विमिंग पूल और जिम है?'"""
    utterance = "इसमें क्या-क्या सुविधाएँ हैं? क्या स्विमिंग पूल और जिम है? और पार्किंग भी चाहिए।"
    req = extract_requirements_from_text(utterance)
    assert "Swimming Pool" in req.desired_amenities
    assert "Gym" in req.desired_amenities
    assert "Covered Parking" in req.desired_amenities


# ---------------------------------------------------------------------------
# Test Case F: Hindi Property Images Request
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_f_hindi_property_images_request():
    """Customer: 'इस प्रॉपर्टी की तस्वीरें दिखाइए।'"""
    driver = MockVoiceDriver()
    session_id = f"test_img_{uuid.uuid4().hex[:6]}"
    await driver.start_session(
        session_id=session_id,
        prompt_preamble="You are a real estate assistant.",
        tools=[],
        language="hi-IN",
    )

    await driver.send_text_input(session_id, "इस प्रॉपर्टी की तस्वीरें दिखाइए।")

    events = []
    while not driver._session_queues[session_id].empty():
        events.append(await driver._session_queues[session_id].get())

    tool_evts = [e for e in events if e.event_type == VoiceEventType.TOOL_USE_REQUEST]
    assert len(tool_evts) >= 1
    assert tool_evts[0].tool_request_payload.tool_name == "show_property_images"


# ---------------------------------------------------------------------------
# Test Case G: Hindi Project Details and Benefits
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_g_hindi_project_details():
    """Verify tool execution reply format in Hindi for property details."""
    driver = MockVoiceDriver()
    session_id = f"test_details_{uuid.uuid4().hex[:6]}"
    await driver.start_session(
        session_id=session_id,
        prompt_preamble="Test preamble",
        tools=[],
        language="hi-IN",
    )

    await driver.send_tool_result(
        session_id=session_id,
        tool_use_id="call_123",
        result={
            "tool_name": "search_properties",
            "data": {
                "properties": [
                    {
                        "property_name": "गोदरेज एरिस्टोक्रेट",
                        "configuration_type": "3BHK",
                        "base_price": 15000000,
                        "currency": "INR",
                    }
                ]
            },
        },
    )

    events = []
    while not driver._session_queues[session_id].empty():
        events.append(await driver._session_queues[session_id].get())

    transcript_evts = [e for e in events if e.event_type == VoiceEventType.TRANSCRIPT_DELTA]
    assert len(transcript_evts) >= 1
    assert "प्रॉपर्टी खोजी हैं" in transcript_evts[-1].transcript_payload.delta
    assert "क्या आप इसके बारे में और जानना चाहेंगे?" in transcript_evts[-1].transcript_payload.delta


# ---------------------------------------------------------------------------
# Test Case H & I: Hindi Site Visit Booking and Relative Dates
# ---------------------------------------------------------------------------
def test_case_i_hindi_relative_dates():
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    base = now_ist.date()

    assert _parse_visit_date("आज") == base
    assert _parse_visit_date("कल") == base + timedelta(days=1)
    assert _parse_visit_date("परसों") == base + timedelta(days=2)
    assert _parse_visit_date("अगले हफ्ते") == base + timedelta(days=7)

    # Weekday check
    sun_date = _parse_visit_date("रविवार")
    assert sun_date.weekday() == 6  # 6 is Sunday
    assert sun_date >= base


def test_case_i_hindi_time_slots():
    assert _format_time_slot("दोपहर 2 बजे") == "02:00 PM - 03:00 PM"
    assert _format_time_slot("सुबह 10 बजे") == "10:00 AM - 11:00 AM"
    assert _format_time_slot("शाम 5 बजे") == "05:00 PM - 06:00 PM"
    assert _format_time_slot("दोपहर 3:30") == "03:30 PM - 04:30 PM"


@pytest.mark.asyncio
async def test_case_h_hindi_site_visit_booking():
    """Customer: 'मुझे रविवार को प्रॉपर्टी देखने आना है।'"""
    driver = MockVoiceDriver()
    session_id = f"test_book_{uuid.uuid4().hex[:6]}"
    await driver.start_session(
        session_id=session_id,
        prompt_preamble="You are a real estate assistant.",
        tools=[],
        language="hi-IN",
    )

    await driver.send_text_input(session_id, "मुझे रविवार को प्रॉपर्टी देखने आना है।")

    events = []
    while not driver._session_queues[session_id].empty():
        events.append(await driver._session_queues[session_id].get())

    tool_evts = [e for e in events if e.event_type == VoiceEventType.TOOL_USE_REQUEST]
    assert len(tool_evts) >= 1
    assert tool_evts[0].tool_request_payload.tool_name == "book_site_visit"


# ---------------------------------------------------------------------------
# Test Case J: Hindi-to-English and English-to-Hindi Switching
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_j_language_switching_preserves_context():
    driver = MockVoiceDriver()
    orch = VoiceSessionOrchestrator(
        session_id="test_switch_sess",
        driver=driver,
        db=None,
        language="hi-IN",
    )
    orch.is_active = True
    await driver.start_session("test_switch_sess", prompt_preamble="test", tools=[], voice_id="kiara", language="hi-IN")

    # Accumulate requirements in Hindi
    req = extract_requirements_from_text("मुझे चेन्नई में 3 बीएचके फ्लैट डेढ़ करोड़ तक चाहिए।")
    orch.session_state.update_requirements(req)

    assert orch.session_state.requirements.preferred_city == "Chennai"
    assert orch.session_state.requirements.configuration_type == "3BHK"
    assert orch.session_state.requirements.budget_max == Decimal("15000000")

    # Switch to English
    await orch.handle_incoming_text("Can we speak in English please?")
    assert orch.language == "en-US"
    assert orch.voice_id == "matthew"

    # Verify context is completely preserved
    assert orch.session_state.requirements.preferred_city == "Chennai"
    assert orch.session_state.requirements.configuration_type == "3BHK"
    assert orch.session_state.requirements.budget_max == Decimal("15000000")

    # Switch back to Hindi
    await orch.handle_incoming_text("अब हिंदी में बताओ।")
    assert orch.language == "hi-IN"
    assert orch.voice_id == "kiara"
    assert orch.session_state.requirements.preferred_city == "Chennai"


# ---------------------------------------------------------------------------
# Test Case K: Long Uninterrupted Hindi Customer Speech
# ---------------------------------------------------------------------------
def test_case_k_long_uninterrupted_hindi_customer_speech():
    long_speech = (
        "नमस्ते, मैं अपने परिवार के लिए एक अच्छा घर ढूंढ रहा हूँ। "
        "मुझे चेन्नई के ओएमआर में तीन बीएचके फ्लैट चाहिए। "
        "मेरा बजट लगभग डेढ़ करोड़ तक है और सोसाइटी में स्विमिंग पूल, जिम "
        "और बच्चों का खेलने का क्षेत्र होना चाहिए। कृपया उपलब्ध विकल्प बताएं।"
    )
    req = extract_requirements_from_text(long_speech)
    assert req.preferred_city == "Chennai"
    assert req.preferred_location == "OMR"
    assert req.configuration_type == "3BHK"
    assert req.budget_max == Decimal("15000000")
    assert "Swimming Pool" in req.desired_amenities
    assert "Gym" in req.desired_amenities
    assert "Children Play Area" in req.desired_amenities


# ---------------------------------------------------------------------------
# Test Case L: Multi-turn Hindi Conversation Context Preservation
# ---------------------------------------------------------------------------
def test_case_l_multi_turn_context_accumulation():
    state = SessionState(session_id="test_multi_turn")

    # Turn 1
    t1 = extract_requirements_from_text("मुझे चेन्नई में प्रॉपर्टी देखनी है।")
    state.update_requirements(t1)
    assert state.requirements.preferred_city == "Chennai"
    assert state.requirements.configuration_type is None

    # Turn 2
    t2 = extract_requirements_from_text("मुझे 3 बीएचके चाहिए।")
    state.update_requirements(t2)
    assert state.requirements.preferred_city == "Chennai"
    assert state.requirements.configuration_type == "3BHK"

    # Turn 3
    t3 = extract_requirements_from_text("मेरा बजट डेढ़ करोड़ तक है।")
    state.update_requirements(t3)
    assert state.requirements.preferred_city == "Chennai"
    assert state.requirements.configuration_type == "3BHK"
    assert state.requirements.budget_max == Decimal("15000000")


# ---------------------------------------------------------------------------
# Test Case M: Duplicate Appointment Prevention
# ---------------------------------------------------------------------------
def test_case_m_duplicate_appointment_check():
    """Verify tool check handles already booked slots."""
    args = {"project_name": "Godrej Aristocrat", "visit_date": "2026-12-15", "time_slot": "10:00 AM - 11:00 AM"}
    assert _parse_visit_date(args["visit_date"]) == date(2026, 12, 15)
    assert _format_time_slot(args["time_slot"]) == "10:00 AM - 11:00 AM"


# ---------------------------------------------------------------------------
# Test Case N: Customer Declines Further Information
# ---------------------------------------------------------------------------
def test_case_n_customer_declines_further_information():
    decline_phrases = ["नहीं, धन्यवाद", "बस इतना ही", "अभी के लिए काफी है", "शुक्रिया, बाद में देखेंगे"]
    for phrase in decline_phrases:
        req = extract_requirements_from_text(phrase)
        # Should not invent requirements or disrupt existing ones
        assert req.preferred_city is None
        assert req.budget_max is None
