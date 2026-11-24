import io
import uuid
import pytest
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.company import Company
from app.models.user import User
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.schemas.dataset import DatasetApprovalRequest
from app.schemas.agent_tools import QueryBusinessDatasetToolInput
from app.services.dataset.manager import (
    upload_and_import_dataset,
    approve_dataset_schema,
    activate_dataset,
    get_active_dataset,
)
from app.services.dataset.retrieval import query_universal_dataset, query_dynamic_dataset
from app.services.agent.dispatcher import dispatch_agent_tool
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.mock_driver import MockVoiceDriver


@pytest.fixture
def db_session():
    # SQLite in-memory database for bounded, safe, isolated unit testing
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
# FIXTURES: Cross-Domain Datasets (Real Estate, Automobile, Electronics)
# ---------------------------------------------------------------------------
@pytest.fixture
def setup_tenants_and_datasets(db_session):
    # Company A: Real Estate
    comp_re = Company(id=uuid.uuid4(), name="Azure Realty LLC")
    # Company B: Automobile
    comp_auto = Company(id=uuid.uuid4(), name="AutoNation Global")
    # Company C: Electronics
    comp_elec = Company(id=uuid.uuid4(), name="CyberTech Electronics")
    db_session.add_all([comp_re, comp_auto, comp_elec])
    db_session.commit()

    # 1. Dataset A — Real Estate
    re_data = [
        {"Project": "Azure Heights", "BHK": "3 BHK", "Area_SqFt": 1850, "Price_INR": 12500000, "City": "Chennai", "Status": "Ready"},
        {"Project": "Green Valley", "BHK": "2 BHK", "Area_SqFt": 1150, "Price_INR": 8200000, "City": "Bangalore", "Status": "Under Construction"},
        {"Project": "Marina Bay", "BHK": "4 BHK", "Area_SqFt": 2800, "Price_INR": 24000000, "City": "Chennai", "Status": "Ready"},
    ]
    ds_re = upload_and_import_dataset(db_session, create_csv_bytes(re_data), "real_estate.csv", company_id=comp_re.id)
    approve_dataset_schema(
        db_session,
        ds_re.id,
        comp_re.id,
        DatasetApprovalRequest(
            approved_fields=["Project", "BHK", "Area_SqFt", "Price_INR", "City", "Status"],
            display_identifier="Project",
            domain_name="Real Estate Properties",
            welcome_greeting="Welcome to Azure Realty. Looking to buy or lease luxury properties?",
            field_labels={"Price_INR": "Price in INR", "Area_SqFt": "Carpet Area"},
        ),
    )
    activate_dataset(db_session, ds_re.id, comp_re.id)

    # 2. Dataset B — Automobile (with confidential unapproved columns)
    auto_data = [
        {"VIN": "1HGCR2F83HA001", "Make": "Honda", "Model": "Accord Hybrid", "Year": 2021, "Mileage_Miles": 24500, "Fuel_Type": "Hybrid", "Price_USD": 26500, "Dealer_Margin": 4200, "Confidential_Note": "Internal clearance"},
        {"VIN": "4T1B11HK5JU002", "Make": "Toyota", "Model": "Camry SE", "Year": 2022, "Mileage_Miles": 18200, "Fuel_Type": "Gasoline", "Price_USD": 28900, "Dealer_Margin": 5100, "Confidential_Note": "Trade-in"},
        {"VIN": "5YJSA1E21HF003", "Make": "Tesla", "Model": "Model S Plaid", "Year": 2023, "Mileage_Miles": 9500, "Fuel_Type": "Electric", "Price_USD": 74500, "Dealer_Margin": 11000, "Confidential_Note": "VIP customer"},
    ]
    ds_auto = upload_and_import_dataset(db_session, create_csv_bytes(auto_data), "vehicles.csv", company_id=comp_auto.id)
    approve_dataset_schema(
        db_session,
        ds_auto.id,
        comp_auto.id,
        DatasetApprovalRequest(
            approved_fields=["VIN", "Make", "Model", "Year", "Mileage_Miles", "Fuel_Type", "Price_USD"],
            display_identifier="Model",
            domain_name="Vehicle Inventory",
            welcome_greeting="Welcome to AutoNation. How may I help you find your next vehicle?",
            field_labels={"Price_USD": "Selling Price", "Mileage_Miles": "Odometer Miles"},
        ),
    )
    activate_dataset(db_session, ds_auto.id, comp_auto.id)

    # 3. Dataset C — Electronics (arbitrary unfamiliar tech columns + confidential supplier cost)
    elec_data = [
        {"SKU": "APP-M3-PRO", "Product_Name": "MacBook Pro 16", "Category": "Laptops", "Chipset_Arch": "ARM 3nm", "RAM_GB": 36, "Warranty_Months": 24, "Stock_Count": 15, "Price_USD": 2499, "Supplier_Cost": 1850},
        {"SKU": "DELL-XPS-15", "Product_Name": "Dell XPS 15", "Category": "Laptops", "Chipset_Arch": "x86 Intel", "RAM_GB": 32, "Warranty_Months": 12, "Stock_Count": 8, "Price_USD": 1999, "Supplier_Cost": 1450},
        {"SKU": "SNY-WH1000", "Product_Name": "Sony WH-1000XM5", "Category": "Audio", "Chipset_Arch": "V1 Processor", "RAM_GB": 1, "Warranty_Months": 12, "Stock_Count": 45, "Price_USD": 399, "Supplier_Cost": 220},
    ]
    ds_elec = upload_and_import_dataset(db_session, create_csv_bytes(elec_data), "products.csv", company_id=comp_elec.id)
    approve_dataset_schema(
        db_session,
        ds_elec.id,
        comp_elec.id,
        DatasetApprovalRequest(
            approved_fields=["SKU", "Product_Name", "Category", "Chipset_Arch", "RAM_GB", "Warranty_Months", "Stock_Count", "Price_USD"],
            display_identifier="Product_Name",
            domain_name="Consumer Electronics",
            welcome_greeting="Welcome to CyberTech. Looking for enterprise laptops or audio gear?",
            field_labels={"Price_USD": "Retail Price", "Stock_Count": "Units In Stock"},
        ),
    )
    activate_dataset(db_session, ds_elec.id, comp_elec.id)

    return {
        "comp_re": comp_re,
        "comp_auto": comp_auto,
        "comp_elec": comp_elec,
        "ds_re": ds_re,
        "ds_auto": ds_auto,
        "ds_elec": ds_elec,
    }


# ---------------------------------------------------------------------------
# TEST 1: Domain-Neutral Query Engine Independence Across All 3 Domains
# ---------------------------------------------------------------------------
def test_cross_domain_query_engine_independence(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Query Real Estate (Company A)
    res_re = query_universal_dataset(db_session, query_text="Marina Bay Chennai", company_id=ctx["comp_re"].id)
    assert res_re["found"] is True
    assert res_re["domain_name"] == "Real Estate Properties"
    assert res_re["records"][0]["display_identifier"] == "Marina Bay"
    assert "24000000" in res_re["records"][0]["voice_summary"] or "24000000" in str(res_re["records"][0]["raw_attributes"])

    # Query Automobile (Company B)
    res_auto = query_universal_dataset(db_session, query_text="Tesla Model S", company_id=ctx["comp_auto"].id)
    assert res_auto["found"] is True
    assert res_auto["domain_name"] == "Vehicle Inventory"
    assert res_auto["records"][0]["display_identifier"] == "Model S Plaid"
    assert res_auto["records"][0]["raw_attributes"]["Fuel_Type"] == "Electric"

    # Query Electronics (Company C)
    res_elec = query_universal_dataset(db_session, query_text="Sony headphones audio", company_id=ctx["comp_elec"].id)
    assert res_elec["found"] is True
    assert res_elec["domain_name"] == "Consumer Electronics"
    assert res_elec["records"][0]["display_identifier"] == "Sony WH-1000XM5"
    assert res_elec["records"][0]["raw_attributes"]["Category"] == "Audio"


# ---------------------------------------------------------------------------
# TEST 2: Arbitrary Unfamiliar Column Names
# ---------------------------------------------------------------------------
def test_arbitrary_unfamiliar_columns(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets
    # Query unfamiliar hardware columns (Chipset_Arch, RAM_GB)
    res = query_universal_dataset(
        db_session,
        filters={"Chipset_Arch": "ARM 3nm", "RAM_GB": 36},
        company_id=ctx["comp_elec"].id
    )
    assert res["found"] is True
    assert len(res["records"]) == 1
    top = res["records"][0]
    assert top["raw_attributes"]["SKU"] == "APP-M3-PRO"
    assert str(top["raw_attributes"]["RAM_GB"]) == "36"


# ---------------------------------------------------------------------------
# TEST 3: Multi-Condition Filtering (Exact & Partial)
# ---------------------------------------------------------------------------
def test_multi_condition_filtering(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets
    # Automobile: Make == 'Toyota', Year >= 2022
    res = query_universal_dataset(
        db_session,
        filters={"Make": "Toyota", "Year": {">=": 2022}},
        company_id=ctx["comp_auto"].id
    )
    assert res["found"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["raw_attributes"]["Model"] == "Camry SE"


# ---------------------------------------------------------------------------
# TEST 4: Numeric Comparisons & Ranges (<, <=, >, >=, between)
# ---------------------------------------------------------------------------
def test_numeric_comparisons_and_ranges(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # 1. Price <= 27000 (Honda Accord $26500 matches, Camry $28900 & Tesla $74500 excluded)
    res_lte = query_universal_dataset(
        db_session,
        filters={"Price_USD": {"<=": 27000}},
        company_id=ctx["comp_auto"].id
    )
    assert res_lte["found"] is True
    assert len(res_lte["records"]) == 1
    assert res_lte["records"][0]["raw_attributes"]["Model"] == "Accord Hybrid"

    # 2. Mileage between 15000 and 20000 (Camry: 18200)
    res_between = query_universal_dataset(
        db_session,
        filters={"Mileage_Miles": {"between": [15000, 20000]}},
        company_id=ctx["comp_auto"].id
    )
    assert res_between["found"] is True
    assert len(res_between["records"]) == 1
    assert res_between["records"][0]["raw_attributes"]["Model"] == "Camry SE"


# ---------------------------------------------------------------------------
# TEST 5: Counting Matching Records
# ---------------------------------------------------------------------------
def test_counting_matching_records(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Count laptops in electronics
    res = query_universal_dataset(
        db_session,
        filters={"Category": "Laptops"},
        intent="count",
        company_id=ctx["comp_elec"].id
    )
    assert res["found"] is True
    assert res["total_matches"] == 2
    assert res["aggregation"]["operation"] == "count"
    assert res["aggregation"]["value"] == 2
    assert "2 matching Consumer Electronics records" in res["voice_grounding"]


# ---------------------------------------------------------------------------
# TEST 6: Sorting by Approved Fields (Ascending & Descending)
# ---------------------------------------------------------------------------
def test_sorting_by_approved_fields(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Sort Automobile by Price_USD Descending
    res_desc = query_universal_dataset(
        db_session,
        sort_by="Price_USD",
        sort_order="desc",
        company_id=ctx["comp_auto"].id
    )
    prices = [int(r["raw_attributes"]["Price_USD"]) for r in res_desc["records"]]
    assert prices == [74500, 28900, 26500]

    # Sort Automobile by Mileage_Miles Ascending
    res_asc = query_universal_dataset(
        db_session,
        sort_by="Mileage_Miles",
        sort_order="asc",
        company_id=ctx["comp_auto"].id
    )
    mileages = [int(r["raw_attributes"]["Mileage_Miles"]) for r in res_asc["records"]]
    assert mileages == [9500, 18200, 24500]


# ---------------------------------------------------------------------------
# TEST 7: Aggregations (Min, Max, Avg, Sum)
# ---------------------------------------------------------------------------
def test_numeric_aggregations(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Calculate average price of laptops
    res_avg = query_universal_dataset(
        db_session,
        filters={"Category": "Laptops"},
        aggregate_field="Price_USD",
        aggregate_op="avg",
        company_id=ctx["comp_elec"].id
    )
    assert res_avg["found"] is True
    assert res_avg["aggregation"]["value"] == 2249.0  # (2499 + 1999) / 2
    assert "2249.0" in res_avg["voice_grounding"]

    # Calculate max RAM in electronics
    res_max = query_universal_dataset(
        db_session,
        aggregate_field="RAM_GB",
        aggregate_op="max",
        company_id=ctx["comp_elec"].id
    )
    assert res_max["found"] is True
    assert res_max["aggregation"]["value"] == 36.0


# ---------------------------------------------------------------------------
# TEST 8: Side-by-Side Record Comparison
# ---------------------------------------------------------------------------
def test_record_comparison(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Compare MacBook Pro and Dell XPS
    res_comp = query_universal_dataset(
        db_session,
        filters={"Category": "Laptops"},
        intent="compare",
        company_id=ctx["comp_elec"].id
    )
    assert res_comp["found"] is True
    assert len(res_comp["records"]) == 2
    assert "Comparing 2 Consumer Electronics" in res_comp["voice_grounding"]
    assert "MacBook Pro 16" in res_comp["voice_grounding"]
    assert "Dell XPS 15" in res_comp["voice_grounding"]


# ---------------------------------------------------------------------------
# TEST 9: Follow-up Questions Using Conversation Context
# ---------------------------------------------------------------------------
def test_follow_up_conversation_context(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # User previously looked at Tesla Model S (record ID 'Model S Plaid')
    # Follow-up: 'What is its fuel type and mileage?'
    res_followup = query_universal_dataset(
        db_session,
        query_text="mileage fuel",
        conversation_context={"selected_record_id": "Model S Plaid"},
        company_id=ctx["comp_auto"].id
    )
    assert res_followup["found"] is True
    assert len(res_followup["records"]) == 1
    assert res_followup["records"][0]["display_identifier"] == "Model S Plaid"
    assert res_followup["records"][0]["raw_attributes"]["Fuel_Type"] == "Electric"
    assert str(res_followup["records"][0]["raw_attributes"]["Mileage_Miles"]) == "9500"


# ---------------------------------------------------------------------------
# TEST 10: Missing Information Handling (Zero Hallucination)
# ---------------------------------------------------------------------------
def test_missing_information_handling(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Query item that doesn't exist in automobile inventory
    res_none = query_universal_dataset(
        db_session,
        query_text="Ferrari F40 Flying Supercar",
        company_id=ctx["comp_auto"].id
    )
    assert res_none["found"] is False
    assert res_none["total_matches"] == 0
    assert "could not find Vehicle Inventory" in res_none["voice_grounding"]


# ---------------------------------------------------------------------------
# TEST 11: Excluded Confidential Fields & Whitelist Enforcement
# ---------------------------------------------------------------------------
def test_confidential_fields_leakage_and_rejection(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # 1. Attempting to filter by unapproved 'Dealer_Margin' or 'Confidential_Note' must raise ValueError
    with pytest.raises(ValueError) as exc1:
        query_universal_dataset(
            db_session,
            filters={"Dealer_Margin": {">": 1000}},
            company_id=ctx["comp_auto"].id
        )
    assert "not permitted" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        query_universal_dataset(
            db_session,
            sort_by="Confidential_Note",
            company_id=ctx["comp_auto"].id
        )
    assert "not in approved fields" in str(exc2.value)

    # 2. Output records must NOT include Dealer_Margin or Confidential_Note
    res = query_universal_dataset(db_session, query_text="Toyota Camry", company_id=ctx["comp_auto"].id)
    assert res["found"] is True
    top_attrs = res["records"][0]["raw_attributes"]
    assert "Dealer_Margin" not in top_attrs
    assert "Confidential_Note" not in top_attrs
    assert "Internal clearance" not in res["voice_grounding"]
    assert "VIP customer" not in res["voice_grounding"]


# ---------------------------------------------------------------------------
# TEST 12: Cross-Tenant Isolation Rejection
# ---------------------------------------------------------------------------
def test_cross_tenant_isolation(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Company B (AutoNation) queries active dataset: gets only cars, never real estate
    res_b = query_universal_dataset(db_session, query_text="Marina Bay", company_id=ctx["comp_auto"].id)
    assert res_b["found"] is False

    # Attempting to query Company A's dataset ID with Company B's tenant ID must fail
    with pytest.raises(ValueError) as exc:
        query_universal_dataset(
            db_session,
            dataset_id=ctx["ds_re"].id,
            company_id=ctx["comp_auto"].id
        )
    assert "Access denied" in str(exc.value)


# ---------------------------------------------------------------------------
# TEST 13: Dataset with Zero Records
# ---------------------------------------------------------------------------
def test_zero_records_dataset(db_session):
    comp_empty = Company(id=uuid.uuid4(), name="Empty Enterprise")
    db_session.add(comp_empty)
    db_session.commit()

    empty_csv = "SKU,Title\n".encode("utf-8")
    # Ingest without rows raises ValueError during inspection
    with pytest.raises(ValueError):
        upload_and_import_dataset(db_session, empty_csv, "empty.csv", company_id=comp_empty.id)


# ---------------------------------------------------------------------------
# TEST 14: Unapproved Dataset Cannot Be Queried (Fail Closed)
# ---------------------------------------------------------------------------
def test_unapproved_dataset_fails_closed(db_session):
    comp_draft = Company(id=uuid.uuid4(), name="Draft Tenant")
    db_session.add(comp_draft)
    db_session.commit()

    csv_data = create_csv_bytes([{"ID": "1", "Desc": "Draft Item"}])
    ds_draft = upload_and_import_dataset(db_session, csv_data, "draft.csv", company_id=comp_draft.id)
    assert ds_draft.status == "pending_approval"

    # Querying unapproved dataset fails closed with ValueError
    with pytest.raises(ValueError) as exc:
        query_universal_dataset(db_session, dataset_id=ds_draft.id, company_id=comp_draft.id)
    assert "pending administrator schema approval" in str(exc.value)


# ---------------------------------------------------------------------------
# TEST 15: Legacy Real Estate Dataset Compatibility
# ---------------------------------------------------------------------------
def test_legacy_real_estate_compatibility(db_session):
    # Simulate legacy dataset with approved_fields=None
    legacy_ds = DynamicDataset(
        id=uuid.uuid4(),
        company_id=None,
        name="Real Estate Master Portfolio v1",
        filename="master.csv",
        file_hash="dummy_hash",
        version=1,
        is_active=True,
        status="active",
        primary_sheet="Sheet1",
        total_rows=1,
        approved_fields=None,  # Legacy unmigrated
        metadata_registry={"worksheets": {"Sheet1": {"columns": [{"column_name": "Project_Name"}]}}},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(legacy_ds)
    db_session.flush()

    rec = DynamicDatasetRecord(
        dataset_id=legacy_ds.id,
        sheet_name="Sheet1",
        row_index=1,
        record_identifier="DLF Camellias",
        raw_data={"Project_Name": "The Camellias", "City": "Gurugram", "BHK": "4 BHK"},
        normalized_search={"_all_tokens": "the camellias gurugram 4 bhk"},
        voice_summary="The Camellias in Gurugram.",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(rec)
    db_session.commit()

    # Query legacy dataset via query_dynamic_dataset
    res_legacy = query_dynamic_dataset(db_session, query_text="Camellias in Gurugram")
    assert res_legacy["found"] is True
    assert res_legacy["total_matches"] == 1
    assert "The Camellias" in res_legacy["records"][0]["voice_summary"]


# ---------------------------------------------------------------------------
# TEST 16: Agent Tool Dispatcher Integration (query_business_dataset)
# ---------------------------------------------------------------------------
def test_agent_dispatcher_universal_tool(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    # Test tool dispatch for Electronics
    tool_resp = dispatch_agent_tool(
        db=db_session,
        tool_name="query_business_dataset",
        raw_arguments={
            "query": "MacBook Pro",
            "filters": {"Category": "Laptops", "Price_USD": {">=": 2000}},
            "company_id": str(ctx["comp_elec"].id),
        }
    )
    assert tool_resp.success is True
    assert tool_resp.data["found"] is True
    assert len(tool_resp.data["records"]) == 1
    assert tool_resp.data["records"][0]["display_identifier"] == "MacBook Pro 16"


# ---------------------------------------------------------------------------
# TEST 17: Dynamic Voice Orchestrator Adaptation (Role & Greeting)
# ---------------------------------------------------------------------------
def test_voice_orchestrator_dynamic_prompt_and_greeting(db_session, setup_tenants_and_datasets):
    ctx = setup_tenants_and_datasets

    mock_driver = MockVoiceDriver()
    orch = VoiceSessionOrchestrator(
        session_id=str(uuid.uuid4()),
        driver=mock_driver,
        db=db_session,
        customer_id=uuid.uuid4(),
    )
    orch.customer_name = "Alex"

    # 1. With Automobile active dataset
    from sqlalchemy import update
    db_session.execute(update(DynamicDataset).values(is_active=False))
    ctx["ds_auto"].is_active = True
    db_session.commit()

    # Orchestrator builds preamble using active dataset
    preamble = orch._build_system_preamble()
    
    assert "Vehicle Inventory" in preamble or "AutoNation" in preamble
    assert "Welcome to AutoNation" in preamble
    assert "query_business_dataset" in preamble
