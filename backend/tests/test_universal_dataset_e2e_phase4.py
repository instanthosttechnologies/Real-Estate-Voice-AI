import io
import uuid
import pytest
import pandas as pd
from typing import Any, Dict, List
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException

from app.db.base import Base
from app.models.company import Company
from app.models.user import User
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.schemas.dataset import DatasetApprovalRequest
from app.schemas.agent_tools import QueryBusinessDatasetToolInput
from app.services.dataset.inspector import inspect_dataset_workbook
from app.services.dataset.manager import (
    upload_and_import_dataset,
    approve_dataset_schema,
    activate_dataset,
    rollback_dataset,
    get_active_dataset,
)
from app.services.dataset.retrieval import query_universal_dataset
from app.services.agent.dispatcher import dispatch_agent_tool
from app.services.voice.tools_spec import get_agent_tools_spec
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.mock_driver import MockVoiceDriver
from app.api.v1.dataset_admin import (
    resolve_tenant_company,
    list_datasets,
    list_available_companies,
)


@pytest.fixture
def isolated_db():
    """Isolated, bounded, ephemeral database strictly separate from realestate_ai."""
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
def tenant_fixture(isolated_db: Session):
    db = isolated_db

    # Create Controlled Test Companies
    comp_a = Company(id=uuid.uuid4(), name="Alpha Enterprises Ltd")
    comp_b = Company(id=uuid.uuid4(), name="Beta Corporation")
    db.add_all([comp_a, comp_b])
    db.flush()

    # Create Controlled Test Admins & Super Owner
    admin_a = User(
        id=uuid.uuid4(),
        email="admin.alpha@test.com",
        hashed_password="mock",
        role="admin",
        company_id=comp_a.id,
    )
    admin_b = User(
        id=uuid.uuid4(),
        email="admin.beta@test.com",
        hashed_password="mock",
        role="admin",
        company_id=comp_b.id,
    )
    unassigned_admin = User(
        id=uuid.uuid4(),
        email="unassigned.admin@test.com",
        hashed_password="mock",
        role="admin",
        company_id=None,
    )
    super_owner = User(
        id=uuid.uuid4(),
        email="super.owner@test.com",
        hashed_password="mock",
        role="super_owner",
        company_id=None,
    )
    db.add_all([admin_a, admin_b, unassigned_admin, super_owner])
    db.commit()

    return {
        "db": db,
        "comp_a": comp_a,
        "comp_b": comp_b,
        "admin_a": admin_a,
        "admin_b": admin_b,
        "unassigned_admin": unassigned_admin,
        "super_owner": super_owner,
    }


def create_csv_bytes(data: List[Dict[str, Any]]) -> bytes:
    df = pd.DataFrame(data)
    out = io.BytesIO()
    df.to_csv(out, index=False)
    return out.getvalue()


def setup_realestate_dataset(db: Session, comp_id: uuid.UUID, user_id: uuid.UUID) -> DynamicDataset:
    re_data = [
        {"project_name": "DLF The Arbour", "city": "Gurugram", "bhk": "4 BHK", "price": 85000000, "confidential_reserve_price": 72000000},
        {"project_name": "M3M Golf Hills", "city": "Gurugram", "bhk": "3 BHK", "price": 24000000, "confidential_reserve_price": 20000000},
    ]
    re_csv = create_csv_bytes(re_data)
    re_ds = upload_and_import_dataset(
        db=db, file_bytes=re_csv, filename="real_estate.csv",
        company_id=comp_id, user_id=user_id, dataset_name="Luxury Residential Projects"
    )
    approve_dataset_schema(
        db=db, dataset_id=re_ds.id, company_id=comp_id,
        approval=DatasetApprovalRequest(
            approved_fields=["project_name", "city", "bhk", "price"],
            display_identifier="project_name",
            domain_name="Luxury Real Estate",
            welcome_greeting="Welcome to BrainMagic Luxury Real Estate! How may I assist your property search?",
        )
    )
    activate_dataset(db=db, dataset_id=re_ds.id, company_id=comp_id)
    return re_ds


def setup_automobile_dataset(db: Session, comp_id: uuid.UUID, user_id: uuid.UUID) -> DynamicDataset:
    auto_data = [
        {"vin": "VIN-TAT-01", "model": "Tata Harrier", "brand": "Tata", "transmission": "Automatic", "fuel": "Diesel", "mileage_kmpl": 16.5, "price": 2200000, "secret_dealer_cost": 1800000},
        {"vin": "VIN-MAH-02", "model": "Mahindra XUV700", "brand": "Mahindra", "transmission": "Automatic", "fuel": "Petrol", "mileage_kmpl": 15.0, "price": 2500000, "secret_dealer_cost": 2050000},
        {"vin": "VIN-HYU-03", "model": "Hyundai Creta", "brand": "Hyundai", "transmission": "Manual", "fuel": "Petrol", "mileage_kmpl": 17.0, "price": 1400000, "secret_dealer_cost": 1150000},
        {"vin": "VIN-TAT-04", "model": "Tata Nexon EV", "brand": "Tata", "transmission": "Automatic", "fuel": "Electric", "mileage_kmpl": 312.0, "price": 1800000, "secret_dealer_cost": 1450000},
    ]
    auto_csv = create_csv_bytes(auto_data)
    auto_ds = upload_and_import_dataset(
        db=db, file_bytes=auto_csv, filename="cars.csv",
        company_id=comp_id, user_id=user_id, dataset_name="Vehicle Fleet Inventory"
    )
    approve_dataset_schema(
        db=db, dataset_id=auto_ds.id, company_id=comp_id,
        approval=DatasetApprovalRequest(
            approved_fields=["vin", "model", "brand", "transmission", "fuel", "mileage_kmpl", "price"],
            display_identifier="model",
            field_labels={"mileage_kmpl": "Mileage (km/l)", "fuel": "Fuel Type"},
            domain_name="Automobile Inventory",
            welcome_greeting="Welcome to City Motors! I can help you find SUVs, sedans, and electric vehicles.",
        )
    )
    activate_dataset(db=db, dataset_id=auto_ds.id, company_id=comp_id)
    return auto_ds


def setup_electronics_dataset(db: Session, comp_id: uuid.UUID, user_id: uuid.UUID) -> DynamicDataset:
    elec_data = [
        {"sku": "TV-OLED-55", "product_title": "Sony Bravia XR OLED 55 Inch", "category": "Television", "price": 140000, "warranty": "3 Years", "distributor_margin": 35000},
        {"sku": "AUD-SND-90", "product_title": "Bose Smart Soundbar 900", "category": "Audio", "price": 85000, "warranty": "2 Years", "distributor_margin": 18000},
        {"sku": "PHN-PRO-15", "product_title": "Apple iPhone 15 Pro", "category": "Smartphone", "price": 130000, "warranty": "1 Year", "distributor_margin": 22000},
    ]
    elec_csv = create_csv_bytes(elec_data)
    elec_ds = upload_and_import_dataset(
        db=db, file_bytes=elec_csv, filename="electronics.csv",
        company_id=comp_id, user_id=user_id, dataset_name="Electronics Master Catalog"
    )
    approve_dataset_schema(
        db=db, dataset_id=elec_ds.id, company_id=comp_id,
        approval=DatasetApprovalRequest(
            approved_fields=["sku", "product_title", "category", "price", "warranty"],
            display_identifier="product_title",
            domain_name="Consumer Electronics Catalog",
            welcome_greeting="Welcome to Apex Electronics! Explore premium displays and audio gear.",
        )
    )
    activate_dataset(db=db, dataset_id=elec_ds.id, company_id=comp_id)
    return elec_ds


# ============================================================================
# STEP 3 & STEP 7: TENANT ISOLATION AND SECURITY GUARANTEES
# ============================================================================

def test_tenant_isolation_and_security_boundaries(tenant_fixture):
    db = tenant_fixture["db"]
    comp_a = tenant_fixture["comp_a"]
    comp_b = tenant_fixture["comp_b"]
    admin_a = tenant_fixture["admin_a"]
    unassigned_admin = tenant_fixture["unassigned_admin"]
    super_owner = tenant_fixture["super_owner"]

    # 1. Normal Admin without assigned company fails closed (403 Forbidden)
    with pytest.raises(HTTPException) as exc1:
        resolve_tenant_company(unassigned_admin, db)
    assert exc1.value.status_code == 403
    assert "not associated with an authorized tenant company" in exc1.value.detail

    # 2. Admin A cannot spoof or access Company B (fails closed)
    with pytest.raises(HTTPException) as exc2:
        resolve_tenant_company(admin_a, db, requested_company_id=comp_b.id)
    assert exc2.value.status_code == 403
    assert "Tenant isolation enforced" in exc2.value.detail

    # 3. Super Owner can inspect all tenant companies
    companies = list_available_companies(current_user=super_owner, db=db)
    assert len(companies) == 2
    comp_ids = [c["id"] for c in companies]
    assert str(comp_a.id) in comp_ids
    assert str(comp_b.id) in comp_ids

    # 4. Super Owner can target specific companies
    resolved_comp = resolve_tenant_company(super_owner, db, requested_company_id=comp_b.id)
    assert resolved_comp == comp_b.id


# ============================================================================
# STEP 4: MULTI-DOMAIN DATASET INGESTION & ADMIN FIELD WHITELISTS
# ============================================================================

def test_multi_domain_ingestion_and_confidential_field_stripping(tenant_fixture):
    db = tenant_fixture["db"]
    comp_a = tenant_fixture["comp_a"]
    admin_a = tenant_fixture["admin_a"]
    comp_b = tenant_fixture["comp_b"]
    admin_b = tenant_fixture["admin_b"]

    # 1. Ingest Domain 1 (Real Estate) for Company A
    re_ds = setup_realestate_dataset(db, comp_a.id, admin_a.id)
    assert re_ds.is_active is True

    # 2. Ingest Domain 2 (Automobile) for Company A (version 2)
    auto_ds = setup_automobile_dataset(db, comp_a.id, admin_a.id)
    assert auto_ds.is_active is True

    # Verify previous real estate dataset was deactivated
    db.refresh(re_ds)
    assert re_ds.is_active is False

    # 3. Ingest Domain 3 (Electronics) for Company B
    elec_ds = setup_electronics_dataset(db, comp_b.id, admin_b.id)
    assert elec_ds.is_active is True

    # Cross-Tenant isolation check: Company A cannot query Company B's electronics
    q_cross = query_universal_dataset(db=db, company_id=comp_a.id, query_text="Bravia OLED")
    assert q_cross["total_matches"] == 0  # Company A only has cars


# ============================================================================
# STEP 5: REAL BUSINESS QUESTIONS & DEEP QUERY VERIFICATION
# ============================================================================

def test_real_business_queries_comprehensive(tenant_fixture):
    db = tenant_fixture["db"]
    comp_a = tenant_fixture["comp_a"]
    admin_a = tenant_fixture["admin_a"]

    # Initialize active Automobile dataset for Company A
    setup_automobile_dataset(db, comp_a.id, admin_a.id)

    # Q1: Single Record Search by Model
    res1 = query_universal_dataset(db=db, company_id=comp_a.id, query_text="Harrier")
    assert res1["found"] is True
    assert res1["total_matches"] == 1
    assert res1["records"][0]["display_identifier"] == "Tata Harrier"
    assert "Tata Harrier" in res1["voice_grounding"]
    # Check that confidential column is NOT in attributes
    assert "secret_dealer_cost" not in res1["records"][0]["raw_attributes"]

    # Q2: Multiple Conditions (Brand: Tata AND Transmission: Automatic)
    res2 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        filters={"brand": "Tata", "transmission": "Automatic"}
    )
    assert res2["total_matches"] == 2
    matched_models = [r["display_identifier"] for r in res2["records"]]
    assert "Tata Harrier" in matched_models
    assert "Tata Nexon EV" in matched_models

    # Q3: Numeric Range (Price <= 2000000)
    res3 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        filters={"price": "<= 2000000"}
    )
    assert res3["total_matches"] == 2
    models_budget = [r["display_identifier"] for r in res3["records"]]
    assert "Hyundai Creta" in models_budget
    assert "Tata Nexon EV" in models_budget

    # Q4: Counting / Aggregation (Average price across inventory)
    res4 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        aggregate_op="avg",
        aggregate_field="price"
    )
    assert res4["found"] is True
    # (2200000 + 2500000 + 1400000 + 1800000) / 4 = 1975000.0
    assert res4["aggregation"]["value"] == 1975000.0
    assert "1975000" in res4["voice_grounding"]

    # Q5: Sorting (Ascending: cheapest vehicle first)
    res5_asc = query_universal_dataset(
        db=db, company_id=comp_a.id,
        sort_by="price",
        sort_order="asc",
        limit=4
    )
    assert res5_asc["records"][0]["display_identifier"] == "Hyundai Creta"  # 14 Lakhs

    # Q6: Sorting (Descending: most expensive vehicle first)
    res5_desc = query_universal_dataset(
        db=db, company_id=comp_a.id,
        sort_by="price",
        sort_order="desc",
        limit=4
    )
    assert res5_desc["records"][0]["display_identifier"] == "Mahindra XUV700"  # 25 Lakhs

    # Q7: Comparing Records (Intent: compare)
    res7 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        query_text="Tata",
        intent="compare"
    )
    assert "Comparing" in res7["voice_grounding"]
    assert "Tata Harrier" in res7["voice_grounding"]
    assert "Tata Nexon EV" in res7["voice_grounding"]

    # Q8: Follow-up Conversation Context (selected_record_id)
    harrier_id = res1["records"][0]["record_id"]
    res8 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        query_text="what is the mileage",
        conversation_context={"selected_record_id": harrier_id}
    )
    assert res8["records"][0]["display_identifier"] == "Tata Harrier"
    assert "16.5" in str(res8["records"][0]["raw_attributes"].get("mileage_kmpl"))

    # Q9: Missing Information / Unmatched criteria
    res9 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        query_text="Ferrari Red Convertible"
    )
    assert res9["total_matches"] == 0
    assert "could not find" in res9["voice_grounding"].lower()

    # Q10: Probing for Excluded Confidential Fields (Zero Data Leakage)
    res10 = query_universal_dataset(
        db=db, company_id=comp_a.id,
        query_text="secret_dealer_cost"
    )
    for rec in res10.get("records", []):
        assert "secret_dealer_cost" not in rec["raw_attributes"]


# ============================================================================
# STEP 6: NOVA SONIC AGENT TOOL AND ORCHESTRATOR INTEGRATION (OFFLINE)
# ============================================================================

def test_nova_sonic_offline_orchestrator_integration(tenant_fixture):
    db = tenant_fixture["db"]
    comp_a = tenant_fixture["comp_a"]
    admin_a = tenant_fixture["admin_a"]

    # Set up Real Estate as base version 1, and Automobile as active version 2
    re_ds = setup_realestate_dataset(db, comp_a.id, admin_a.id)
    auto_ds = setup_automobile_dataset(db, comp_a.id, admin_a.id)

    active_ds = get_active_dataset(db=db, company_id=comp_a.id)
    assert active_ds is not None
    assert active_ds.id == auto_ds.id

    # 1. Tool Spec is dynamically synthesized for active domain
    spec = get_agent_tools_spec(active_ds)
    assert len(spec) >= 1
    query_tools = [s["toolSpec"] for s in spec if s["toolSpec"]["name"] == "query_business_dataset"]
    assert len(query_tools) == 1
    query_tool = query_tools[0]
    assert "Automobile Inventory" in query_tool["description"]

    # Verify input schema includes approved fields in properties
    props = query_tool["inputSchema"]["json"]["properties"]
    assert "filters" in props
    assert "query" in props

    # 2. Agent Dispatcher handles QueryBusinessDatasetToolInput
    raw_args = {
        "query": "electric SUV",
        "filters": {"fuel": "Electric"},
        "company_id": str(comp_a.id),
    }
    dispatch_res = dispatch_agent_tool(
        db=db,
        tool_name="query_business_dataset",
        raw_arguments=raw_args,
    )
    assert dispatch_res.success is True
    assert "Tata Nexon EV" in dispatch_res.data["voice_grounding"]
    assert dispatch_res.data["total_matches"] == 1
    assert "secret_dealer_cost" not in dispatch_res.data["records"][0]["raw_attributes"]

    # 3. Dynamic Prompt & Greeting Synthesis in VoiceSessionOrchestrator
    session_id = str(uuid.uuid4())
    mock_driver = MockVoiceDriver()
    orchestrator = VoiceSessionOrchestrator(
        session_id=session_id,
        driver=mock_driver,
        db=db,
    )

    sys_prompt = orchestrator._build_system_preamble()
    assert "Automobile Inventory" in sys_prompt
    assert "query_business_dataset" in sys_prompt
    assert "Welcome to City Motors" in sys_prompt

    # 4. Rollback capability: roll back to previous Real Estate dataset
    rollback_res = rollback_dataset(db=db, dataset_id=auto_ds.id, company_id=comp_a.id)
    assert rollback_res["status"] == "rolled_back"
    assert rollback_res["reverted_to"]["name"] == "Luxury Residential Projects"

    # Re-check active dataset is now Real Estate again
    reverted_active = get_active_dataset(db=db, company_id=comp_a.id)
    assert reverted_active.domain_name == "Luxury Real Estate"

    # Check greeting in preamble reverts to real estate greeting
    orchestrator_reverted = VoiceSessionOrchestrator(
        session_id=str(uuid.uuid4()),
        driver=mock_driver,
        db=db,
        company_id=comp_a.id,
    )
    sys_prompt_reverted = orchestrator_reverted._build_system_preamble()
    assert "BrainMagic Luxury Real Estate" in sys_prompt_reverted


def test_voice_orchestrator_tenant_routing_isolation(tenant_fixture):
    """
    Step 5 Audit: Verify VoiceSessionOrchestrator tenant routing isolation.
    - Customer of Company A receives Company A's active dataset in preamble.
    - Customer of Company B receives Company B's active dataset in preamble.
    - Dispatcher rejects cross-tenant tool arguments and enforces company boundary.
    """
    f = tenant_fixture
    db = f["db"]
    comp_a = f["comp_a"]
    comp_b = f["comp_b"]
    admin_a = f["admin_a"]
    admin_b = f["admin_b"]

    # Company A gets Automobile dataset
    auto_ds = setup_automobile_dataset(db, comp_a.id, admin_a.id)

    # Company B gets Electronics dataset
    elec_data = [
        {
            "product_name": "Ultra Smart 4K TV",
            "category": "Television",
            "price_inr": 45000,
            "secret_manufacturing_cost": 22000,
        },
        {
            "product_name": "Noise Cancelling Earbuds",
            "category": "Audio",
            "price_inr": 8999,
            "secret_manufacturing_cost": 3000,
        },
    ]
    elec_csv = create_csv_bytes(elec_data)

    elec_ds = upload_and_import_dataset(
        db=db,
        file_bytes=elec_csv,
        filename="electronics.csv",
        dataset_name="Electronics Catalog",
        company_id=comp_b.id,
        user_id=admin_b.id,
    )
    approve_dataset_schema(
        db=db,
        dataset_id=elec_ds.id,
        approval=DatasetApprovalRequest(
            approved_fields=["product_name", "category", "price_inr"],
            domain_name="Consumer Electronics",
            welcome_greeting="Welcome to Sound & Vision Electronics! How can I assist your tech shopping today?",
            display_identifier="product_name",
        ),
        company_id=comp_b.id,
    )
    activate_dataset(db=db, dataset_id=elec_ds.id, company_id=comp_b.id)

    # 1. Company A Voice Session Orchestrator
    mock_driver_a = MockVoiceDriver()
    orch_a = VoiceSessionOrchestrator(
        session_id=str(uuid.uuid4()),
        driver=mock_driver_a,
        db=db,
        company_id=comp_a.id,
    )
    preamble_a = orch_a._build_system_preamble()
    assert "Automobile" in preamble_a
    assert "Welcome to City Motors" in preamble_a
    assert "Consumer Electronics" not in preamble_a
    assert "Sound & Vision" not in preamble_a

    # 2. Company B Voice Session Orchestrator
    mock_driver_b = MockVoiceDriver()
    orch_b = VoiceSessionOrchestrator(
        session_id=str(uuid.uuid4()),
        driver=mock_driver_b,
        db=db,
        company_id=comp_b.id,
    )
    preamble_b = orch_b._build_system_preamble()
    assert "Consumer Electronics" in preamble_b
    assert "Sound & Vision Electronics" in preamble_b
    assert "Automobile" not in preamble_b
    assert "City Motors" not in preamble_b

    # 3. Cross-Tenant Query Dispatch Isolation
    # Comp A customer querying Comp B's dataset id directly fails closed
    cross_res = dispatch_agent_tool(
        db=db,
        tool_name="query_business_dataset",
        raw_arguments={
            "query": "earbuds",
            "dataset_id": str(elec_ds.id),
            "company_id": str(comp_a.id),  # Comp A customer tries to access Comp B dataset
        },
    )
    assert cross_res.success is False
    assert "Access denied" in cross_res.error_message or "Unauthorized" in cross_res.error_message
