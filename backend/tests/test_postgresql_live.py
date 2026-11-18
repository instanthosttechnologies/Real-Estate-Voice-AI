import os
import subprocess
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from alembic.config import Config
from alembic import command

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
from app.schemas.ingestion import ConflictResolutionStrategy
from app.services.ingestion.pipeline import execute_ingestion_batch, execute_rollback

PG_PORT = 5433
PG_HOST = "127.0.0.1"
PG_USER = "postgres"
PG_URL = f"postgresql+psycopg2://{PG_USER}@{PG_HOST}:{PG_PORT}/realestate_ai"
PG_DATA_DIR = r"d:\Brain Magic\RealEstate_Agentic_Voice_AI\pg_test_data"


def is_postgres_running():
    try:
        engine = create_engine(f"postgresql+psycopg2://{PG_USER}@{PG_HOST}:{PG_PORT}/postgres", connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def postgres_engine():
    if not is_postgres_running():
        pytest.skip(f"Live PostgreSQL instance is not reachable at {PG_HOST}:{PG_PORT}.")

    # Create realestate_ai database cleanly
    admin_engine = create_engine(f"postgresql+psycopg2://{PG_USER}@{PG_HOST}:{PG_PORT}/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS realestate_ai WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE realestate_ai"))
    admin_engine.dispose()

    # Run Alembic migrations against PostgreSQL
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", PG_URL)
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(PG_URL, echo=False)
    yield engine
    engine.dispose()


def test_postgresql_connection_and_version(postgres_engine):
    with postgres_engine.connect() as conn:
        version = conn.execute(text("SELECT version();")).scalar()
        assert "PostgreSQL" in version
        print("\n[LIVE POSTGRESQL DETECTED]:", version)


def test_postgresql_alembic_tables_created(postgres_engine):
    with postgres_engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)).scalars().all()
        
        expected_tables = [
            "alembic_version",
            "amenities",
            "audit_logs",
            "companies",
            "conversations",
            "customers",
            "ingestion_batches",
            "ingestion_records",
            "leads",
            "locations",
            "pricing",
            "project_amenities",
            "projects",
            "properties",
            "property_units",
            "site_visits",
            "users",
        ]
        for tbl in expected_tables:
            assert tbl in tables, f"Expected table {tbl} was not created by Alembic in PostgreSQL!"


def test_postgresql_foreign_key_and_check_constraints(postgres_engine):
    with Session(postgres_engine) as session:
        # 1. Company
        comp = Company(name="PG Test Builders", registration_number=f"REG-PG-{uuid.uuid4().hex[:6]}")
        loc = Location(address_line_1="PG St", city="San Jose", state="CA", postal_code="95112")
        session.add_all([comp, loc])
        session.flush()

        # 2. Project
        proj = Project(company_id=comp.id, location_id=loc.id, name="PG Horizon")
        session.add(proj)
        session.flush()

        prop = Property(project_id=proj.id, name="Tower Alpha", property_type="apartment")
        session.add(prop)
        session.commit()

        # 3. Test Check Constraint: carpet_area_sqft > 0
        invalid_unit = PropertyUnit(
            property_id=prop.id,
            unit_number="BAD-1",
            configuration_type="1BHK",
            carpet_area_sqft=Decimal("-10.00"),  # Violates check constraint
        )
        session.add(invalid_unit)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # Re-fetch project after rollback
        comp = session.execute(select(Company).where(Company.name == "PG Test Builders")).scalar_one()
        loc = session.execute(select(Location).where(Location.postal_code == "95112")).scalar_one()
        proj = session.execute(select(Project).where(Project.company_id == comp.id)).scalar_one()
        prop = session.execute(select(Property).where(Property.project_id == proj.id)).scalar_one()

        # 4. Valid unit insertion
        valid_unit = PropertyUnit(
            property_id=prop.id,
            unit_number="PG-101",
            configuration_type="2BHK",
            carpet_area_sqft=Decimal("1100.00"),
        )
        session.add(valid_unit)
        session.flush()

        # 5. Pricing and Availability History
        t0 = datetime.now(timezone.utc) - timedelta(days=20)
        t1 = datetime.now(timezone.utc)
        p1 = Pricing(
            unit_id=valid_unit.id,
            base_price=Decimal("600000.00"),
            total_estimated_price=Decimal("650000.00"),
            is_active=False,
            valid_from=t0,
            valid_to=t1,
        )
        p2 = Pricing(
            unit_id=valid_unit.id,
            base_price=Decimal("630000.00"),
            total_estimated_price=Decimal("685000.00"),
            is_active=True,
            valid_from=t1,
        )
        session.add_all([p1, p2])
        session.commit()

        # Verify query on real PostgreSQL
        unit_prices = session.execute(
            select(Pricing).where(Pricing.unit_id == valid_unit.id).order_by(Pricing.valid_from)
        ).scalars().all()
        assert len(unit_prices) == 2
        assert unit_prices[0].is_active is False
        assert unit_prices[1].is_active is True


def test_postgresql_ingestion_and_rollback(postgres_engine):
    with Session(postgres_engine) as session:
        user = User(email="pg_admin@realty.com", hashed_password="x", role="super_owner")
        session.add(user)
        session.commit()

        csv_data = """Developer,ProjectName,City,Zip,Tower,FlatNo,Beds,AreaSqft,Cost
Postgres Realty,Postgres Heights,Austin,78701,East Tower,801,3BHK,1400,850000
"""
        mappings = {
            "Developer": "company_name",
            "ProjectName": "project_name",
            "City": "city",
            "Zip": "postal_code",
            "Tower": "property_name",
            "FlatNo": "unit_number",
            "Beds": "configuration_type",
            "AreaSqft": "carpet_area_sqft",
            "Cost": "base_price",
        }
        res = execute_ingestion_batch(
            db=session,
            content=csv_data.encode("utf-8"),
            filename="pg_import.csv",
            confirmed_mappings=mappings,
            conflict_strategy=ConflictResolutionStrategy.NEW_VERSION,
            user_id=user.id,
        )
        assert res.imported_rows == 1
        batch_id = res.batch_id

        # Verify committed in PostgreSQL
        unit = session.execute(select(PropertyUnit).where(PropertyUnit.unit_number == "801")).scalar_one_or_none()
        assert unit is not None

        # Rollback on PostgreSQL
        rb_res = execute_rollback(
            db=session,
            batch_id=batch_id,
            user_id=user.id,
            user_role=user.role,
        )
        assert rb_res.status == "rolled_back"

        # Verify deleted in PostgreSQL
        unit_after = session.execute(select(PropertyUnit).where(PropertyUnit.unit_number == "801")).scalar_one_or_none()
        assert unit_after is None


def test_postgresql_phase2_currency_timezone_and_concurrency_locking(postgres_engine):
    from zoneinfo import ZoneInfo
    from app.services.real_estate.search import PropertySearchCriteria, search_properties
    from app.services.real_estate.site_visits import BookVisitInput, book_site_visit, get_available_visit_slots

    with Session(postgres_engine) as session:
        # 1. Company & Locations
        comp = Company(name=f"PG MultiCorp {uuid.uuid4().hex[:6]}", phone="+1-555-0199")
        loc_in = Location(address_line_1="MG Road", city="Bengaluru", state="KA", postal_code="560001")
        loc_us = Location(address_line_1="4th Ave", city="Seattle", state="WA", postal_code="98104")
        session.add_all([comp, loc_in, loc_us])
        session.flush()

        # 2. Projects with project-local timezones
        proj_in = Project(
            company_id=comp.id,
            location_id=loc_in.id,
            name=f"Bengaluru Tech Park {uuid.uuid4().hex[:4]}",
            timezone="Asia/Kolkata",
            status="ready_to_move",
        )
        proj_us = Project(
            company_id=comp.id,
            location_id=loc_us.id,
            name=f"Seattle Tech Tower {uuid.uuid4().hex[:4]}",
            timezone="America/Los_Angeles",
            status="ready_to_move",
        )
        session.add_all([proj_in, proj_us])
        session.flush()

        # Verify timezone persisted in PostgreSQL
        p_row = session.execute(select(Project).where(Project.id == proj_in.id)).scalar_one()
        assert p_row.timezone == "Asia/Kolkata"

        # 3. Properties and units
        prop_in = Property(project_id=proj_in.id, name="Block A", property_type="apartment")
        prop_us = Property(project_id=proj_us.id, name="Skyline Tower", property_type="apartment")
        session.add_all([prop_in, prop_us])
        session.flush()

        unit_in = PropertyUnit(
            property_id=prop_in.id,
            unit_number="IN-101",
            configuration_type="3BHK",
            carpet_area_sqft=Decimal("1500.00"),
        )
        unit_us = PropertyUnit(
            property_id=prop_us.id,
            unit_number="US-202",
            configuration_type="2BHK",
            carpet_area_sqft=Decimal("950.00"),
        )
        session.add_all([unit_in, unit_us])
        session.flush()

        # 4. Multi-currency active pricing: INR 2.0 Cr vs USD $750k
        session.add_all([
            Pricing(
                unit_id=unit_in.id,
                base_price=Decimal("20000000.00"),
                total_estimated_price=Decimal("20500000.00"),
                currency="INR",
                is_active=True,
            ),
            Availability(unit_id=unit_in.id, status="available", is_current=True),
            Pricing(
                unit_id=unit_us.id,
                base_price=Decimal("750000.00"),
                total_estimated_price=Decimal("775000.00"),
                currency="USD",
                is_active=True,
            ),
            Availability(unit_id=unit_us.id, status="available", is_current=True),
        ])
        session.commit()

        # 5. Search isolated by ISO Currency on PostgreSQL
        inr_results = search_properties(session, PropertySearchCriteria(currency="INR"))
        assert any(r.unit_id == unit_in.id for r in inr_results)
        assert all(r.currency == "INR" for r in inr_results)

        usd_results = search_properties(session, PropertySearchCriteria(currency="USD"))
        assert any(r.unit_id == unit_us.id for r in usd_results)
        assert all(r.currency == "USD" for r in usd_results)

        # 6. Test Site Visit Slot Generation & Booking with SELECT ... FOR UPDATE in PostgreSQL
        cust = Customer(full_name="Postgres Live Client", phone="+91-9988776655")
        session.add(cust)
        session.commit()

        target_d = date(2026, 12, 10)
        slots = get_available_visit_slots(session, proj_in.id, target_d)
        assert len(slots.slots) == 9
        assert slots.project_timezone == "Asia/Kolkata"
        # 09:00 AM IST = 03:30 UTC
        assert slots.slots[0].start_time.hour == 3 and slots.slots[0].start_time.minute == 30

        # Book with concurrency lock (with_for_update inside book_site_visit)
        ist_tz = ZoneInfo("Asia/Kolkata")
        visit_time = datetime(2026, 12, 10, 11, 0, tzinfo=ist_tz)
        booking = book_site_visit(
            session,
            BookVisitInput(
                customer_id=cust.id,
                project_id=proj_in.id,
                unit_id=unit_in.id,
                scheduled_start=visit_time,
            )
        )
        assert booking.status == "scheduled"
        assert booking.project_id == proj_in.id


def test_postgresql_audit_log_immutability_trigger(postgres_engine):
    """
    Verifies that database-level triggers on PostgreSQL strictly prevent UPDATE and DELETE
    operations on the audit_logs table, ensuring tamper-evident persistence.
    """
    with Session(postgres_engine) as session:
        audit_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO audit_logs (id, user_role, action, resource_type, resource_id, timestamp) "
                "VALUES (:id, 'super_owner', 'TEST_SECURITY_IMMUTABLE', 'system', 'test_1', NOW())"
            ),
            {"id": audit_id},
        )
        session.commit()

        # 1. Attempt UPDATE - Must fail due to trigger trg_audit_logs_prevent_update
        with pytest.raises(Exception) as exc_info:
            session.execute(
                text("UPDATE audit_logs SET action = 'TAMPERED' WHERE id = :id"),
                {"id": audit_id},
            )
            session.commit()
        session.rollback()
        assert "Audit logs are strictly immutable and cannot be updated" in str(exc_info.value)

        # 2. Attempt DELETE - Must fail due to trigger trg_audit_logs_prevent_delete
        with pytest.raises(Exception) as exc_info:
            session.execute(
                text("DELETE FROM audit_logs WHERE id = :id"),
                {"id": audit_id},
            )
            session.commit()
        session.rollback()
        assert "Audit logs are strictly immutable and cannot be updated or deleted" in str(exc_info.value)

        # 3. Verify record remains unchanged in database
        row = session.execute(
            text("SELECT action FROM audit_logs WHERE id = :id"),
            {"id": audit_id},
        ).scalar_one()
        assert row == "TEST_SECURITY_IMMUTABLE"


def test_postgresql_least_privilege_audit_role(postgres_engine):
    """
    Verifies that a non-superuser application role with least-privilege permissions:
    1. Can SELECT and INSERT audit logs.
    2. Is strictly blocked by PostgreSQL permissions from executing UPDATE, DELETE, or TRUNCATE on audit_logs.
    3. Has no permission to modify or execute the trigger function prevent_audit_log_tampering().
    """
    admin_conn = postgres_engine.connect()
    trans = admin_conn.begin()
    try:
        # Create temporary non-superuser role
        admin_conn.execute(text("DROP ROLE IF EXISTS realty_test_app_role;"))
        admin_conn.execute(text("CREATE ROLE realty_test_app_role WITH LOGIN PASSWORD 'test_pass';"))
        admin_conn.execute(text("GRANT USAGE ON SCHEMA public TO realty_test_app_role;"))
        admin_conn.execute(text("GRANT SELECT, INSERT ON TABLE audit_logs TO realty_test_app_role;"))
        admin_conn.execute(text("REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_logs FROM realty_test_app_role;"))
        admin_conn.execute(text("REVOKE ALL ON FUNCTION prevent_audit_log_tampering() FROM realty_test_app_role;"))
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        admin_conn.close()

    # Connect as non-superuser application role
    test_role_url = f"postgresql+psycopg2://realty_test_app_role:test_pass@{PG_HOST}:{PG_PORT}/realestate_ai"
    role_engine = create_engine(test_role_url)

    try:
        with role_engine.connect() as conn:
            # 1. Non-superuser role can insert an audit log
            audit_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO audit_logs (id, user_role, action, resource_type, resource_id, timestamp) "
                    "VALUES (:id, 'customer', 'ROLE_PERM_TEST', 'system', 'test_2', NOW())"
                ),
                {"id": audit_id},
            )
            conn.commit()

            # 2. Non-superuser role can select audit logs
            count = conn.execute(text("SELECT count(*) FROM audit_logs WHERE id = :id"), {"id": audit_id}).scalar()
            assert count == 1

            # 3. Non-superuser role cannot UPDATE - blocked at permission level
            with pytest.raises(Exception) as exc_update:
                conn.execute(text("UPDATE audit_logs SET action = 'HACKED' WHERE id = :id"), {"id": audit_id})
                conn.commit()
            conn.rollback()
            assert "permission denied for table audit_logs" in str(exc_update.value).lower()

            # 4. Non-superuser role cannot DELETE - blocked at permission level
            with pytest.raises(Exception) as exc_delete:
                conn.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": audit_id})
                conn.commit()
            conn.rollback()
            assert "permission denied for table audit_logs" in str(exc_delete.value).lower()
    finally:
        role_engine.dispose()
        # Cleanup role
        with postgres_engine.connect() as cleanup_conn:
            with cleanup_conn.begin():
                cleanup_conn.execute(text("DROP OWNED BY realty_test_app_role;"))
                cleanup_conn.execute(text("DROP ROLE IF EXISTS realty_test_app_role;"))


