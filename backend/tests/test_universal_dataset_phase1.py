import io
import uuid
import pytest
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.db.base import Base
from app.models.company import Company
from app.models.user import User
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.services.dataset.inspector import inspect_dataset_workbook
from app.services.dataset.manager import (
    upload_and_import_dataset,
    approve_dataset_schema,
    activate_dataset,
    rollback_dataset,
    get_active_dataset,
)
from app.services.dataset.retrieval import query_dynamic_dataset
from app.schemas.dataset import DatasetApprovalRequest
from app.api.v1.dataset_admin import resolve_tenant_company


@pytest.fixture
def db_session():
    # Use SQLite in-memory database for bounded, safe, isolated unit testing
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def create_csv_bytes(data: list[dict]) -> bytes:
    df = pd.DataFrame(data)
    out = io.BytesIO()
    df.to_csv(out, index=False)
    return out.getvalue()


# ---------------------------------------------------------------------------
# TEST 1: Dynamic column discovery and type detection across domains
# ---------------------------------------------------------------------------
def test_dynamic_column_discovery_cross_domain():
    # Dataset A: Real Estate
    re_data = [
        {"Project_Name": "Azure Heights", "City": "Chennai", "BHK": "3 BHK", "Price_INR": 12000000},
        {"Project_Name": "Green Valley", "City": "Bangalore", "BHK": "2 BHK", "Price_INR": 8500000},
    ]
    re_bytes = create_csv_bytes(re_data)
    re_inspection = inspect_dataset_workbook(re_bytes, "real_estate.csv")
    meta_re = re_inspection["metadata_registry"]
    
    assert meta_re["total_worksheets"] == 1
    primary_sheet_re = meta_re["primary_sheet"]
    sheet_re = meta_re["worksheets"][primary_sheet_re]
    assert sheet_re["total_rows"] == 2
    headers_re = [c["column_name"] for c in sheet_re["columns"]]
    assert "Project_Name" in headers_re
    assert "BHK" in headers_re
    assert "Project_Name" in sheet_re["candidate_identifiers"]

    # Dataset B: Automobile Inventory (Unrelated domain, headers never hardcoded)
    auto_data = [
        {"VIN": "1HGCR2F83HA001", "MAKE": "Honda", "MODEL": "Accord", "YEAR": 2021, "FUEL_TYPE": "Hybrid", "ODOMETER": 25000, "PRICE_USD": 26500, "DEALER_COST": 22000, "CONFIDENTIAL_NOTE": "Margin: 4500"},
        {"VIN": "4T1B11HK5JU002", "MAKE": "Toyota", "MODEL": "Camry", "YEAR": 2022, "FUEL_TYPE": "Gasoline", "ODOMETER": 18000, "PRICE_USD": 28000, "DEALER_COST": 23500, "CONFIDENTIAL_NOTE": "Trade-in special"},
    ]
    auto_bytes = create_csv_bytes(auto_data)
    auto_inspection = inspect_dataset_workbook(auto_bytes, "inventory_cars.csv")
    meta_auto = auto_inspection["metadata_registry"]
    
    primary_sheet_auto = meta_auto["primary_sheet"]
    sheet_auto = meta_auto["worksheets"][primary_sheet_auto]
    assert sheet_auto["total_rows"] == 2
    headers_auto = [c["column_name"] for c in sheet_auto["columns"]]
    assert set(headers_auto) == {"VIN", "MAKE", "MODEL", "YEAR", "FUEL_TYPE", "ODOMETER", "PRICE_USD", "DEALER_COST", "CONFIDENTIAL_NOTE"}
    # Candidate identifiers should detect VIN or MODEL (unique strings)
    assert any(col in sheet_auto["candidate_identifiers"] for col in ["VIN", "MODEL"])


# ---------------------------------------------------------------------------
# TEST 2 & 3: Admin Approval, Whitelisting, and Data Leakage Prevention
# ---------------------------------------------------------------------------
def test_approval_contract_and_data_leakage_prevention(db_session):
    company = Company(id=uuid.uuid4(), name="AutoNation Corp")
    db_session.add(company)
    db_session.commit()

    auto_data = [
        {"VIN": "1HGCR2F83HA001", "MAKE": "Honda", "MODEL": "Accord Hybrid", "YEAR": 2021, "PRICE_USD": 26500, "DEALER_COST": 22000, "CONFIDENTIAL_NOTE": "Internal margin $4500"},
        {"VIN": "4T1B11HK5JU002", "MAKE": "Toyota", "MODEL": "Camry SE", "YEAR": 2022, "PRICE_USD": 28000, "DEALER_COST": 23500, "CONFIDENTIAL_NOTE": "Wholesale buy"},
    ]
    raw_bytes = create_csv_bytes(auto_data)

    # Ingestion phase (Pending approval)
    ds = upload_and_import_dataset(
        db=db_session,
        file_bytes=raw_bytes,
        filename="vehicles.csv",
        company_id=company.id,
    )
    assert ds.status == "pending_approval"
    assert ds.is_active is False

    # Approval phase: Explicit whitelist. DEALER_COST and CONFIDENTIAL_NOTE are NOT approved!
    approval_req = DatasetApprovalRequest(
        approved_fields=["MAKE", "MODEL", "YEAR", "PRICE_USD"],
        display_identifier="MODEL",
        domain_name="Automobile Inventory",
        welcome_greeting="Hello! Welcome to AutoNation. How can I help you choose your next car?",
        field_labels={"PRICE_USD": "Selling Price"},
    )
    approved_ds = approve_dataset_schema(
        db=db_session,
        dataset_id=ds.id,
        company_id=company.id,
        approval=approval_req,
    )
    assert approved_ds.status == "approved"
    assert approved_ds.approved_fields == ["MAKE", "MODEL", "YEAR", "PRICE_USD"]
    assert approved_ds.display_identifier == "MODEL"

    # Verify DynamicDatasetRecord search tokens and voice summaries omit unapproved fields
    records = db_session.query(DynamicDatasetRecord).filter_by(dataset_id=ds.id).all()
    for rec in records:
        # Search index must not contain internal secrets
        assert "DEALER_COST" not in rec.normalized_search
        assert "CONFIDENTIAL_NOTE" not in rec.normalized_search
        assert "Internal margin" not in rec.normalized_search
        assert "Wholesale buy" not in rec.normalized_search
        assert "Selling Price" in rec.voice_summary or "26500" in rec.voice_summary or "28000" in rec.voice_summary

    # Activate dataset
    activate_dataset(db=db_session, dataset_id=ds.id, company_id=company.id)

    # Retrieval query: Verify raw_attributes returned to AI strictly filters out unapproved fields
    search_res = query_dynamic_dataset(db_session, query_text="Toyota Camry", dataset_id=ds.id)
    assert len(search_res["records"]) > 0
    top_match = search_res["records"][0]
    raw_attrs = top_match["raw_attributes"]
    
    assert "MODEL" in raw_attrs
    assert "PRICE_USD" in raw_attrs
    # Crucial security check: unapproved fields MUST NOT be returned in search results
    assert "DEALER_COST" not in raw_attrs
    assert "CONFIDENTIAL_NOTE" not in raw_attrs


# ---------------------------------------------------------------------------
# TEST 4: Multi-Tenant Isolation & Role Authorization
# ---------------------------------------------------------------------------
def test_tenant_isolation_and_spoof_prevention(db_session):
    company_a = Company(id=uuid.uuid4(), name="Company A")
    company_b = Company(id=uuid.uuid4(), name="Company B")
    db_session.add_all([company_a, company_b])
    db_session.commit()

    admin_a = User(
        id=uuid.uuid4(),
        email="admin@comp-a.com",
        hashed_password="pw",
        role="admin",
        company_id=company_a.id,
        is_active=True,
    )
    admin_b = User(
        id=uuid.uuid4(),
        email="admin@comp-b.com",
        hashed_password="pw",
        role="admin",
        company_id=company_b.id,
        is_active=True,
    )
    super_owner = User(
        id=uuid.uuid4(),
        email="super@platform.com",
        hashed_password="pw",
        role="super_owner",
        is_active=True,
    )
    db_session.add_all([admin_a, admin_b, super_owner])
    db_session.commit()

    # Admin A attempts to resolve tenant: returns company_a.id
    resolved_a = resolve_tenant_company(admin_a, db=db_session, requested_company_id=None)
    assert resolved_a == company_a.id

    # Admin A attempts to pass company_b.id: MUST raise 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        resolve_tenant_company(admin_a, db=db_session, requested_company_id=company_b.id)
    assert exc_info.value.status_code == 403

    # Super Owner can resolve requested company
    resolved_super = resolve_tenant_company(super_owner, db=db_session, requested_company_id=company_b.id)
    assert resolved_super == company_b.id


# ---------------------------------------------------------------------------
# TEST 5: Independent Activation Across Companies
# ---------------------------------------------------------------------------
def test_independent_activation_across_tenants(db_session):
    comp_a = Company(id=uuid.uuid4(), name="Tenant Alpha")
    comp_b = Company(id=uuid.uuid4(), name="Tenant Beta")
    db_session.add_all([comp_a, comp_b])
    db_session.commit()

    data = [{"Item": "Widget 1", "Qty": 10}]
    raw_bytes = create_csv_bytes(data)

    # Ingest and approve for Tenant Alpha
    ds_alpha = upload_and_import_dataset(
        db=db_session, file_bytes=raw_bytes, filename="alpha.csv", company_id=comp_a.id
    )
    approve_dataset_schema(
        db=db_session,
        dataset_id=ds_alpha.id,
        company_id=comp_a.id,
        approval=DatasetApprovalRequest(approved_fields=["Item", "Qty"], display_identifier="Item"),
    )
    activate_dataset(db=db_session, dataset_id=ds_alpha.id, company_id=comp_a.id)

    # Ingest and approve for Tenant Beta
    ds_beta = upload_and_import_dataset(
        db=db_session, file_bytes=raw_bytes, filename="beta.csv", company_id=comp_b.id
    )
    approve_dataset_schema(
        db=db_session,
        dataset_id=ds_beta.id,
        company_id=comp_b.id,
        approval=DatasetApprovalRequest(approved_fields=["Item", "Qty"], display_identifier="Item"),
    )
    activate_dataset(db=db_session, dataset_id=ds_beta.id, company_id=comp_b.id)

    # Verify both are active independently
    active_alpha = get_active_dataset(db=db_session, company_id=comp_a.id)
    active_beta = get_active_dataset(db=db_session, company_id=comp_b.id)
    assert active_alpha.id == ds_alpha.id
    assert active_beta.id == ds_beta.id

    # Tenant Alpha activates a new version v2
    ds_alpha_v2 = upload_and_import_dataset(
        db=db_session, file_bytes=raw_bytes, filename="alpha_v2.csv", company_id=comp_a.id
    )
    approve_dataset_schema(
        db=db_session,
        dataset_id=ds_alpha_v2.id,
        company_id=comp_a.id,
        approval=DatasetApprovalRequest(approved_fields=["Item", "Qty"], display_identifier="Item"),
    )
    activate_dataset(db=db_session, dataset_id=ds_alpha_v2.id, company_id=comp_a.id)

    # Alpha's active dataset changed to v2
    assert get_active_dataset(db=db_session, company_id=comp_a.id).id == ds_alpha_v2.id
    # Beta's active dataset MUST STILL BE ACTIVE and unchanged!
    assert get_active_dataset(db=db_session, company_id=comp_b.id).id == ds_beta.id


# ---------------------------------------------------------------------------
# TEST 6: Rejection of Unapproved Activation
# ---------------------------------------------------------------------------
def test_unapproved_activation_rejected(db_session):
    comp = Company(id=uuid.uuid4(), name="Tenant Gamma")
    db_session.add(comp)
    db_session.commit()

    data = [{"Code": "C100", "Title": "Gadget"}]
    raw_bytes = create_csv_bytes(data)

    ds = upload_and_import_dataset(
        db=db_session, file_bytes=raw_bytes, filename="gamma.csv", company_id=comp.id
    )
    assert ds.status == "pending_approval"

    # Activating without approval must fail closed
    with pytest.raises(ValueError) as exc:
        activate_dataset(db=db_session, dataset_id=ds.id, company_id=comp.id)
    assert "approved" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# TEST 7: Tenant-Scoped Rollback
# ---------------------------------------------------------------------------
def test_tenant_scoped_rollback(db_session):
    comp = Company(id=uuid.uuid4(), name="Tenant Delta")
    db_session.add(comp)
    db_session.commit()

    data = [{"SKU": "SKU-001", "Name": "Appliance"}]
    raw_bytes = create_csv_bytes(data)

    # v1
    v1 = upload_and_import_dataset(
        db=db_session, file_bytes=raw_bytes, filename="delta.csv", company_id=comp.id
    )
    approve_dataset_schema(
        db=db_session,
        dataset_id=v1.id,
        company_id=comp.id,
        approval=DatasetApprovalRequest(approved_fields=["SKU", "Name"], display_identifier="SKU"),
    )
    activate_dataset(db=db_session, dataset_id=v1.id, company_id=comp.id)

    # v2
    v2 = upload_and_import_dataset(
        db=db_session, file_bytes=raw_bytes, filename="delta.csv", company_id=comp.id
    )
    approve_dataset_schema(
        db=db_session,
        dataset_id=v2.id,
        company_id=comp.id,
        approval=DatasetApprovalRequest(approved_fields=["SKU", "Name"], display_identifier="SKU"),
    )
    activate_dataset(db=db_session, dataset_id=v2.id, company_id=comp.id)

    assert get_active_dataset(db=db_session, company_id=comp.id).id == v2.id

    # Rollback to v1
    rolled = rollback_dataset(db=db_session, dataset_id=v2.id, company_id=comp.id)
    assert rolled["status"] == "rolled_back"
    assert rolled["reverted_to"]["id"] == str(v1.id)
    assert get_active_dataset(db=db_session, company_id=comp.id).id == v1.id


# ---------------------------------------------------------------------------
# TEST 8: Verify Customer Registration & Conversations Untouched
# ---------------------------------------------------------------------------
def test_customer_and_conversation_tables_untouched(db_session):
    cust = Customer(
        id=uuid.uuid4(),
        full_name="John Doe",
        phone="+919876543210",
        email="john@example.com",
        is_verified=True,
    )
    db_session.add(cust)
    db_session.commit()

    conv = Conversation(
        id=uuid.uuid4(),
        customer_id=cust.id,
        session_id=str(uuid.uuid4()),
        duration_seconds=120,
        conversation_priority="high",
    )
    db_session.add(conv)
    db_session.commit()

    saved_cust = db_session.query(Customer).filter_by(id=cust.id).first()
    assert saved_cust.full_name == "John Doe"
    assert saved_cust.is_verified is True

    saved_conv = db_session.query(Conversation).filter_by(customer_id=cust.id).first()
    assert saved_conv.conversation_priority == "high"
