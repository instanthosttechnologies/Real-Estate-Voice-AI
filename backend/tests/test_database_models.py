import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    User,
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
    Conversation,
    AuditLog,
    IngestionBatch,
    IngestionRecord,
)


@pytest.fixture
def db_session():
    # In-memory SQLite with StaticPool for instantaneous, isolated test runs
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_full_real_estate_entity_graph(db_session: Session):
    # 1. Company
    company = Company(
        name="Apex Luxury Realty",
        registration_number="REG-2026-999",
        contact_email="contact@apexluxury.com",
        phone="+1-555-0199",
    )
    db_session.add(company)
    db_session.flush()

    # 2. Location
    location = Location(
        address_line_1="100 Ocean Drive",
        city="Miami",
        state="FL",
        postal_code="33139",
        country="USA",
        latitude=25.778135,
        longitude=-80.131324,
        landmark="South Beach Park",
    )
    db_session.add(location)
    db_session.flush()

    # 3. Project
    project = Project(
        company_id=company.id,
        location_id=location.id,
        name="Oceanview Residences",
        description="Ultra-luxury beachfront apartments",
        status="under_construction",
        total_phases=2,
    )
    db_session.add(project)
    db_session.flush()

    # 4. Amenities & Project Amenity
    gym = Amenity(name="State-of-the-art Gym", category="Fitness")
    pool = Amenity(name="Infinity Pool", category="Leisure")
    db_session.add_all([gym, pool])
    db_session.flush()

    pa1 = ProjectAmenity(project_id=project.id, amenity_id=gym.id)
    pa2 = ProjectAmenity(project_id=project.id, amenity_id=pool.id)
    db_session.add_all([pa1, pa2])
    db_session.flush()

    # 5. Property (Tower)
    tower_a = Property(
        project_id=project.id,
        name="Tower A",
        property_type="apartment",
        total_floors=30,
        construction_status="active",
    )
    db_session.add(tower_a)
    db_session.flush()

    # 6. Property Unit
    unit_101 = PropertyUnit(
        property_id=tower_a.id,
        unit_number="1001",
        floor_number=10,
        configuration_type="3BHK",
        carpet_area_sqft=Decimal("1850.50"),
        super_built_up_area_sqft=Decimal("2200.00"),
        facing="East",
        balcony_count=2,
    )
    db_session.add(unit_101)
    db_session.flush()

    # 7. Initial Pricing
    now = datetime.now(timezone.utc)
    pricing_v1 = Pricing(
        unit_id=unit_101.id,
        base_price=Decimal("1250000.00"),
        currency="USD",
        maintenance_charge_monthly=Decimal("650.00"),
        parking_charge=Decimal("25000.00"),
        estimated_tax=Decimal("62500.00"),
        total_estimated_price=Decimal("1338150.00"),
        is_active=True,
        valid_from=now - timedelta(days=30),
    )
    db_session.add(pricing_v1)

    # 8. Initial Availability
    avail_v1 = Availability(
        unit_id=unit_101.id,
        status="available",
        available_from=date(2026, 12, 1),
        is_current=True,
        valid_from=now - timedelta(days=30),
    )
    db_session.add(avail_v1)
    db_session.commit()

    # Verify query relationships
    result = db_session.execute(
        select(Project).where(Project.name == "Oceanview Residences")
    )
    fetched_project = result.scalar_one()
    assert fetched_project.company_id == company.id
    assert fetched_project.location_id == location.id
    assert len(fetched_project.properties) == 1
    assert fetched_project.properties[0].name == "Tower A"


def test_preserve_pricing_and_availability_history(db_session: Session):
    """
    Mandatory instruction #4: Preserve pricing and availability history.
    Verifies that updating price/status does not overwrite past records.
    """
    company = Company(name="Prestige Builders")
    location = Location(address_line_1="5th Ave", city="Austin", state="TX", postal_code="78701")
    db_session.add_all([company, location])
    db_session.flush()

    project = Project(company_id=company.id, location_id=location.id, name="Skyline Heights")
    db_session.add(project)
    db_session.flush()

    prop = Property(project_id=project.id, name="Phase 1", property_type="apartment")
    db_session.add(prop)
    db_session.flush()

    unit = PropertyUnit(
        property_id=prop.id,
        unit_number="PH-1",
        floor_number=20,
        configuration_type="Penthouse",
        carpet_area_sqft=Decimal("3500.00"),
    )
    db_session.add(unit)
    db_session.flush()

    t0 = datetime.now(timezone.utc) - timedelta(days=60)
    t1 = datetime.now(timezone.utc) - timedelta(days=10)
    t2 = datetime.now(timezone.utc)

    # --- Historical Pricing Sequence ---
    # Price V1 (Initial launch: $2,000,000)
    p1 = Pricing(
        unit_id=unit.id,
        base_price=Decimal("2000000.00"),
        total_estimated_price=Decimal("2100000.00"),
        is_active=False,
        valid_from=t0,
        valid_to=t1,
    )
    # Price V2 (Revision: $2,250,000 active now)
    p2 = Pricing(
        unit_id=unit.id,
        base_price=Decimal("2250000.00"),
        total_estimated_price=Decimal("2360000.00"),
        is_active=True,
        valid_from=t1,
        valid_to=None,
    )
    db_session.add_all([p1, p2])

    # --- Historical Availability Sequence ---
    # Avail V1: available
    a1 = Availability(
        unit_id=unit.id,
        status="available",
        is_current=False,
        valid_from=t0,
        valid_to=t2,
    )
    # Avail V2: reserved (e.g. deposit received)
    a2 = Availability(
        unit_id=unit.id,
        status="reserved",
        is_current=True,
        valid_from=t2,
        valid_to=None,
    )
    db_session.add_all([a1, a2])
    db_session.commit()

    # Query and verify pricing history is preserved
    prices_res = db_session.execute(
        select(Pricing).where(Pricing.unit_id == unit.id).order_by(Pricing.valid_from)
    )
    all_prices = prices_res.scalars().all()
    assert len(all_prices) == 2
    assert all_prices[0].base_price == Decimal("2000000.00")
    assert all_prices[0].is_active is False
    assert all_prices[1].base_price == Decimal("2250000.00")
    assert all_prices[1].is_active is True

    # Verify availability history is preserved
    avail_res = db_session.execute(
        select(Availability).where(Availability.unit_id == unit.id).order_by(Availability.valid_from)
    )
    all_avails = avail_res.scalars().all()
    assert len(all_avails) == 2
    assert all_avails[0].status == "available"
    assert all_avails[0].is_current is False
    assert all_avails[1].status == "reserved"
    assert all_avails[1].is_current is True


def test_leads_and_site_visit_lifecycle(db_session: Session):
    company = Company(name="Metro Homes")
    location = Location(address_line_1="1st St", city="Denver", state="CO", postal_code="80202")
    db_session.add_all([company, location])
    db_session.flush()

    project = Project(company_id=company.id, location_id=location.id, name="Metro Heights")
    db_session.add(project)
    db_session.flush()

    # Customer
    customer = Customer(
        full_name="Sarah Connor",
        email="sarah@example.com",
        phone="+1-303-555-0144",
    )
    db_session.add(customer)
    db_session.flush()

    # Lead qualified by Voice AI
    lead = Lead(
        customer_id=customer.id,
        project_id=project.id,
        preferred_config="2BHK",
        budget_min=Decimal("450000.00"),
        budget_max=Decimal("600000.00"),
        lead_priority="high",
        qualification_status="budget_matched",
        notes="Interested in mountain views and parking.",
    )
    db_session.add(lead)

    # Site visit booking
    visit_time = datetime.now(timezone.utc) + timedelta(days=2)
    visit = SiteVisit(
        customer_id=customer.id,
        project_id=project.id,
        scheduled_start=visit_time,
        scheduled_end=visit_time + timedelta(hours=1),
        status="scheduled",
        assigned_agent_name="Agent John Miller",
    )
    db_session.add(visit)
    db_session.commit()

    # Verify query
    visits_res = db_session.execute(
        select(SiteVisit).where(SiteVisit.customer_id == customer.id)
    )
    loaded_visit = visits_res.scalar_one()
    assert loaded_visit.project_id == project.id
    assert loaded_visit.status == "scheduled"
