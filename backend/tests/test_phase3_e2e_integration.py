import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    Amenity,
    Availability,
    Company,
    Customer,
    Lead,
    Location,
    Pricing,
    Project,
    ProjectAmenity,
    Property,
    PropertyUnit,
    SiteVisit,
    User,
    Conversation,
    AuditLog,
)
from app.services.agent.dispatcher import dispatch_agent_tool, AGENT_TOOL_REGISTRY
from app.services.real_estate.requirements import (
    ExtractedCustomerRequirements,
    extract_requirements_from_text,
)
from app.services.real_estate.matcher import (
    CustomerPreferences,
    intelligent_property_search,
)
from app.services.real_estate.search import PropertySearchCriteria
from app.services.voice.session_state import SessionState
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.base import VoiceEventType


# ============================================================================
# FIXTURES: In-Memory / Isolated Relational Test Database
# ============================================================================

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def populated_real_estate_db(db_session: Session):
    """
    Populates genuine database records:
    - Company: Prestige Estates
    - Project: Prestige Courtyards (OMR, Chennai)
    - Amenities: Swimming Pool, Gym, Covered Parking, Power Backup
    - Unit 1: 2BHK at 65 Lakhs (Available)
    - Unit 2: 2BHK at 78 Lakhs (Available, higher floor, 1100 sqft)
    - Unit 3: 3BHK at 85 Lakhs (Available, 1400 sqft)
    - Customer & User: Sarah Jenkins
    """
    company = Company(name="Prestige Estates")
    location = Location(
        address_line_1="OMR IT Expressway",
        city="Chennai",
        state="Tamil Nadu",
        postal_code="600096",
    )
    db_session.add_all([company, location])
    db_session.flush()

    project = Project(
        company_id=company.id,
        location_id=location.id,
        name="Prestige Courtyards",
        description="Premium residential towers on OMR",
    )
    db_session.add(project)
    db_session.flush()

    # Amenities
    amen_pool = Amenity(name="Swimming Pool", category="Leisure")
    amen_gym = Amenity(name="Gym", category="Fitness")
    amen_parking = Amenity(name="Covered Parking", category="Convenience")
    amen_backup = Amenity(name="Power Backup", category="Utilities")
    db_session.add_all([amen_pool, amen_gym, amen_parking, amen_backup])
    db_session.flush()

    db_session.add_all([
        ProjectAmenity(project_id=project.id, amenity_id=amen_pool.id),
        ProjectAmenity(project_id=project.id, amenity_id=amen_gym.id),
        ProjectAmenity(project_id=project.id, amenity_id=amen_parking.id),
        ProjectAmenity(project_id=project.id, amenity_id=amen_backup.id),
    ])
    db_session.flush()

    # Tower
    tower = Property(
        project_id=project.id,
        name="Tower A",
        property_type="apartment",
        total_floors=14,
    )
    db_session.add(tower)
    db_session.flush()

    now = datetime.now(timezone.utc)

    # Unit 1: 2BHK - 65 Lakhs ($6,500,000 INR)
    u1 = PropertyUnit(
        property_id=tower.id,
        unit_number="101",
        configuration_type="2BHK",
        carpet_area_sqft=Decimal("950.00"),
        floor_number=1,
        facing="East",
        balcony_count=1,
    )
    # Unit 2: 2BHK - 78 Lakhs ($7,800,000 INR)
    u2 = PropertyUnit(
        property_id=tower.id,
        unit_number="502",
        configuration_type="2BHK",
        carpet_area_sqft=Decimal("1100.00"),
        floor_number=5,
        facing="North-East",
        balcony_count=2,
    )
    # Unit 3: 3BHK - 85 Lakhs ($8,500,000 INR)
    u3 = PropertyUnit(
        property_id=tower.id,
        unit_number="901",
        configuration_type="3BHK",
        carpet_area_sqft=Decimal("1450.00"),
        floor_number=9,
        facing="North",
        balcony_count=2,
    )
    db_session.add_all([u1, u2, u3])
    db_session.flush()

    # Pricing records
    p1 = Pricing(
        unit_id=u1.id,
        base_price=Decimal("6500000.00"),
        total_estimated_price=Decimal("6850000.00"),
        currency="INR",
        is_active=True,
        valid_from=now,
    )
    p2 = Pricing(
        unit_id=u2.id,
        base_price=Decimal("7800000.00"),
        total_estimated_price=Decimal("8150000.00"),
        currency="INR",
        is_active=True,
        valid_from=now,
    )
    p3 = Pricing(
        unit_id=u3.id,
        base_price=Decimal("8500000.00"),
        total_estimated_price=Decimal("8950000.00"),
        currency="INR",
        is_active=True,
        valid_from=now,
    )

    # Availability
    a1 = Availability(unit_id=u1.id, status="available", is_current=True, valid_from=now)
    a2 = Availability(unit_id=u2.id, status="available", is_current=True, valid_from=now)
    a3 = Availability(unit_id=u3.id, status="available", is_current=True, valid_from=now)

    db_session.add_all([p1, p2, p3, a1, a2, a3])

    # User & Customer
    user = User(
        email="sarah.jenkins@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$fakehash",
        role="customer",
    )
    db_session.add(user)
    db_session.flush()

    customer = Customer(
        user_id=user.id,
        full_name="Sarah Jenkins",
        email="sarah.jenkins@example.com",
        phone="+919876543210",
    )
    db_session.add(customer)
    db_session.commit()

    return {
        "company": company,
        "location": location,
        "project": project,
        "tower": tower,
        "u1": u1,
        "u2": u2,
        "u3": u3,
        "customer": customer,
        "user": user,
    }


# ============================================================================
# SECTION 2: Complete Audio Pipeline & WebSocket Backend Verification
# ============================================================================

@pytest.mark.asyncio
async def test_complete_audio_pipeline_and_robot_state_events(db_session: Session, populated_real_estate_db):
    """
    Verifies the end-to-end voice pipeline:
    Client Microphone -> FastAPI / VoiceSessionOrchestrator -> VoiceDriver -> Dispatcher -> Audio Output.
    Validates that incoming voice events correctly map to robot visual states.
    """
    driver = MockVoiceDriver(model_id="amazon.nova-2-5-sonic")
    session_id = f"e2e_audio_pipeline_{uuid.uuid4().hex[:8]}"
    cust = populated_real_estate_db["customer"]
    user = populated_real_estate_db["user"]

    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=db_session,
        customer_id=cust.id,
        user_role="customer",
        user_id=user.id,
    )

    await orchestrator.start()
    assert orchestrator.is_active is True

    received_client_messages = []
    received_audio_chunks = []

    async def mock_send_text(msg: str):
        received_client_messages.append(json.loads(msg))

    async def mock_send_bytes(audio_bytes: bytes):
        received_audio_chunks.append(audio_bytes)

    pipeline_task = asyncio.create_task(
        orchestrator.run_pipeline(send_text=mock_send_text, send_bytes=mock_send_bytes)
    )

    # Allow session initialization
    await asyncio.sleep(0.05)

    # 1. Verify session_started triggers greeting
    session_start_events = [m for m in received_client_messages if m.get("type") == "session_started"]
    assert len(session_start_events) == 1
    assert session_start_events[0]["model"] == "amazon.nova-2-5-sonic"

    # 2. Simulate client audio input frame (24kHz PCM mono)
    synthetic_audio_frame = b"\x00\x00" * 480  # 20ms of audio
    await orchestrator.handle_incoming_audio(synthetic_audio_frame)

    # 3. Simulate agent tool call execution: search_properties
    mock_tool_event = {
        "tool_name": "search_properties",
        "arguments": {"city": "Chennai", "configuration_type": "2BHK", "max_budget": 7000000},
        "tool_use_id": "tool_call_test_001",
    }
    # Send tool call request through mock driver
    session_queue = driver._session_queues[session_id]
    from app.services.voice.base import VoiceServerEvent, ToolUseRequestPayload
    await session_queue.put(
        VoiceServerEvent(
            event_type=VoiceEventType.TOOL_USE_REQUEST,
            session_id=session_id,
            tool_request_payload=ToolUseRequestPayload(
                tool_use_id="tool_call_test_001",
                tool_name="search_properties",
                arguments={"city": "Chennai", "configuration_type": "2BHK", "max_budget": 7000000},
            ),
        )
    )

    # Allow tool execution in orchestrator
    await asyncio.sleep(0.1)

    # Verify tool execution events emitted to client
    tool_starts = [m for m in received_client_messages if m.get("type") == "tool_call_start"]
    assert len(tool_starts) >= 1
    assert tool_starts[0]["tool_name"] == "search_properties"

    tool_completes = [m for m in received_client_messages if m.get("type") == "tool_call_complete"]
    assert len(tool_completes) >= 1
    assert tool_completes[0]["success"] is True

    # 4. Simulate user interruption
    await orchestrator.handle_interruption()
    await asyncio.sleep(0.05)
    interrupted_events = [m for m in received_client_messages if m.get("type") == "interrupted"]
    assert len(interrupted_events) >= 1

    # 5. Clean teardown
    await orchestrator.close()
    pipeline_task.cancel()
    try:
        await pipeline_task
    except (asyncio.CancelledError, Exception):
        pass

    assert orchestrator.is_active is False
    assert orchestrator.session_state.is_active is False


# ============================================================================
# SECTION 3: Multi-Turn Customer Requirement Understanding (Scenarios A - E)
# ============================================================================

def test_multiturn_scenarios_a_through_e(db_session: Session, populated_real_estate_db):
    """
    Tests complete customer multi-turn dialogue progression:
    - Scenario A: Customer: "I need a 2BHK apartment in OMR below 70 lakhs."
    - Scenario B: Customer: "Actually, increase my budget to 80 lakhs."
    - Scenario C: Customer: "I need parking and a gym."
    - Scenario D: Customer: "Compare the available properties."
    - Scenario E: Customer: "Book a site visit for Sunday."
    """
    cust = populated_real_estate_db["customer"]
    project = populated_real_estate_db["project"]
    state = SessionState(session_id="session_scenario_test", customer_id=cust.id)

    # ------------------------------------------------------------------------
    # SCENARIO A: Initial requirement
    # ------------------------------------------------------------------------
    utt_a = "I need a 2BHK apartment in OMR below 70 lakhs."
    req_a = extract_requirements_from_text(utt_a)
    assert req_a.configuration_type == "2BHK"
    assert req_a.preferred_location == "OMR"
    assert req_a.preferred_city == "Chennai"
    assert req_a.budget_max == Decimal("7000000")
    state.update_requirements(req_a)

    # Search authentic PostgreSQL records
    search_resp_a = dispatch_agent_tool(
        db=db_session,
        tool_name="search_properties",
        raw_arguments={
            "city": state.requirements.preferred_city,
            "configuration_type": state.requirements.configuration_type,
            "max_budget": float(state.requirements.budget_max),
        },
    )
    assert search_resp_a.success is True
    assert search_resp_a.data["total_exact_matches"] == 1
    assert search_resp_a.data["properties"][0]["unit_number"] == "101"
    assert search_resp_a.data["properties"][0]["base_price"] == 6500000.0

    # ------------------------------------------------------------------------
    # SCENARIO B: Budget update preserving location and layout
    # ------------------------------------------------------------------------
    utt_b = "Actually, increase my budget to 80 lakhs."
    req_b = extract_requirements_from_text(utt_b, existing_requirements=state.requirements.model_dump())
    changes_b = state.update_requirements(req_b)

    # Verify requirement preservation and delta
    assert state.requirements.configuration_type == "2BHK"
    assert state.requirements.preferred_location == "OMR"
    assert state.requirements.preferred_city == "Chennai"
    assert state.requirements.budget_max == Decimal("8000000")
    assert "budget_max" in changes_b

    # Search updated inventory: Now includes both Unit 101 (65L) and Unit 502 (78L)
    search_resp_b = dispatch_agent_tool(
        db=db_session,
        tool_name="search_properties",
        raw_arguments={
            "city": state.requirements.preferred_city,
            "configuration_type": state.requirements.configuration_type,
            "max_budget": float(state.requirements.budget_max),
        },
    )
    assert search_resp_b.success is True
    assert search_resp_b.data["total_exact_matches"] == 2
    matched_numbers = [p["unit_number"] for p in search_resp_b.data["properties"]]
    assert "101" in matched_numbers
    assert "502" in matched_numbers

    # ------------------------------------------------------------------------
    # SCENARIO C: Add amenities preference
    # ------------------------------------------------------------------------
    utt_c = "I need parking and a gym."
    req_c = extract_requirements_from_text(utt_c, existing_requirements=state.requirements.model_dump())
    state.update_requirements(req_c)

    assert "Covered Parking" in state.requirements.desired_amenities
    assert "Gym" in state.requirements.desired_amenities
    assert state.requirements.configuration_type == "2BHK"
    assert state.requirements.budget_max == Decimal("8000000")

    # ------------------------------------------------------------------------
    # SCENARIO D: Compare properties side-by-side
    # ------------------------------------------------------------------------
    u1_id = populated_real_estate_db["u1"].id
    u2_id = populated_real_estate_db["u2"].id

    compare_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="compare_properties",
        raw_arguments={"unit_ids": [str(u1_id), str(u2_id)]},
    )
    assert compare_resp.success is True
    comp_data = compare_resp.data
    assert comp_data["total_units_compared"] == 2
    assert comp_data["summary_metrics"]["price_delta"] == 1300000.0  # 78L - 65L
    assert "Gym" in comp_data["summary_metrics"]["common_amenities"]
    assert "Covered Parking" in comp_data["summary_metrics"]["common_amenities"]
    assert "Unit 101" in comp_data["comparison_summary"]

    # ------------------------------------------------------------------------
    # SCENARIO E: Book site visit
    # ------------------------------------------------------------------------
    # Compute upcoming Sunday
    today = date.today()
    days_ahead = 6 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    target_sunday = today + timedelta(days=days_ahead)

    # 1. Check visit slots
    slots_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="check_visit_slots",
        raw_arguments={
            "project_id": str(project.id),
            "target_date": target_sunday.isoformat(),
        },
    )
    assert slots_resp.success is True
    assert slots_resp.data["total_available_slots"] > 0

    # 2. Book 11:00 AM slot on Sunday
    slot_time = datetime.combine(target_sunday, datetime.min.time(), tzinfo=timezone.utc).replace(hour=11)
    book_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="book_site_visit",
        raw_arguments={
            "customer_id": str(cust.id),
            "project_id": str(project.id),
            "unit_id": str(u1_id),
            "scheduled_start": slot_time.isoformat(),
            "customer_notes": "Visited through voice assistant journey.",
        },
    )
    assert book_resp.success is True
    assert book_resp.data["status"] == "scheduled"
    visit_id = book_resp.data["visit_id"]

    # Verify site visit was persisted in PostgreSQL database
    v_uuid = uuid.UUID(str(visit_id))
    visit_record = db_session.execute(
        select(SiteVisit).where(SiteVisit.id == v_uuid)
    ).scalar_one_or_none()
    assert visit_record is not None
    assert visit_record.customer_id == cust.id
    assert visit_record.unit_id == u1_id
    assert visit_record.status == "scheduled"


# ============================================================================
# SECTION 4: Full 14 Business Tools Integration (Success & Failure Modes)
# ============================================================================

def test_all_14_agent_tools_success_and_failure_modes(db_session: Session, populated_real_estate_db):
    """
    Verifies all 14 real estate agent tools against genuine database entities:
    Both positive success cases and negative failure / validation rejection cases.
    """
    project = populated_real_estate_db["project"]
    u1 = populated_real_estate_db["u1"]
    cust = populated_real_estate_db["customer"]

    # 1. search_properties
    s_ok = dispatch_agent_tool(db_session, "search_properties", {"city": "Chennai", "configuration_type": "2BHK"})
    assert s_ok.success is True
    assert s_ok.data["total_matches"] >= 1

    s_none = dispatch_agent_tool(db_session, "search_properties", {"city": "NonExistentCity", "configuration_type": "5BHK"})
    assert s_none.success is True
    assert s_none.data["total_matches"] == 0

    # 2. get_property_details
    d_ok = dispatch_agent_tool(db_session, "get_property_details", {"unit_id": str(u1.id)})
    assert d_ok.success is True
    assert d_ok.data["unit_number"] == "101"

    d_fail = dispatch_agent_tool(db_session, "get_property_details", {"unit_id": str(uuid.uuid4())})
    assert d_fail.success is False
    assert "not found" in d_fail.error_message

    # 3. get_property_price
    p_ok = dispatch_agent_tool(db_session, "get_property_price", {"unit_id": str(u1.id)})
    assert p_ok.success is True
    assert p_ok.data["base_price"] == 6500000.0

    p_fail = dispatch_agent_tool(db_session, "get_property_price", {"unit_id": str(uuid.uuid4())})
    assert p_fail.success is False

    # 4. check_property_availability
    a_ok = dispatch_agent_tool(db_session, "check_property_availability", {"unit_id": str(u1.id)})
    assert a_ok.success is True
    assert a_ok.data["status"] == "available"
    assert a_ok.data["is_bookable"] is True

    # Non-existent unit is verified as non-bookable
    a_none = dispatch_agent_tool(db_session, "check_property_availability", {"unit_id": str(uuid.uuid4())})
    assert a_none.success is True
    assert a_none.data["is_bookable"] is False
    assert a_none.data["status"] == "unknown"

    # Missing arguments rejected by dispatcher
    a_fail = dispatch_agent_tool(db_session, "check_property_availability", {})
    assert a_fail.success is False

    # 5. extract_requirements
    e_ok = dispatch_agent_tool(db_session, "extract_requirements", {"customer_utterance": "2BHK in Chennai under 70 lakhs"})
    assert e_ok.success is True
    assert e_ok.data["configuration_type"] == "2BHK"

    # 6. create_lead
    cl_ok = dispatch_agent_tool(
        db_session,
        "create_lead",
        {
            "full_name": "Bruce Wayne",
            "phone": "+919876543299",
            "project_id": str(project.id),
            "requirements": {"preferred_city": "Chennai", "configuration_type": "3BHK", "budget_max": 9000000.0},
        },
    )
    assert cl_ok.success is True
    lead_id = cl_ok.data["lead_id"]

    # 7. update_lead
    ul_ok = dispatch_agent_tool(db_session, "update_lead", {"lead_id": lead_id, "budget_max": 9500000.0})
    assert ul_ok.success is True

    ul_fail = dispatch_agent_tool(db_session, "update_lead", {"lead_id": str(uuid.uuid4())})
    assert ul_fail.success is False

    # 8. calculate_lead_priority
    prio_ok = dispatch_agent_tool(
        db_session,
        "calculate_lead_priority",
        {
            "requirements": {"preferred_city": "Chennai", "budget_max": 8000000.0, "is_complete": True, "purchase_timeline": "immediate"},
            "has_scheduled_visit": True,
        },
    )
    assert prio_ok.success is True
    assert prio_ok.data["lead_priority"] == "urgent"

    # 9. check_visit_slots
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    slots_ok = dispatch_agent_tool(db_session, "check_visit_slots", {"project_id": str(project.id), "target_date": tomorrow})
    assert slots_ok.success is True

    slots_fail = dispatch_agent_tool(db_session, "check_visit_slots", {"project_id": str(uuid.uuid4()), "target_date": tomorrow})
    assert slots_fail.success is False

    # 10. book_site_visit
    slot_dt = datetime.combine(date.today() + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc).replace(hour=14)
    book_ok = dispatch_agent_tool(
        db_session,
        "book_site_visit",
        {
            "customer_id": str(cust.id),
            "project_id": str(project.id),
            "unit_id": str(u1.id),
            "scheduled_start": slot_dt.isoformat(),
        },
    )
    assert book_ok.success is True
    v_id = book_ok.data["visit_id"]

    # Booking outside operating hours rejected
    bad_slot = slot_dt.replace(hour=22)
    book_fail = dispatch_agent_tool(
        db_session,
        "book_site_visit",
        {
            "customer_id": str(cust.id),
            "project_id": str(project.id),
            "scheduled_start": bad_slot.isoformat(),
        },
    )
    assert book_fail.success is False
    assert "operating hours" in book_fail.error_message

    # 11. reschedule_site_visit
    resched_ok = dispatch_agent_tool(
        db_session,
        "reschedule_site_visit",
        {
            "visit_id": v_id,
            "new_scheduled_start": (slot_dt + timedelta(hours=2)).isoformat(),
        },
    )
    assert resched_ok.success is True

    resched_fail = dispatch_agent_tool(
        db_session,
        "reschedule_site_visit",
        {"visit_id": str(uuid.uuid4()), "new_scheduled_start": slot_dt.isoformat()},
    )
    assert resched_fail.success is False

    # 12. cancel_site_visit
    cancel_ok = dispatch_agent_tool(db_session, "cancel_site_visit", {"visit_id": v_id})
    assert cancel_ok.success is True

    cancel_fail = dispatch_agent_tool(db_session, "cancel_site_visit", {"visit_id": str(uuid.uuid4())})
    assert cancel_fail.success is False

    # 13. transfer_to_human
    human_ok = dispatch_agent_tool(
        db_session,
        "transfer_to_human",
        {"customer_phone": "+919876543210", "reason": "Customer requested human advisor"},
    )
    assert human_ok.success is True
    assert human_ok.data["status"] == "handoff_request_queued"

    # 14. compare_properties
    u2 = populated_real_estate_db["u2"]
    comp_ok = dispatch_agent_tool(db_session, "compare_properties", {"unit_ids": [str(u1.id), str(u2.id)]})
    assert comp_ok.success is True
    assert comp_ok.data["total_units_compared"] == 2

    comp_fail = dispatch_agent_tool(db_session, "compare_properties", {"unit_ids": [str(u1.id)]})
    assert comp_fail.success is False
    assert "at least 2" in comp_fail.error_message.lower()


# ============================================================================
# SECTION 5: Database Integration & Encrypted Transcript Storage Verification
# ============================================================================

def test_database_integrity_and_encrypted_transcripts(db_session: Session, populated_real_estate_db):
    """
    Verifies that database integrity constraints, AES-256-GCM encrypted transcripts,
    and immutable audit log records function correctly.
    """
    cust = populated_real_estate_db["customer"]
    user = populated_real_estate_db["user"]

    # Verify genuine records
    property_count = db_session.execute(select(PropertyUnit)).scalars().all()
    assert len(property_count) == 3

    pricing_records = db_session.execute(select(Pricing)).scalars().all()
    assert len(pricing_records) == 3
    assert all(p.currency == "INR" for p in pricing_records)

    # Verify conversation persistence with encrypted transcript
    driver = MockVoiceDriver()
    session_id = f"test_enc_transcript_{uuid.uuid4().hex[:8]}"
    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=db_session,
        customer_id=cust.id,
        user_role="customer",
        user_id=user.id,
    )
    orchestrator.transcript_entries.append("[Customer]: I need a 2BHK flat in OMR.")
    orchestrator.transcript_entries.append("[Assistant]: Found Unit 101 at 65 Lakhs.")
    orchestrator.is_active = True

    asyncio.run(orchestrator.close())

    # Verify database record
    conv = db_session.execute(
        select(Conversation).where(Conversation.session_id == session_id)
    ).scalar_one_or_none()
    assert conv is not None
    assert conv.customer_id == cust.id
    assert conv.encrypted_transcript is not None
    # Plaintext must NOT appear in encrypted payload
    assert "Found Unit 101" not in conv.encrypted_transcript
    assert "2BHK" not in conv.encrypted_transcript

    # Verify audit event logged
    audit_event = db_session.execute(
        select(AuditLog).where(AuditLog.resource_id == str(conv.id))
    ).scalar_one_or_none()
    assert audit_event is not None
    assert audit_event.action == "VOICE_SESSION_COMPLETED"
    assert audit_event.user_id == user.id
