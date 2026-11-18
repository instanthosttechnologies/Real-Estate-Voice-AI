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
    Amenity,
    ProjectAmenity,
    Property,
    PropertyUnit,
    Pricing,
    Availability,
    Customer,
    Lead,
    SiteVisit,
    User,
)
from app.services.real_estate.search import PropertySearchCriteria, search_properties
from app.services.real_estate.matcher import CustomerPreferences, rank_and_explain_matches
from app.services.real_estate.details import get_property_unit_details
from app.services.real_estate.availability import check_unit_availability
from app.services.real_estate.requirements import (
    ExtractedCustomerRequirements,
    extract_requirements_from_text,
    parse_numeric_budget,
)
from app.services.real_estate.priority import calculate_lead_priority, apply_manual_priority_override
from app.services.real_estate.leads import CreateLeadInput, UpdateLeadInput, create_customer_lead, update_customer_lead
from app.services.real_estate.site_visits import (
    BookVisitInput,
    RescheduleVisitInput,
    book_site_visit,
    cancel_site_visit,
    get_available_visit_slots,
    reschedule_site_visit,
)


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
def seeded_real_estate_db(db_session: Session):
    # Developer
    developer = Company(name="Pinnacle Living", phone="+1-206-555-0100")
    # Location
    loc_seattle = Location(
        address_line_1="1500 5th Ave",
        city="Seattle",
        state="WA",
        postal_code="98101",
        landmark="Westlake Center",
    )
    db_session.add_all([developer, loc_seattle])
    db_session.flush()

    # Project
    project = Project(
        company_id=developer.id,
        location_id=loc_seattle.id,
        name="Pinnacle Tower",
        status="ready_to_move",
    )
    db_session.add(project)
    db_session.flush()

    # Amenities
    pool = Amenity(name="Swimming Pool", category="Leisure")
    gym = Amenity(name="Gym", category="Fitness")
    parking = Amenity(name="Covered Parking", category="Convenience")
    db_session.add_all([pool, gym, parking])
    db_session.flush()

    db_session.add_all([
        ProjectAmenity(project_id=project.id, amenity_id=pool.id),
        ProjectAmenity(project_id=project.id, amenity_id=gym.id),
        ProjectAmenity(project_id=project.id, amenity_id=parking.id),
    ])

    # Tower
    tower = Property(project_id=project.id, name="Tower A", property_type="apartment")
    db_session.add(tower)
    db_session.flush()

    # Unit 1: 2BHK Available $650,000
    u1 = PropertyUnit(
        property_id=tower.id,
        unit_number="1001",
        configuration_type="2BHK",
        carpet_area_sqft=Decimal("1150.00"),
        floor_number=10,
        facing="West",
        balcony_count=1,
    )
    # Unit 2: 3BHK Available $920,000
    u2 = PropertyUnit(
        property_id=tower.id,
        unit_number="1501",
        configuration_type="3BHK",
        carpet_area_sqft=Decimal("1650.00"),
        floor_number=15,
        facing="North",
        balcony_count=2,
    )
    # Unit 3: 1BHK Sold $450,000
    u3 = PropertyUnit(
        property_id=tower.id,
        unit_number="501",
        configuration_type="1BHK",
        carpet_area_sqft=Decimal("720.00"),
        floor_number=5,
        facing="East",
        balcony_count=1,
    )
    db_session.add_all([u1, u2, u3])
    db_session.flush()

    now = datetime.now(timezone.utc)
    # Pricing
    p1 = Pricing(unit_id=u1.id, base_price=Decimal("650000.00"), total_estimated_price=Decimal("690000.00"), is_active=True, valid_from=now)
    p2 = Pricing(unit_id=u2.id, base_price=Decimal("920000.00"), total_estimated_price=Decimal("980000.00"), is_active=True, valid_from=now)
    p3 = Pricing(unit_id=u3.id, base_price=Decimal("450000.00"), total_estimated_price=Decimal("480000.00"), is_active=True, valid_from=now)
    db_session.add_all([p1, p2, p3])

    # Availability
    a1 = Availability(unit_id=u1.id, status="available", is_current=True, valid_from=now)
    a2 = Availability(unit_id=u2.id, status="available", is_current=True, valid_from=now)
    a3 = Availability(unit_id=u3.id, status="sold", is_current=True, valid_from=now)
    db_session.add_all([a1, a2, a3])
    db_session.commit()

    return {
        "project": project,
        "tower": tower,
        "u1_2bhk": u1,
        "u2_3bhk": u2,
        "u3_1bhk_sold": u3,
        "pool": pool,
        "gym": gym,
    }


# -----------------------------------------------------------------------------
# 1. Property Search Engine Tests
# -----------------------------------------------------------------------------

def test_property_search_by_city_and_config(db_session: Session, seeded_real_estate_db):
    criteria = PropertySearchCriteria(
        city="Seattle",
        configuration_type="2BHK",
        availability_status="available",
    )
    results = search_properties(db_session, criteria)
    assert len(results) == 1
    item = results[0]
    assert item.unit_number == "1001"
    assert item.base_price == Decimal("650000.00")
    assert "Swimming Pool" in item.amenities


def test_property_search_by_budget_range(db_session: Session, seeded_real_estate_db):
    criteria = PropertySearchCriteria(
        city="Seattle",
        min_budget=Decimal("600000"),
        max_budget=Decimal("1000000"),
        availability_status="available",
    )
    results = search_properties(db_session, criteria)
    assert len(results) == 2
    units = [r.unit_number for r in results]
    assert "1001" in units
    assert "1501" in units


def test_property_search_required_amenities(db_session: Session, seeded_real_estate_db):
    criteria = PropertySearchCriteria(
        city="Seattle",
        required_amenities=["Swimming Pool", "Gym"],
        availability_status="available",
    )
    results = search_properties(db_session, criteria)
    assert len(results) == 2


def test_property_search_zero_matches_never_invents(db_session: Session, seeded_real_estate_db):
    criteria = PropertySearchCriteria(
        city="NonExistentCity",
        configuration_type="5BHK",
    )
    results = search_properties(db_session, criteria)
    assert len(results) == 0


# -----------------------------------------------------------------------------
# 2. Property Matching Engine Tests
# -----------------------------------------------------------------------------

def test_property_matching_and_explanation(db_session: Session, seeded_real_estate_db):
    all_props = search_properties(db_session, PropertySearchCriteria(city="Seattle", availability_status="available"))
    prefs = CustomerPreferences(
        preferred_city="Seattle",
        preferred_config="2BHK",
        budget_max=Decimal("700000"),
        desired_amenities=["Swimming Pool"],
    )
    ranked = rank_and_explain_matches(all_props, prefs)
    assert len(ranked) == 2
    # The 2BHK unit should rank higher than the 3BHK unit
    assert ranked[0].property.unit_number == "1001"
    assert ranked[0].match_score > ranked[1].match_score
    assert "Exact match for desired layout (2BHK)" in ranked[0].match_summary
    assert "Within budget" in ranked[0].match_summary


# -----------------------------------------------------------------------------
# 3. Property Details & Verified Pricing Tests
# -----------------------------------------------------------------------------

def test_property_unit_details_and_active_pricing(db_session: Session, seeded_real_estate_db):
    u1 = seeded_real_estate_db["u1_2bhk"]
    details = get_property_unit_details(db_session, u1.id, include_pricing_history=True)

    assert details is not None
    assert details.unit_number == "1001"
    assert details.current_pricing is not None
    assert details.current_pricing.base_price == Decimal("650000.00")
    assert details.current_pricing.is_active is True
    assert details.current_availability == "available"


# -----------------------------------------------------------------------------
# 4. Live Availability Engine Tests
# -----------------------------------------------------------------------------

def test_live_availability_status_distinction(db_session: Session, seeded_real_estate_db):
    u1 = seeded_real_estate_db["u1_2bhk"]
    u3 = seeded_real_estate_db["u3_1bhk_sold"]

    avail_u1 = check_unit_availability(db_session, u1.id)
    assert avail_u1.status == "available"
    assert avail_u1.is_bookable is True

    avail_u3 = check_unit_availability(db_session, u3.id)
    assert avail_u3.status == "sold"
    assert avail_u3.is_bookable is False
    assert "sold" in avail_u3.remarks

    # Non-existent unit returns unknown
    fake_unit_avail = check_unit_availability(db_session, uuid.uuid4())
    assert fake_unit_avail.status == "unknown"
    assert fake_unit_avail.is_bookable is False


# -----------------------------------------------------------------------------
# 5. Customer Requirement Extraction Tests
# -----------------------------------------------------------------------------

def test_numeric_budget_parser():
    assert parse_numeric_budget("$1.2M") == Decimal("1200000")
    assert parse_numeric_budget("850k") == Decimal("850000")
    assert parse_numeric_budget("650,000") == Decimal("650000")
    assert parse_numeric_budget("2 million") == Decimal("2000000")


def test_customer_requirement_extraction_complete():
    utterance = "I'm looking to buy a 2 BHK apartment in Seattle under 800k with a swimming pool, ready to move."
    extracted = extract_requirements_from_text(utterance)

    assert extracted.intent_type == "buy"
    assert extracted.configuration_type == "2BHK"
    assert extracted.preferred_city == "Seattle"
    assert extracted.budget_max == Decimal("800000")
    assert "Swimming Pool" in extracted.desired_amenities
    assert extracted.purchase_timeline == "immediate"
    assert extracted.is_complete is True
    assert len(extracted.missing_fields) == 0


def test_customer_requirement_extraction_incomplete_and_clarification():
    utterance = "Hi, I need a place in Denver."
    extracted = extract_requirements_from_text(utterance)

    assert extracted.preferred_city == "Denver"
    assert extracted.is_complete is False
    assert "budget" in extracted.missing_fields
    assert "configuration (e.g. 2BHK, 3BHK)" in extracted.missing_fields
    assert extracted.clarification_prompt is not None


# -----------------------------------------------------------------------------
# 6 & 7. Lead Management & Priority Engine Tests
# -----------------------------------------------------------------------------

def test_lead_priority_classification():
    # Urgent: immediate + budget + site visit
    urgent_req = ExtractedCustomerRequirements(
        configuration_type="3BHK",
        preferred_city="Seattle",
        budget_max=Decimal("1200000"),
        purchase_timeline="immediate",
        is_complete=True,
    )
    eval_urgent = calculate_lead_priority(urgent_req, has_scheduled_visit=True)
    assert eval_urgent.lead_priority == "urgent"
    assert eval_urgent.priority_score >= 80

    # Low: exploring without budget
    low_req = ExtractedCustomerRequirements(
        purchase_timeline="exploring",
        is_complete=False,
    )
    eval_low = calculate_lead_priority(low_req)
    assert eval_low.lead_priority == "low"
    assert eval_low.priority_score < 35


def test_create_lead_and_manual_override(db_session: Session, seeded_real_estate_db):
    user = User(email="manager@realtor.com", hashed_password="x", role="admin")
    db_session.add(user)
    db_session.commit()

    req = ExtractedCustomerRequirements(
        configuration_type="2BHK",
        preferred_city="Seattle",
        budget_max=Decimal("700000"),
        purchase_timeline="1_3_months",
        is_complete=True,
    )
    lead_input = CreateLeadInput(
        full_name="Bruce Wayne",
        phone="+1-206-555-9000",
        email="bruce@wayne.com",
        project_id=seeded_real_estate_db["project"].id,
        requirements=req,
        initial_notes="Prefers high floor with city views.",
    )
    lead_resp = create_customer_lead(db_session, lead_input)
    assert lead_resp.customer_name == "Bruce Wayne"
    assert lead_resp.lead_priority in ["high", "medium"]

    # Manual Priority Override
    overridden = apply_manual_priority_override(
        db=db_session,
        lead_id=lead_resp.lead_id,
        new_priority="urgent",
        override_reason="VIP cash buyer confirmed via phone conversation.",
        actor_user_id=user.id,
        actor_role=user.role,
    )
    assert overridden.lead_priority == "urgent"


# -----------------------------------------------------------------------------
# 8. Site Visit Management Tests
# -----------------------------------------------------------------------------

def test_site_visit_booking_reschedule_and_cancellation(db_session: Session, seeded_real_estate_db):
    project = seeded_real_estate_db["project"]
    cust = Customer(full_name="Diana Prince", phone="+1-206-555-1122")
    db_session.add(cust)
    db_session.commit()

    tomorrow = date.today() + timedelta(days=1)
    slots_resp = get_available_visit_slots(db_session, project.id, tomorrow)
    assert len(slots_resp.slots) == 9  # 9 AM to 6 PM

    # Book slot
    start_time = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc).replace(hour=10)
    book_input = BookVisitInput(
        customer_id=cust.id,
        project_id=project.id,
        scheduled_start=start_time,
        scheduled_end=start_time + timedelta(hours=1),
        customer_notes="Wants tour of 2BHK models.",
    )
    visit = book_site_visit(db_session, book_input)
    assert visit.status == "scheduled"
    assert visit.project_name == project.name

    # Double Booking Prevention: Same customer booking overlapping slot
    with pytest.raises(ValueError) as exc:
        book_site_visit(db_session, book_input)
    assert "already has an active site visit scheduled" in str(exc.value)

    # Reschedule
    new_start = start_time.replace(hour=14)
    resched_input = RescheduleVisitInput(
        visit_id=visit.visit_id,
        new_scheduled_start=new_start,
        new_scheduled_end=new_start + timedelta(hours=1),
        reschedule_reason="Customer requested afternoon slot",
    )
    resched_visit = reschedule_site_visit(db_session, resched_input)
    assert resched_visit.status == "rescheduled"
    assert resched_visit.scheduled_start.hour == 14

    # Cancel
    cancelled = cancel_site_visit(db_session, visit.visit_id, "Customer travel rescheduled")
    assert cancelled.status == "cancelled"


# -----------------------------------------------------------------------------
# 9. Currency Isolation & Mixed-Currency Matching Tests
# -----------------------------------------------------------------------------

def test_mixed_currency_search_and_matching(db_session: Session):
    # Setup company & locations
    builder = Company(name="Global Builders Inc", phone="+1-800-555-0199")
    loc_mumbai = Location(
        address_line_1="Bandra Kurla Complex",
        city="Mumbai",
        state="Maharashtra",
        postal_code="400051",
    )
    loc_seattle = Location(
        address_line_1="100 Pine St",
        city="Seattle",
        state="WA",
        postal_code="98101",
    )
    db_session.add_all([builder, loc_mumbai, loc_seattle])
    db_session.flush()

    # Project 1: Mumbai (INR)
    proj_mumbai = Project(
        company_id=builder.id,
        location_id=loc_mumbai.id,
        name="Mumbai Ocean Heights",
        timezone="Asia/Kolkata",
        status="under_construction",
    )
    # Project 2: Seattle (USD)
    proj_seattle = Project(
        company_id=builder.id,
        location_id=loc_seattle.id,
        name="Seattle Pine Residences",
        timezone="America/Los_Angeles",
        status="ready_to_move",
    )
    db_session.add_all([proj_mumbai, proj_seattle])
    db_session.flush()

    # Properties
    prop_inr = Property(project_id=proj_mumbai.id, name="Tower Alpha", property_type="apartment")
    prop_usd = Property(project_id=proj_seattle.id, name="West Tower", property_type="apartment")
    db_session.add_all([prop_inr, prop_usd])
    db_session.flush()

    # Units
    unit_inr = PropertyUnit(
        property_id=prop_inr.id,
        unit_number="1201",
        configuration_type="3BHK",
        carpet_area_sqft=Decimal("1450"),
    )
    unit_usd = PropertyUnit(
        property_id=prop_usd.id,
        unit_number="502",
        configuration_type="2BHK",
        carpet_area_sqft=Decimal("950"),
    )
    db_session.add_all([unit_inr, unit_usd])
    db_session.flush()

    # Pricing (INR 1.5 Crore vs USD 850,000)
    db_session.add_all([
        Pricing(
            unit_id=unit_inr.id,
            base_price=Decimal("15000000"),  # 1.5 Crore INR
            total_estimated_price=Decimal("15500000"),
            currency="INR",
            is_active=True,
        ),
        Availability(
            unit_id=unit_inr.id,
            status="available",
            is_current=True,
        ),
        Pricing(
            unit_id=unit_usd.id,
            base_price=Decimal("850000"),  # 850k USD
            total_estimated_price=Decimal("870000"),
            currency="USD",
            is_active=True,
        ),
        Availability(
            unit_id=unit_usd.id,
            status="available",
            is_current=True,
        ),
    ])
    db_session.commit()

    # 1. Strict Search by Currency: INR
    inr_results = search_properties(db_session, PropertySearchCriteria(currency="INR"))
    assert len(inr_results) == 1
    assert inr_results[0].currency == "INR"
    assert inr_results[0].base_price == Decimal("15000000")
    assert inr_results[0].city == "Mumbai"

    # 2. Strict Search by Currency: USD
    usd_results = search_properties(db_session, PropertySearchCriteria(currency="USD"))
    assert len(usd_results) == 1
    assert usd_results[0].currency == "USD"
    assert usd_results[0].base_price == Decimal("850000")
    assert usd_results[0].city == "Seattle"

    # 3. Currency Isolation in Budget Matching
    # Customer has budget in INR, property is in USD
    inr_preferences = CustomerPreferences(
        preferred_config="2BHK",
        budget_max=Decimal("20000000"),  # 2 Crore INR
        preferred_currency="INR",
    )
    # Attempting to match USD property against INR preferences must flag currency mismatch
    matches = rank_and_explain_matches([usd_results[0]], inr_preferences)
    assert len(matches) == 1
    assert any("Currency mismatch" in r for r in matches[0].match_reasons)
    assert "never silently converted" in matches[0].match_reasons[1]


def test_indian_and_global_currency_requirement_extraction():
    # Indian Crores extraction
    req1 = extract_requirements_from_text("Looking for a 3 BHK in Mumbai under 2.5 Crores with gym")
    assert req1.configuration_type == "3BHK"
    assert req1.preferred_city == "Mumbai"
    assert req1.budget_max == Decimal("25000000")
    assert req1.currency == "INR"
    assert "Gym" in req1.desired_amenities

    # Indian Lakhs / Lacs extraction
    req2 = extract_requirements_from_text("Need 2 BHK in Bangalore around 75 Lakhs ready to move")
    assert req2.configuration_type == "2BHK"
    assert req2.preferred_city == "Bangalore"
    assert req2.budget_max == Decimal("7500000")
    assert req2.currency == "INR"

    # British Pound extraction
    req3 = extract_requirements_from_text("Want 2 bedroom flat in London under £650k")
    assert req3.configuration_type == "2BHK"
    assert req3.preferred_city == "London"
    assert req3.budget_max == Decimal("650000")
    assert req3.currency == "GBP"

    # UAE Dirhams range extraction
    req4 = extract_requirements_from_text("Searching for villa in Dubai between 1.5M and 2M AED")
    assert req4.property_type == "villa"
    assert req4.preferred_city == "Dubai"
    assert req4.budget_min == Decimal("1500000")
    assert req4.budget_max == Decimal("2000000")
    assert req4.currency == "AED"


# -----------------------------------------------------------------------------
# 10. Timezone & Operating Hours Scheduling Tests
# -----------------------------------------------------------------------------

def test_project_timezone_operating_hours(db_session: Session):
    company = Company(name="Metro Corp", phone="+91-22-5555-1234")
    loc = Location(address_line_1="MG Road", city="Bengaluru", state="Karnataka", postal_code="560001")
    db_session.add_all([company, loc])
    db_session.flush()

    # Project in India (IST = UTC+05:30)
    project_ist = Project(
        company_id=company.id,
        location_id=loc.id,
        name="Bengaluru Green Tech",
        timezone="Asia/Kolkata",
        status="ready_to_move",
    )
    db_session.add(project_ist)
    db_session.flush()

    customer = Customer(full_name="Arun Sharma", phone="+91-98765-43210")
    db_session.add(customer)
    db_session.commit()

    test_date = date(2026, 12, 1)
    slots_resp = get_available_visit_slots(db_session, project_ist.id, test_date)
    assert len(slots_resp.slots) == 9
    assert slots_resp.project_timezone == "Asia/Kolkata"

    # 1. First slot is 09:00 AM IST, which corresponds to 03:30 UTC
    first_slot = slots_resp.slots[0]
    assert first_slot.timezone == "Asia/Kolkata"
    assert "09:00 AM" in first_slot.local_display
    assert first_slot.start_time.hour == 3 and first_slot.start_time.minute == 30

    # 2. Book appointment at 10:00 AM IST (04:30 UTC) - within operating hours
    from zoneinfo import ZoneInfo
    ist_tz = ZoneInfo("Asia/Kolkata")
    valid_booking_time = datetime(2026, 12, 1, 10, 0, tzinfo=ist_tz)
    booking = book_site_visit(
        db_session,
        BookVisitInput(
            customer_id=customer.id,
            project_id=project_ist.id,
            scheduled_start=valid_booking_time,
        )
    )
    assert booking.status == "scheduled"

    # 3. Attempt booking outside operating hours (e.g. 02:00 AM IST) -> must fail
    invalid_time = datetime(2026, 12, 1, 2, 0, tzinfo=ist_tz)
    customer2 = Customer(full_name="Raj Patel", phone="+91-98765-43211")
    db_session.add(customer2)
    db_session.commit()

    with pytest.raises(ValueError) as exc:
        book_site_visit(
            db_session,
            BookVisitInput(
                customer_id=customer2.id,
                project_id=project_ist.id,
                scheduled_start=invalid_time,
            )
        )
    assert "within project operating hours" in str(exc.value)


def test_dst_timezone_transition_handling(db_session: Session):
    company = Company(name="West Coast Developers", phone="+1-415-555-0100")
    loc = Location(address_line_1="Market St", city="San Francisco", state="CA", postal_code="94105")
    db_session.add_all([company, loc])
    db_session.flush()

    # Project in US Pacific Time (has DST)
    project_pacific = Project(
        company_id=company.id,
        location_id=loc.id,
        name="Bay View Towers",
        timezone="America/Los_Angeles",
        status="ready_to_move",
    )
    db_session.add(project_pacific)
    db_session.commit()

    # Winter date (Standard Time: PST = UTC-8)
    winter_date = date(2026, 1, 15)
    winter_slots = get_available_visit_slots(db_session, project_pacific.id, winter_date)
    # 09:00 AM PST = 17:00 UTC (9 + 8)
    assert winter_slots.slots[0].start_time.hour == 17

    # Summer date (Daylight Saving Time: PDT = UTC-7)
    summer_date = date(2026, 7, 15)
    summer_slots = get_available_visit_slots(db_session, project_pacific.id, summer_date)
    # 09:00 AM PDT = 16:00 UTC (9 + 7)
    assert summer_slots.slots[0].start_time.hour == 16
