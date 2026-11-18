import io
import json
import uuid
from decimal import Decimal
import openpyxl
import pytest
import pymupdf as fitz
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import User, Company, PropertyUnit, Pricing, Availability, IngestionBatch, AuditLog
from app.core.security import hash_password
from app.schemas.ingestion import ConflictResolutionStrategy
from app.services.ingestion.pipeline import (
    generate_preview,
    execute_ingestion_batch,
    execute_rollback,
)


@pytest.fixture
def db_session():
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


@pytest.fixture
def super_owner_user(db_session: Session) -> User:
    user = User(
        email="superowner@realestate.ai",
        hashed_password=hash_password("SuperSecretPass123"),
        role="super_owner",
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_csv_preview_and_mapping():
    csv_data = """Developer,ProjectName,City,Zip,Address,Tower,FlatNo,Beds,AreaSqft,Cost,Status
Skyline Group,Skyline Towers,Seattle,98101,1200 4th Ave,Tower 1,101,2 Bed,1250,750000,available
Skyline Group,Skyline Towers,Seattle,98101,1200 4th Ave,Tower 1,102,3 Bed,1600,950000,available
"""
    content = csv_data.encode("utf-8")
    preview = generate_preview(content, "listings.csv")

    assert preview.file_format == "csv"
    assert preview.total_preview_rows == 2
    assert "Developer" in preview.detected_headers

    # Check mapping proposals
    mapping_dict = {m.source_column: m.target_field for m in preview.suggested_mappings}
    assert mapping_dict["Developer"] == "company_name"
    assert mapping_dict["Cost"] == "base_price"
    assert mapping_dict["Beds"] == "configuration_type"
    assert mapping_dict["City"] == "city"


def test_excel_preview():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "company_name", "project_name", "city", "postal_code",
        "unit_number", "configuration_type", "carpet_area_sqft",
        "base_price", "availability_status"
    ])
    ws.append([
        "Apex Devs", "Apex Vista", "Austin", "78702",
        "A-1", "Studio", 550, 320000, "available"
    ])
    out = io.BytesIO()
    wb.save(out)
    content = out.getvalue()

    preview = generate_preview(content, "properties.xlsx")
    assert preview.file_format == "excel"
    assert preview.total_preview_rows == 1


def test_json_preview():
    data = [
        {
            "company": "Horizon Realty",
            "project": "Horizon Greens",
            "city": "Chicago",
            "zip": "60601",
            "address": "200 N Michigan Ave",
            "unit": "304",
            "layout": "2BHK",
            "sqft": 1100,
            "price": 540000,
            "status": "available"
        }
    ]
    content = json.dumps(data).encode("utf-8")
    preview = generate_preview(content, "feed.json")
    assert preview.file_format == "json"
    assert preview.total_preview_rows == 1


def test_pdf_preview():
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "Property #1:\n"
        "Company: Bayview Homes\n"
        "Project: Marina Cove\n"
        "City: San Francisco\n"
        "PostalCode: 94105\n"
        "Unit: 501\n"
        "Type: 3BHK\n"
        "Area: 1450\n"
        "Price: 1350000\n"
        "Status: available\n"
    )
    page.insert_text((50, 50), text)
    pdf_bytes = doc.tobytes()
    doc.close()

    preview = generate_preview(pdf_bytes, "brochure.pdf")
    assert preview.file_format == "pdf"
    assert preview.total_preview_rows >= 1


def test_full_csv_ingestion_and_provenance(db_session: Session, super_owner_user: User):
    csv_data = """Developer,ProjectName,City,Zip,Address,Tower,FlatNo,Beds,AreaSqft,Cost,Status
Skyline Group,Skyline Towers,Seattle,98101,1200 4th Ave,Tower 1,101,2 Bed,1250,750000,available
Skyline Group,Skyline Towers,Seattle,98101,1200 4th Ave,Tower 1,102,3 Bed,1600,950000,available
"""
    content = csv_data.encode("utf-8")
    mappings = {
        "Developer": "company_name",
        "ProjectName": "project_name",
        "City": "city",
        "Zip": "postal_code",
        "Address": "address_line_1",
        "Tower": "property_name",
        "FlatNo": "unit_number",
        "Beds": "configuration_type",
        "AreaSqft": "carpet_area_sqft",
        "Cost": "base_price",
        "Status": "availability_status",
    }

    result = execute_ingestion_batch(
        db=db_session,
        content=content,
        filename="listings.csv",
        confirmed_mappings=mappings,
        conflict_strategy=ConflictResolutionStrategy.NEW_VERSION,
        user_id=super_owner_user.id,
    )

    assert result.status == "completed"
    assert result.imported_rows == 2
    assert result.failed_rows == 0

    # Verify Company created
    comp = db_session.execute(select(Company).where(Company.name == "Skyline Group")).scalar_one()
    assert comp is not None

    # Verify PropertyUnits created with pricing and availability
    units = db_session.execute(select(PropertyUnit)).scalars().all()
    assert len(units) == 2

    unit101 = [u for u in units if u.unit_number == "101"][0]
    assert unit101.configuration_type == "2BHK"  # Normalized from '2 Bed'
    assert unit101.carpet_area_sqft == Decimal("1250")

    # Verify Pricing
    prices = db_session.execute(select(Pricing).where(Pricing.unit_id == unit101.id)).scalars().all()
    assert len(prices) == 1
    assert prices[0].base_price == Decimal("750000")
    assert prices[0].is_active is True

    # Verify IngestionBatch recorded
    batch = db_session.get(IngestionBatch, result.batch_id)
    assert batch is not None
    assert batch.can_rollback is True


def test_conflict_detection_and_historical_preservation(db_session: Session, super_owner_user: User):
    # Step 1: Initial Ingest
    csv_initial = """Developer,ProjectName,City,Zip,Tower,FlatNo,Beds,AreaSqft,Cost
Metro Corp,Metro Oasis,Dallas,75201,T1,201,1BHK,800,400000
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

    res1 = execute_ingestion_batch(
        db=db_session,
        content=csv_initial.encode("utf-8"),
        filename="batch1.csv",
        confirmed_mappings=mappings,
        conflict_strategy=ConflictResolutionStrategy.NEW_VERSION,
        user_id=super_owner_user.id,
    )
    assert res1.imported_rows == 1

    # Step 2: Ingest conflicting update for unit 201 with price increase to 450,000 and status reserved
    csv_conflict = """Developer,ProjectName,City,Zip,Tower,FlatNo,Beds,AreaSqft,Cost,Status
Metro Corp,Metro Oasis,Dallas,75201,T1,201,1BHK,800,450000,reserved
"""
    mappings["Status"] = "availability_status"

    res2 = execute_ingestion_batch(
        db=db_session,
        content=csv_conflict.encode("utf-8"),
        filename="batch2.csv",
        confirmed_mappings=mappings,
        conflict_strategy=ConflictResolutionStrategy.NEW_VERSION,
        user_id=super_owner_user.id,
    )
    assert res2.imported_rows == 1

    # Verify unit 201 now has 2 pricing records (1 historical inactive, 1 active)
    unit = db_session.execute(select(PropertyUnit).where(PropertyUnit.unit_number == "201")).scalar_one()
    prices = db_session.execute(
        select(Pricing).where(Pricing.unit_id == unit.id).order_by(Pricing.valid_from)
    ).scalars().all()

    assert len(prices) == 2
    assert prices[0].base_price == Decimal("400000")
    assert prices[0].is_active is False
    assert prices[1].base_price == Decimal("450000")
    assert prices[1].is_active is True

    # Verify availability history
    avails = db_session.execute(
        select(Availability).where(Availability.unit_id == unit.id).order_by(Availability.valid_from)
    ).scalars().all()
    assert len(avails) == 2
    assert avails[0].status == "available"
    assert avails[0].is_current is False
    assert avails[1].status == "reserved"
    assert avails[1].is_current is True


def test_atomic_rollback(db_session: Session, super_owner_user: User):
    csv_data = """Developer,ProjectName,City,Zip,Tower,FlatNo,Beds,AreaSqft,Cost
Rollback Builders,Undo Tower,Phoenix,85001,Tower R,999,2BHK,1000,500000
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

    result = execute_ingestion_batch(
        db=db_session,
        content=csv_data.encode("utf-8"),
        filename="to_rollback.csv",
        confirmed_mappings=mappings,
        conflict_strategy=ConflictResolutionStrategy.NEW_VERSION,
        user_id=super_owner_user.id,
    )
    assert result.imported_rows == 1

    # Unit exists
    unit = db_session.execute(select(PropertyUnit).where(PropertyUnit.unit_number == "999")).scalar_one_or_none()
    assert unit is not None

    # Execute rollback
    rb_res = execute_rollback(
        db=db_session,
        batch_id=result.batch_id,
        user_id=super_owner_user.id,
        user_role=super_owner_user.role,
    )
    assert rb_res.status == "rolled_back"
    assert rb_res.reverted_records_count > 0

    # Unit should now be deleted
    unit_after = db_session.execute(select(PropertyUnit).where(PropertyUnit.unit_number == "999")).scalar_one_or_none()
    assert unit_after is None

    # Audit log entry exists
    audit = db_session.execute(
        select(AuditLog).where(AuditLog.action == "EXECUTE_INGESTION_ROLLBACK")
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.resource_id == str(result.batch_id)
