import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    Company,
    Location,
    Project,
    Property,
    PropertyUnit,
    Pricing,
    Availability,
    Customer,
    Lead,
    SiteVisit,
)
from app.services.agent.dispatcher import dispatch_agent_tool, AGENT_TOOL_REGISTRY


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
def test_setup(db_session: Session):
    comp = Company(name="Metro Living")
    loc = Location(address_line_1="700 Pine St", city="Seattle", state="WA", postal_code="98101")
    db_session.add_all([comp, loc])
    db_session.flush()

    project = Project(company_id=comp.id, location_id=loc.id, name="Metro Pine")
    db_session.add(project)
    db_session.flush()

    tower = Property(project_id=project.id, name="Tower 1", property_type="apartment")
    db_session.add(tower)
    db_session.flush()

    unit = PropertyUnit(
        property_id=tower.id,
        unit_number="801",
        configuration_type="2BHK",
        carpet_area_sqft=Decimal("950.00"),
    )
    db_session.add(unit)
    db_session.flush()

    now = datetime.now(timezone.utc)
    pricing = Pricing(
        unit_id=unit.id,
        base_price=Decimal("580000.00"),
        total_estimated_price=Decimal("610000.00"),
        is_active=True,
        valid_from=now,
    )
    avail = Availability(
        unit_id=unit.id,
        status="available",
        is_current=True,
        valid_from=now,
    )
    db_session.add_all([pricing, avail])
    db_session.commit()

    return {"project": project, "tower": tower, "unit": unit}


def test_tool_registry_contains_all_14_tools():
    expected_tools = [
        "search_properties",
        "get_property_details",
        "get_property_price",
        "check_property_availability",
        "extract_requirements",
        "create_lead",
        "update_lead",
        "calculate_lead_priority",
        "check_visit_slots",
        "book_site_visit",
        "reschedule_site_visit",
        "cancel_site_visit",
        "transfer_to_human",
        "compare_properties",
    ]
    for t in expected_tools:
        assert t in AGENT_TOOL_REGISTRY, f"Tool '{t}' missing from AGENT_TOOL_REGISTRY!"


def test_tool_search_properties(db_session: Session, test_setup):
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="search_properties",
        raw_arguments={"city": "Seattle", "configuration_type": "2BHK", "max_budget": 600000}
    )
    assert resp.success is True
    assert resp.data["total_matches"] == 1
    assert resp.data["properties"][0]["unit_number"] == "801"


def test_tool_get_property_details(db_session: Session, test_setup):
    unit = test_setup["unit"]
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="get_property_details",
        raw_arguments={"unit_id": str(unit.id), "include_pricing_history": True}
    )
    assert resp.success is True
    assert resp.data["unit_number"] == "801"
    assert resp.data["current_pricing"]["base_price"] == 580000.0


def test_tool_get_property_price(db_session: Session, test_setup):
    unit = test_setup["unit"]
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="get_property_price",
        raw_arguments={"unit_id": str(unit.id)}
    )
    assert resp.success is True
    assert resp.data["base_price"] == 580000.0
    assert resp.data["is_verified_active"] is True


def test_tool_check_property_availability(db_session: Session, test_setup):
    unit = test_setup["unit"]
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="check_property_availability",
        raw_arguments={"unit_id": str(unit.id)}
    )
    assert resp.success is True
    assert resp.data["status"] == "available"
    assert resp.data["is_bookable"] is True


def test_tool_extract_requirements(db_session: Session):
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="extract_requirements",
        raw_arguments={"customer_utterance": "I want a 3BHK in Austin under 900k within 1 month"}
    )
    assert resp.success is True
    assert resp.data["configuration_type"] == "3BHK"
    assert resp.data["preferred_city"] == "Austin"
    assert resp.data["budget_max"] == 900000.0
    assert resp.data["is_complete"] is True


def test_tool_lead_lifecycle(db_session: Session, test_setup):
    # 1. Create Lead
    create_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="create_lead",
        raw_arguments={
            "full_name": "Peter Parker",
            "phone": "+1-206-555-7788",
            "email": "peter@dailybugle.com",
            "project_id": str(test_setup["project"].id),
            "requirements": {
                "preferred_city": "Seattle",
                "configuration_type": "2BHK",
                "budget_max": 600000.0,
                "purchase_timeline": "immediate",
                "is_complete": True,
            },
            "notes": "Spoke via voice agent.",
        }
    )
    assert create_resp.success is True
    lead_id = create_resp.data["lead_id"]
    customer_id = create_resp.data["customer_id"]

    # 2. Update Lead
    update_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="update_lead",
        raw_arguments={
            "lead_id": lead_id,
            "budget_max": 650000.0,
            "qualification_status": "ready_to_visit",
            "append_notes": "Increased budget cap by 50k.",
        }
    )
    assert update_resp.success is True
    assert update_resp.data["budget_max"] == 650000.0

    # 3. Calculate Lead Priority tool
    prio_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="calculate_lead_priority",
        raw_arguments={
            "requirements": {
                "preferred_city": "Seattle",
                "configuration_type": "2BHK",
                "budget_max": 650000.0,
                "purchase_timeline": "immediate",
                "is_complete": True,
            },
            "has_scheduled_visit": True,
        }
    )
    assert prio_resp.success is True
    assert prio_resp.data["lead_priority"] == "urgent"


def test_tool_site_visit_lifecycle(db_session: Session, test_setup):
    # Seed customer
    cust = Customer(full_name="Tony Stark", phone="+1-206-555-3000")
    db_session.add(cust)
    db_session.commit()

    tomorrow = date.today() + timedelta(days=1)
    project_id = str(test_setup["project"].id)

    # 1. Check slots
    slots_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="check_visit_slots",
        raw_arguments={"project_id": project_id, "target_date": tomorrow.isoformat()}
    )
    assert slots_resp.success is True
    assert slots_resp.data["total_available_slots"] > 0

    # 2. Book visit
    slot_time = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc).replace(hour=11)
    book_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="book_site_visit",
        raw_arguments={
            "customer_id": str(cust.id),
            "project_id": project_id,
            "scheduled_start": slot_time.isoformat(),
            "customer_notes": "Interested in penthouse or corner units.",
        }
    )
    assert book_resp.success is True
    visit_id = book_resp.data["visit_id"]
    assert book_resp.data["status"] == "scheduled"

    # 3. Reschedule visit
    new_slot = slot_time.replace(hour=15)
    resched_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="reschedule_site_visit",
        raw_arguments={
            "visit_id": visit_id,
            "new_scheduled_start": new_slot.isoformat(),
            "reschedule_reason": "Customer calendar change",
        }
    )
    assert resched_resp.success is True
    assert resched_resp.data["status"] == "rescheduled"

    # 4. Cancel visit
    cancel_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="cancel_site_visit",
        raw_arguments={
            "visit_id": visit_id,
            "cancellation_reason": "Purchased another home",
        }
    )
    assert cancel_resp.success is True
    assert cancel_resp.data["status"] == "cancelled"


def test_tool_transfer_to_human(db_session: Session):
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="transfer_to_human",
        raw_arguments={
            "customer_phone": "+1-206-555-8899",
            "reason": "Customer requested legal contract review with senior broker",
            "department": "legal",
            "conversation_summary": "Customer ready to buy, requested custom payment clauses.",
        }
    )
    assert resp.success is True
    assert resp.data["status"] == "handoff_request_queued"
    assert resp.data["telephony_bridged"] is False
    assert "handoff_ticket_id" in resp.data
    assert resp.data["department"] == "legal"

    # Also test invocation using alias 'request_human_handoff'
    alias_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="request_human_handoff",
        raw_arguments={
            "customer_phone": "+1-206-555-8899",
            "reason": "Customer wants direct human callback",
            "department": "sales",
        }
    )
    assert alias_resp.success is True
    assert alias_resp.data["status"] == "handoff_request_queued"
    assert alias_resp.data["telephony_bridged"] is False


def test_tool_dispatcher_edge_cases(db_session: Session):
    # Unknown tool
    unknown_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="non_existent_tool",
        raw_arguments={}
    )
    assert unknown_resp.success is False
    assert "not recognized" in unknown_resp.error_message

    # Invalid arguments (missing required parameters)
    bad_args_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="get_property_details",
        raw_arguments={}  # Missing unit_id
    )
    assert bad_args_resp.success is False
    assert "Invalid arguments" in bad_args_resp.error_message
