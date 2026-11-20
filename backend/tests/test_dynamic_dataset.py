import csv
import io
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.services.dataset.inspector import inspect_dataset_workbook
from app.services.dataset.manager import (
    activate_dataset,
    get_active_dataset,
    rollback_dataset,
    upload_and_import_dataset,
)
from app.services.dataset.retrieval import query_dynamic_dataset
from app.services.agent.dispatcher import dispatch_agent_tool


@pytest.fixture
def memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_schema_inspector_csv():
    csv_content = (
        "UNIT_CODE,PROPERTY_NAME,CITY_ZONE,PRICE_USD,HAS_GOLF_COURSE\n"
        "U_01,Azure Pinnacle,North Seattle,1200000,True\n"
        "U_02,Cascade Heights,East Bellevue,950000,False\n"
        "U_03,Emerald Bay Residences,South Mercer,2100000,True\n"
    ).encode("utf-8")

    res = inspect_dataset_workbook(csv_content, "seattle_properties.csv")
    meta = res["metadata_registry"]
    assert res["primary_sheet"] == "Primary_Dataset"
    assert res["total_rows"] == 3
    columns = meta["worksheets"]["Primary_Dataset"]["columns"]
    col_names = [c["column_name"] for c in columns]
    assert "UNIT_CODE" in col_names
    assert "PROPERTY_NAME" in col_names
    assert "PRICE_USD" in col_names

    # Check candidate identifiers
    candidate_keys = meta["worksheets"]["Primary_Dataset"]["candidate_identifiers"]
    assert "UNIT_CODE" in candidate_keys


def test_dynamic_dataset_upload_preserves_raw_data(memory_db):
    csv_content = (
        "ID,TITLE,METRO,UNITS,PRICE\n"
        "101,Apex Tower,Bengaluru,4 BHK,₹3.5 Cr\n"
        "102,Prestige Serenity,Bengaluru,3 BHK,₹2.1 Cr\n"
    ).encode("utf-8")

    ds = upload_and_import_dataset(
        db=memory_db,
        file_bytes=csv_content,
        filename="bengaluru_luxury.csv",
        auto_activate=True,
        dataset_name="Bengaluru Luxury"
    )

    assert ds.name == "Bengaluru Luxury"
    assert ds.version == 1
    assert ds.is_active is True
    assert ds.total_rows == 2

    records = memory_db.query(DynamicDatasetRecord).filter_by(dataset_id=ds.id).all()
    assert len(records) == 2

    # Verify exact raw preservation (Rule 5)
    r1 = records[0]
    assert r1.raw_data["TITLE"] == "Apex Tower"
    assert r1.raw_data["PRICE"] == "₹3.5 Cr"
    assert r1.normalized_search["title"] == "apex tower"


def test_cross_dataset_isolation_and_rollback(memory_db):
    # Dataset 1: Luxury Residences
    ds1_csv = (
        "RECORD_ID,NAME,CITY\n"
        "REC_01,The Camellias,Gurugram\n"
        "REC_02,The Dahlias,Gurugram\n"
    ).encode("utf-8")
    ds1 = upload_and_import_dataset(
        db=memory_db,
        file_bytes=ds1_csv,
        filename="dlf_portfolio.csv",
        auto_activate=True,
        dataset_name="DLF Portfolio"
    )

    # Dataset 2: Industrial Tech Parks
    ds2_csv = (
        "PARK_ID,FACILITY,REGION\n"
        "IND_01,Silicon Tech Center,San Jose\n"
        "IND_02,Austin Quantum Hub,Austin\n"
    ).encode("utf-8")
    ds2 = upload_and_import_dataset(
        db=memory_db,
        file_bytes=ds2_csv,
        filename="tech_parks.csv",
        auto_activate=True,
        dataset_name="Tech Parks"
    )

    # Dataset 2 is now active
    active = get_active_dataset(memory_db)
    assert active.id == ds2.id

    # Query active dataset (Tech Parks) for Camellias (DLF) -> must NOT leak
    res_leak = query_dynamic_dataset(memory_db, "The Camellias")
    assert res_leak["total_matches"] == 0, "No cross-dataset leakage permitted"

    # Query active dataset (Tech Parks) for Silicon -> matches
    res_tech = query_dynamic_dataset(memory_db, "Silicon Tech Center")
    assert res_tech["total_matches"] > 0
    assert "Silicon Tech Center" in res_tech["records"][0]["voice_summary"]

    # Rollback Dataset 2 -> Reverts cleanly to Dataset 1
    rollback_res = rollback_dataset(memory_db, ds2.id)
    assert rollback_res["status"] == "rolled_back"

    active_after = get_active_dataset(memory_db)
    assert active_after.id == ds1.id
    assert active_after.name == "DLF Portfolio"

    # Now Camellias queries succeed
    res_restored = query_dynamic_dataset(memory_db, "The Camellias")
    assert res_restored["total_matches"] > 0
    assert "The Camellias" in res_restored["records"][0]["voice_summary"]


def test_agent_dispatcher_integration(memory_db):
    csv_content = (
        "RECORD_ID,DEVELOPER,PROJECT_NAME,CITY,CONFIGURATION,AMENITIES\n"
        "RE_01,DLF Limited,The Camellias,Gurugram,4 BHK Residences,Golf Course & Spa\n"
        "RE_02,Godrej Properties,Godrej Aristocrat,Gurugram,3 BHK Luxury,Clubhouse & Pool\n"
    ).encode("utf-8")

    upload_and_import_dataset(
        db=memory_db,
        file_bytes=csv_content,
        filename="master_sheet.csv",
        auto_activate=True,
        dataset_name="Master Sheet"
    )

    # 1. Test query_active_dataset tool dispatch
    resp = dispatch_agent_tool(
        db=memory_db,
        tool_name="query_active_dataset",
        raw_arguments={"query": "DLF Camellias in Gurugram"}
    )
    assert resp.success is True
    assert resp.data["found"] is True
    assert len(resp.data["records"]) > 0
    assert "Camellias" in resp.data["voice_grounding"]

    # 2. Test search_properties tool dispatch fallback
    resp2 = dispatch_agent_tool(
        db=memory_db,
        tool_name="search_properties",
        raw_arguments={"company_name": "Godrej Properties", "city": "Gurugram"}
    )
    assert resp2.success is True
    assert resp2.data["dataset_grounded"] is True
    assert resp2.data["total_exact_matches"] > 0

    # 3. Test anti-hallucination on missing record
    resp_empty = dispatch_agent_tool(
        db=memory_db,
        tool_name="query_active_dataset",
        raw_arguments={"query": "Neptune floating underwater crystal habitat on Jupiter"}
    )
    assert resp_empty.success is True
    assert resp_empty.data["found"] is False
    assert "could not find properties matching" in resp_empty.data["voice_grounding"]
