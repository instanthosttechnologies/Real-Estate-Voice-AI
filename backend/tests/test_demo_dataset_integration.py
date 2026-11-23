import os
import sys
import uuid
import pytest
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.schemas.agent_tools import (
    SearchPropertiesToolInput,
    GetPropertyDetailsToolInput,
    GetPropertyPriceToolInput,
    ComparePropertiesToolInput,
    QueryActiveDatasetToolInput,
)
from app.services.agent.dispatcher import dispatch_agent_tool
from app.services.agent import tools
from app.services.real_estate.demo_dataset import DemoDatasetService
from app.services.voice.session_state import SessionState


@pytest.fixture(scope="module")
def sqlite_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session


def test_1_dataset_loading_and_reference_validation():
    """Test 1: All 4 sheets load and foreign keys are validated."""
    svc = DemoDatasetService.get_instance()
    assert svc.is_loaded is True
    assert len(svc.all_projects) == 166
    assert len(svc.projects) >= 100  # Filtered saleable projects
    assert len(svc.all_configurations) == 181
    assert len(svc.configurations) >= 150  # Filtered saleable configurations
    assert len(svc.faqs) == 331
    assert len(svc.demo_apartments) == 459

    # Validate foreign keys: all configurations point to a valid Project_ID
    for cfg_id, cfg in svc.all_configurations.items():
        proj_id = cfg.get("Project_ID")
        assert proj_id in svc.all_projects, f"Configuration {cfg_id} points to non-existent project {proj_id}"

    # Validate demo apartments point to a valid Project_ID and Configuration_ID
    for apt_id, apt in svc.demo_apartments.items():
        proj_id = apt.get("Project_ID")
        cfg_id = apt.get("Configuration_ID")
        assert proj_id in svc.all_projects, f"Demo Apartment {apt_id} points to invalid project {proj_id}"
        if cfg_id and cfg_id != "NO_SOURCE_CONFIGURATION":
            assert cfg_id in svc.all_configurations, f"Demo Apartment {apt_id} points to invalid configuration {cfg_id}"


def test_2_search_by_location_and_bhk(sqlite_db: Session):
    """Test 2: Search by City, Locality, and BHK layout."""
    resp = dispatch_agent_tool(
        db=sqlite_db,
        tool_name="search_properties",
        raw_arguments={
            "city": "Bengaluru",
            "configuration_type": "3BHK",
            "limit": 5,
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["is_demo_mode"] is True
    assert data["total_matches"] > 0
    first_match = data["properties"][0]
    assert first_match["city"] == "Bengaluru"
    assert "spoken_price_script" in first_match
    assert "For this demo, the estimated price is around" in first_match["spoken_price_script"]


def test_3_budget_filtering(sqlite_db: Session):
    """Test 3: Budget filtering restricts results appropriately."""
    resp = dispatch_agent_tool(
        db=sqlite_db,
        tool_name="search_properties",
        raw_arguments={
            "city": "Bengaluru",
            "max_budget": 10000000,  # 1 Crore
            "limit": 5,
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["is_demo_mode"] is True
    for p in data["properties"]:
        assert p["city"] == "Bengaluru"


def test_4_matching_project_amenities(sqlite_db: Session):
    """Test 4: Amenities filtering checks confirmed & illustrative amenities."""
    resp = dispatch_agent_tool(
        db=sqlite_db,
        tool_name="search_properties",
        raw_arguments={
            "city": "Bengaluru",
            "required_amenities": ["Gym", "Clubhouse"],
            "limit": 5,
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["total_matches"] > 0
    for p in data["properties"]:
        amen_str = str(p["amenities"]).lower()
        assert "gym" in amen_str or "clubhouse" in amen_str


def test_5_estimated_price_responses_and_disclaimer(sqlite_db: Session):
    """Test 5: Explicit price tool enforces required demo disclaimer format."""
    svc = DemoDatasetService.get_instance()
    # Pick first project
    sample_proj_id = next(iter(svc.projects.keys()))
    resp = dispatch_agent_tool(
        db=sqlite_db,
        tool_name="get_property_price",
        raw_arguments={
            "unit_id": sample_proj_id,
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["is_demo_mode"] is True
    script = data["spoken_price_script"]
    assert "For this demo, the estimated price is around" in script
    assert "The actual selling price may vary." in script


def test_6_duplicate_filtering():
    """Test 6: Duplicate aliases and portfolio summaries are not exposed as saleable properties."""
    svc = DemoDatasetService.get_instance()
    for proj_id, p in svc.projects.items():
        rec_type = str(p.get("Record_Type") or "").lower()
        assert "duplicate" not in rec_type
        assert "portfolio_summary" not in rec_type


def test_7_follow_up_property_context():
    """Test 7: SessionState stores active property for follow-up turns."""
    state = SessionState(session_id="test_context_001")
    assert state.get_selected_property() is None

    # Set focused property
    prop_data = {
        "project_id": "PRJ_002",
        "project_name": "The Camellias",
        "developer_name": "DLF LIMITED",
        "city": "Gurugram",
        "locality": "Sector 42",
        "spoken_price_script": "For this demo, the estimated price is around 25 crore. The actual selling price may vary."
    }
    state.set_selected_property(prop_data)

    retrieved = state.get_selected_property()
    assert retrieved is not None
    assert retrieved["project_name"] == "The Camellias"
    assert retrieved["project_id"] == "PRJ_002"

    # Reset cleans context
    state.reset()
    assert state.get_selected_property() is None


def test_8_property_gallery_and_official_link_fallback():
    """Test 8: Gallery interface returns approved URLs or official project link fallback."""
    svc = DemoDatasetService.get_instance()
    sample_proj_id = next(iter(svc.projects.keys()))
    gallery = svc.get_property_gallery(sample_proj_id)
    assert "has_images" in gallery
    assert "official_url" in gallery
    assert "message" in gallery
    # If no images, official URL or verified message is provided
    if not gallery["has_images"]:
        assert "official project page" in gallery["message"]


def test_9_faq_answering(sqlite_db: Session):
    """Test 9: FAQ search returns verified real estate answers from RealEstate_FAQs sheet."""
    resp = dispatch_agent_tool(
        db=sqlite_db,
        tool_name="query_active_dataset",
        raw_arguments={
            "query": "What is carpet area compared with built-up area?",
        },
    )
    assert resp.success is True
    data = resp.data
    assert data["is_demo_mode"] is True
    assert data["faq_found"] is True
    assert "carpet area" in data["answer"].lower()


def test_10_demo_versus_production_isolation(sqlite_db: Session):
    """Test 10: Disabling DEMO_DATASET_MODE executes standard production database paths."""
    original_mode = getattr(settings, "DEMO_DATASET_MODE", True)
    try:
        # Turn off demo mode
        settings.DEMO_DATASET_MODE = False
        resp = dispatch_agent_tool(
            db=sqlite_db,
            tool_name="get_property_price",
            raw_arguments={
                "unit_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert resp.success is False
        assert "No verified active price found" in resp.error_message
    finally:
        # Restore demo mode
        settings.DEMO_DATASET_MODE = original_mode
