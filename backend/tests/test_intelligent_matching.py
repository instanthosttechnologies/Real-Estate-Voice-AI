import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
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
)
from app.services.agent.dispatcher import dispatch_agent_tool
from app.services.real_estate.matcher import (
    CustomerPreferences,
    intelligent_property_search,
)
from app.services.real_estate.requirements import (
    ExtractedCustomerRequirements,
    extract_requirements_from_text,
)
from app.services.real_estate.search import PropertySearchCriteria
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.session_state import SessionState
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


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
def matching_inventory(db_session: Session):
    company = Company(name="Prestige Estates")
    loc_chennai = Location(
        address_line_1="OMR IT Corridor",
        city="Chennai",
        state="Tamil Nadu",
        postal_code="600096",
    )
    loc_blr = Location(
        address_line_1="Whitefield Main Rd",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560066",
    )
    db_session.add_all([company, loc_chennai, loc_blr])
    db_session.flush()

    proj_chennai = Project(
        company_id=company.id,
        location_id=loc_chennai.id,
        name="Prestige Courtyards",
    )
    proj_blr = Project(
        company_id=company.id,
        location_id=loc_blr.id,
        name="Prestige Park Grove",
    )
    db_session.add_all([proj_chennai, proj_blr])
    db_session.flush()

    # Amenities
    amen_pool = Amenity(name="Swimming Pool", category="Leisure")
    amen_gym = Amenity(name="Gym", category="Fitness")
    amen_backup = Amenity(name="Power Backup", category="Utilities")
    amen_club = Amenity(name="Clubhouse", category="Leisure")
    amen_badminton = Amenity(name="Badminton Court", category="Sports")
    db_session.add_all([amen_pool, amen_gym, amen_backup, amen_club, amen_badminton])
    db_session.flush()

    # Link amenities to Chennai project
    db_session.add_all(
        [
            ProjectAmenity(project_id=proj_chennai.id, amenity_id=amen_pool.id),
            ProjectAmenity(project_id=proj_chennai.id, amenity_id=amen_gym.id),
            ProjectAmenity(project_id=proj_chennai.id, amenity_id=amen_backup.id),
        ]
    )
    # Link amenities to BLR project
    db_session.add_all(
        [
            ProjectAmenity(project_id=proj_blr.id, amenity_id=amen_club.id),
            ProjectAmenity(project_id=proj_blr.id, amenity_id=amen_gym.id),
            ProjectAmenity(project_id=proj_blr.id, amenity_id=amen_badminton.id),
        ]
    )
    db_session.flush()

    # Chennai Tower
    tower_c = Property(
        project_id=proj_chennai.id,
        name="Tower A",
        property_type="apartment",
    )
    # BLR Tower
    tower_b = Property(
        project_id=proj_blr.id,
        name="Tower B",
        property_type="apartment",
    )
    db_session.add_all([tower_c, tower_b])
    db_session.flush()

    now = datetime.now(UTC)

    # Unit 1: Chennai 2BHK - 65 Lakhs
    unit_c1 = PropertyUnit(
        property_id=tower_c.id,
        unit_number="101",
        configuration_type="2BHK",
        carpet_area_sqft=Decimal("950.00"),
        floor_number=1,
        facing="East",
        balcony_count=1,
    )
    # Unit 2: Chennai 3BHK - 85 Lakhs (Alternative if budget was 80L)
    unit_c2 = PropertyUnit(
        property_id=tower_c.id,
        unit_number="301",
        configuration_type="3BHK",
        carpet_area_sqft=Decimal("1400.00"),
        floor_number=3,
        facing="North",
        balcony_count=2,
    )
    # Unit 3: BLR 3BHK - 1.5 Cr
    unit_b1 = PropertyUnit(
        property_id=tower_b.id,
        unit_number="501",
        configuration_type="3BHK",
        carpet_area_sqft=Decimal("1650.00"),
        floor_number=5,
        facing="North-East",
        balcony_count=2,
    )
    db_session.add_all([unit_c1, unit_c2, unit_b1])
    db_session.flush()

    # Pricing & Availability
    p_c1 = Pricing(
        unit_id=unit_c1.id,
        base_price=Decimal("6500000.00"),
        total_estimated_price=Decimal("6800000.00"),
        currency="INR",
        is_active=True,
        valid_from=now,
    )
    p_c2 = Pricing(
        unit_id=unit_c2.id,
        base_price=Decimal("8500000.00"),
        total_estimated_price=Decimal("8900000.00"),
        currency="INR",
        is_active=True,
        valid_from=now,
    )
    p_b1 = Pricing(
        unit_id=unit_b1.id,
        base_price=Decimal("15000000.00"),
        total_estimated_price=Decimal("15600000.00"),
        currency="INR",
        is_active=True,
        valid_from=now,
    )
    a_c1 = Availability(
        unit_id=unit_c1.id, status="available", is_current=True, valid_from=now
    )
    a_c2 = Availability(
        unit_id=unit_c2.id, status="available", is_current=True, valid_from=now
    )
    a_b1 = Availability(
        unit_id=unit_b1.id, status="available", is_current=True, valid_from=now
    )

    db_session.add_all([p_c1, p_c2, p_b1, a_c1, a_c2, a_b1])
    db_session.commit()

    return {
        "unit_c1": unit_c1,
        "unit_c2": unit_c2,
        "unit_b1": unit_b1,
        "proj_chennai": proj_chennai,
        "proj_blr": proj_blr,
    }


def test_exact_property_matching(db_session: Session, matching_inventory):
    """Test 1: Exact search returns genuine database records matching all mandatory criteria."""
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="search_properties",
        raw_arguments={
            "city": "Chennai",
            "configuration_type": "2BHK",
            "max_budget": 7000000,
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["total_matches"] == 1
    assert data["total_exact_matches"] == 1
    assert data["permission_required"] is False
    assert len(data["exact_matches"]) == 1

    match = data["exact_matches"][0]
    assert match["is_exact_match"] is True
    assert match["match_score"] == 100.0
    assert any("Configuration: 2BHK" in c for c in match["satisfied_constraints"])
    assert any("City: Chennai" in c for c in match["satisfied_constraints"])
    assert len(match["violated_constraints"]) == 0


def test_partial_matching_with_ranking_and_explanations(
    db_session: Session, matching_inventory
):
    """
    Test 2: When exact matches do not exist, intelligent search finds viable alternatives
    (e.g. 3BHK within 15% budget flex) and explains satisfied vs violated constraints.
    """
    criteria = PropertySearchCriteria(
        city="Chennai",
        configuration_type="3BHK",
        max_budget=Decimal(7800000),  # 78 Lakhs (Unit C2 is 85L, within 15% flex)
    )
    prefs = CustomerPreferences(
        preferred_city="Chennai",
        preferred_config="3BHK",
        budget_max=Decimal(7800000),
        preferred_currency="INR",
        desired_amenities=["swimming_pool"],
    )

    res = intelligent_property_search(db_session, criteria, prefs)
    assert res["total_exact_matches"] == 0
    assert res["total_recommended_alternatives"] >= 1

    top_alt = res["recommended_alternatives"][0]
    assert top_alt["is_exact_match"] is False
    assert top_alt["match_score"] > 60.0
    # Satisfied constraints should include configuration and city
    assert any("Configuration: 3BHK" in c for c in top_alt["satisfied_constraints"])
    assert any("City: Chennai" in c for c in top_alt["satisfied_constraints"])
    # Violated constraints should note budget
    assert any("Budget" in v for v in top_alt["violated_constraints"])
    assert top_alt["match_summary"] is not None
    assert len(top_alt["match_reasons"]) > 0


def test_zero_matching_requires_permission(db_session: Session, matching_inventory):
    """
    Test 3: Zero exact matches with available alternatives requires explicit customer permission
    and provides a transparent permission_prompt before presenting alternatives.
    """
    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="search_properties",
        raw_arguments={
            "city": "Chennai",
            "configuration_type": "3BHK",
            "max_budget": 7500000,  # 75L, Unit is 85L
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["total_exact_matches"] == 0
    assert data["total_recommended_alternatives"] >= 1
    assert data["permission_required"] is True
    assert data["permission_prompt"] is not None
    assert (
        "Would you like to explore these alternative options?"
        in data["permission_prompt"]
    )


def test_property_side_by_side_comparison(db_session: Session, matching_inventory):
    """
    Test 4: compare_properties tool compares 2-5 units side-by-side with metrics,
    price/sqft, common vs unique amenities, and summary.
    """
    u1_id = matching_inventory["unit_c1"].id
    u2_id = matching_inventory["unit_c2"].id

    resp = dispatch_agent_tool(
        db=db_session,
        tool_name="compare_properties",
        raw_arguments={"unit_ids": [str(u1_id), str(u2_id)]},
    )
    assert resp.success is True
    data = resp.data
    assert data["total_units_compared"] == 2
    assert len(data["comparison_items"]) == 2

    item1 = data["comparison_items"][0]
    item2 = data["comparison_items"][1]
    assert item1["price_per_sqft"] > 0
    assert item2["price_per_sqft"] > 0

    metrics = data["summary_metrics"]
    assert metrics["price_delta"] == 2000000.0  # 85L - 65L
    assert "Swimming Pool" in metrics["common_amenities"]
    assert data["comparison_summary"] is not None

    # Test rejection with fewer than 2 units
    bad_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="compare_properties",
        raw_arguments={"unit_ids": [str(u1_id)]},
    )
    assert bad_resp.success is False


def test_multi_turn_budget_update():
    """
    Test 5: Multi-turn customer requirement memory updates budget while preserving
    previously extracted location and configuration.
    """
    state = SessionState(session_id="session_turn_test_1")

    # Turn 1: "I am looking for a 2BHK in OMR below 70 Lakhs"
    t1_req = extract_requirements_from_text(
        "I am looking for a 2BHK flat in OMR below 70 Lakhs"
    )
    assert t1_req.preferred_location == "OMR"
    assert t1_req.preferred_city == "Chennai"
    assert t1_req.configuration_type == "2BHK"
    assert t1_req.budget_max == Decimal(7000000)
    state.update_requirements(t1_req)

    assert state.requirements.configuration_type == "2BHK"
    assert state.requirements.preferred_location == "OMR"
    assert state.requirements.budget_max == Decimal(7000000)

    # Turn 2: "Actually, my budget is 80 Lakhs"
    t2_req = extract_requirements_from_text(
        "Actually, my budget is 80 Lakhs",
        existing_requirements=state.requirements.model_dump(),
    )
    changes = state.update_requirements(t2_req)

    # Budget is updated to 80L, but 2BHK and OMR are safely preserved
    assert state.requirements.budget_max == Decimal(8000000)
    assert state.requirements.configuration_type == "2BHK"
    assert state.requirements.preferred_location == "OMR"
    assert state.requirements.preferred_city == "Chennai"
    assert "budget_max" in changes
    assert state.turn_count == 2


def test_multi_turn_location_change():
    """
    Test 6: Multi-turn location change updates location while preserving
    configuration and budget.
    """
    state = SessionState(session_id="session_turn_test_2")

    # Turn 1: 3BHK in Bengaluru with 1.5 Cr budget
    t1_req = extract_requirements_from_text(
        "Looking for 3BHK in Bengaluru with budget 1.5 Cr"
    )
    state.update_requirements(t1_req)
    assert state.requirements.preferred_city == "Bengaluru"
    assert state.requirements.configuration_type == "3BHK"
    assert state.requirements.budget_max == Decimal(15000000)

    # Turn 2: "Let's check in Whitefield instead"
    t2_req = extract_requirements_from_text(
        "Let's check in Whitefield instead",
        existing_requirements=state.requirements.model_dump(),
    )
    changes = state.update_requirements(t2_req)

    assert state.requirements.preferred_location == "Whitefield"
    assert state.requirements.preferred_city == "Bengaluru"
    assert state.requirements.configuration_type == "3BHK"
    assert state.requirements.budget_max == Decimal(15000000)
    assert "preferred_location" in changes


def test_requirement_removal_and_relaxation():
    """Test 7: Removing or relaxing individual criteria dynamically."""
    state = SessionState(session_id="session_turn_test_3")
    req = ExtractedCustomerRequirements(
        preferred_city="Chennai",
        preferred_location="OMR",
        configuration_type="2BHK",
        budget_max=Decimal(7000000),
        currency="INR",
        desired_amenities=["swimming_pool", "gym"],
    )
    state.update_requirements(req)

    # Remove budget constraint
    assert state.remove_requirement("budget") is True
    assert state.requirements.budget_max is None
    assert state.requirements.configuration_type == "2BHK"
    assert state.requirements.preferred_city == "Chennai"

    # Remove specific amenity
    assert state.remove_requirement("gym") is True
    assert state.requirements.desired_amenities == ["swimming_pool"]


@pytest.mark.asyncio
async def test_returning_customer_context_preseeded(
    db_session: Session, matching_inventory
):
    """
    Test 8: Returning customer preferences and active site visits are automatically
    retrieved and pre-seeded into SessionState and prompt preamble upon session start.
    """
    # Create customer and existing lead & site visit
    user = User(email="rajesh@example.com", hashed_password="pw", role="customer")
    db_session.add(user)
    db_session.flush()

    cust = Customer(
        user_id=user.id,
        full_name="Rajesh Kumar",
        email="rajesh@example.com",
        phone="+919876543210",
    )
    db_session.add(cust)
    db_session.flush()

    lead = Lead(
        customer_id=cust.id,
        preferred_config="2BHK",
        preferred_location="OMR",
        budget_max=Decimal("7000000.00"),
        lead_priority="high",
        qualification_status="qualified",
    )
    visit = SiteVisit(
        customer_id=cust.id,
        project_id=matching_inventory["proj_chennai"].id,
        unit_id=matching_inventory["unit_c1"].id,
        scheduled_start=datetime.now(UTC) + timedelta(days=2),
        scheduled_end=datetime.now(UTC) + timedelta(days=2, hours=1),
        status="scheduled",
    )
    db_session.add_all([lead, visit])
    db_session.commit()

    driver = MockVoiceDriver()
    session_id = "test_returning_customer_001"
    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=driver,
        db=db_session,
        customer_id=cust.id,
        user_role="customer",
        user_id=user.id,
        is_verified=True,
    )

    await orchestrator.start()

    # Verify session state was pre-seeded
    assert orchestrator.session_state.requirements.configuration_type == "2BHK"
    assert orchestrator.session_state.requirements.preferred_location == "OMR"
    assert orchestrator.session_state.requirements.budget_max == Decimal("7000000.00")
    assert (
        orchestrator.session_state.saved_requirements_from_profile["lead_priority"]
        == "high"
    )

    # Verify preamble passed to driver includes returning context
    preamble = driver._session_preambles[session_id]
    assert "RETURNING CUSTOMER CONTEXT" in preamble
    assert "Rajesh Kumar" in preamble
    assert "Configuration: 2BHK" in preamble
    assert "Scheduled Site Visits" in preamble

    await orchestrator.close()
    # Verify cleanup on close
    assert orchestrator.session_state.is_active is False


def test_session_ownership_enforcement():
    """
    Test 9: Session ownership check strictly protects customer sessions
    from cross-customer access while permitting super owners and admins.
    """
    cust_a = uuid.uuid4()
    cust_b = uuid.uuid4()

    state = SessionState(
        session_id="session_own_001", customer_id=cust_a, user_role="customer"
    )

    # Customer A accessing own session -> allowed
    assert (
        state.check_ownership(requesting_customer_id=cust_a, requesting_role="customer")
        is True
    )

    # Customer B attempting to access Customer A's session -> rejected
    assert (
        state.check_ownership(requesting_customer_id=cust_b, requesting_role="customer")
        is False
    )

    # Admin and Super Owner accessing session -> authorized by RBAC
    assert (
        state.check_ownership(requesting_customer_id=cust_b, requesting_role="admin")
        is True
    )
    assert (
        state.check_ownership(
            requesting_customer_id=cust_b, requesting_role="super_owner"
        )
        is True
    )
