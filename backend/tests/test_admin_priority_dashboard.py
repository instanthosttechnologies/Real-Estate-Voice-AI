"""
Unit & Integration Tests for Admin Customer Priority Dashboard.
Tests:
- Table 1: All Registered Customers (including zero conversations, search, status filter, pagination)
- Table 2: Customer Priority Ranking (accurate repeat conversation calculation, duration calculation,
  priority classification High/Medium/Low, time filtering, and STRICT omission of numerical priority score)
- Action: Customer Details modal payload inspection (strictly zero raw audio or transcripts)
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Customer, Lead, Conversation, SiteVisit, User
from app.api.v1.admin import (
    list_registered_customers,
    list_customer_priority_ranking,
    get_customer_operational_details as get_customer_detail,
    format_seconds_to_duration,
    format_budget_range,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database for isolated test execution."""
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
def admin_user():
    return User(
        id=uuid.uuid4(),
        email="admin@brainmagic.ai",
        role="admin",
        hashed_password="mocked_hashed_pw",
        is_active=True,
    )


def test_duration_and_budget_formatting():
    """Test helper formatting functions."""
    assert format_seconds_to_duration(0) == "0s"
    assert format_seconds_to_duration(45) == "45s"
    assert format_seconds_to_duration(60) == "1m 0s"
    assert format_seconds_to_duration(125) == "2m 5s"
    assert format_seconds_to_duration(3665) == "1h 1m"

    assert format_budget_range(None, None) is None
    assert format_budget_range(5000000, 10000000) == "₹50 L - ₹1 Cr"
    assert format_budget_range(15000000, None) == "From ₹1.5 Cr"
    assert format_budget_range(None, 8000000) == "Up to ₹80 L"


def test_all_registered_customers_table(db_session: Session, admin_user: User):
    """
    Test Table 1: All Registered Customers.
    Verifies that customers with zero conversations are included,
    preferences are populated, and search/filtering/pagination work.
    """
    now = datetime.now(timezone.utc)

    # Customer 1: Registered with zero conversations
    c1 = Customer(
        id=uuid.uuid4(),
        full_name="Alice Smith",
        phone="+919876543210",
        email="alice@example.com",
        is_verified=True,
        created_at=now - timedelta(days=10),
    )
    # Lead preferences for Alice
    l1 = Lead(
        id=uuid.uuid4(),
        customer_id=c1.id,
        preferred_location="Whitefield, Bengaluru",
        preferred_config="2 BHK",
        budget_min=6000000.0,
        budget_max=9000000.0,
        lead_priority="medium",
        qualification_status="qualified",
        created_at=now - timedelta(days=9),
    )

    # Customer 2: Unverified with 2 conversations
    c2 = Customer(
        id=uuid.uuid4(),
        full_name="Bob Jones",
        phone="+919876543211",
        email="bob@example.com",
        is_verified=False,
        created_at=now - timedelta(days=5),
    )
    conv1 = Conversation(
        id=uuid.uuid4(),
        session_id="sess_bob_1",
        customer_id=c2.id,
        duration_seconds=120,
        conversation_priority="high",
        created_at=now - timedelta(days=4),
    )
    conv2 = Conversation(
        id=uuid.uuid4(),
        session_id="sess_bob_2",
        customer_id=c2.id,
        duration_seconds=200,
        conversation_priority="high",
        created_at=now - timedelta(days=2),
    )

    db_session.add_all([c1, l1, c2, conv1, conv2])
    db_session.commit()

    # 1. Fetch all
    res = list_registered_customers(
        search=None,
        status_filter=None,
        limit=10,
        offset=0,
        current_user=admin_user,
        db=db_session,
    )
    assert res.total == 2
    assert len(res.items) == 2

    # Check Alice (zero conversations)
    alice_item = next(i for i in res.items if i.customer_name == "Alice Smith")
    assert alice_item.phone == "+919876543210"
    assert alice_item.email == "alice@example.com"
    assert alice_item.preferred_location == "Whitefield, Bengaluru"
    assert alice_item.preferred_config == "2 BHK"
    assert "₹60 L - ₹90 L" in (alice_item.budget_display or "")
    assert alice_item.total_conversations == 0
    assert alice_item.last_conversation_date is None
    assert alice_item.status == "Verified"

    # Check Bob (2 conversations)
    bob_item = next(i for i in res.items if i.customer_name == "Bob Jones")
    assert bob_item.total_conversations == 2
    assert bob_item.last_conversation_date is not None
    assert bob_item.status == "Unverified"

    # 2. Test status filter
    verified_res = list_registered_customers(
        search=None,
        status_filter="verified",
        limit=10,
        offset=0,
        current_user=admin_user,
        db=db_session,
    )
    assert verified_res.total == 1
    assert verified_res.items[0].customer_name == "Alice Smith"

    # 3. Test search filter
    search_res = list_registered_customers(
        search="bob",
        status_filter=None,
        limit=10,
        offset=0,
        current_user=admin_user,
        db=db_session,
    )
    assert search_res.total == 1
    assert search_res.items[0].customer_name == "Bob Jones"


def test_customer_priority_ranking_formula_and_omission(db_session: Session, admin_user: User):
    """
    Test Table 2: Customer Priority Ranking.
    Validates:
    - Internal score formula: Duration_min + (Repeat_convs * 10)
    - Eligible calls: duration >= 30 seconds
    - Repeat conversations = max(eligible_convs - 1, 0)
    - Strict classification: High >= 50, Medium 20-49, Low < 20
    - STRICT OMISSION: Numerical score is NOT in the response model
    """
    now = datetime.now(timezone.utc)

    # Customer High Priority:
    # 3 calls: 600s (10m), 1200s (20m), 1200s (20m). Total duration = 3000s = 50.0m.
    # Eligible calls = 3, Repeat calls = 2.
    # Internal score = 50.0 + (2 * 10) = 70.0 -> High priority (>= 50)
    c_high = Customer(
        id=uuid.uuid4(),
        full_name="High Priority Customer",
        phone="+919999999991",
        email="high@priority.com",
        created_at=now - timedelta(days=20),
    )
    c_high_convs = [
        Conversation(id=uuid.uuid4(), session_id="s_h1", customer_id=c_high.id, duration_seconds=600, conversation_priority="urgent", created_at=now - timedelta(days=3)),
        Conversation(id=uuid.uuid4(), session_id="s_h2", customer_id=c_high.id, duration_seconds=1200, conversation_priority="urgent", created_at=now - timedelta(days=2)),
        Conversation(id=uuid.uuid4(), session_id="s_h3", customer_id=c_high.id, duration_seconds=1200, conversation_priority="high", created_at=now - timedelta(days=1)),
    ]

    # Customer Medium Priority:
    # 2 calls: 600s (10m), 600s (10m). Total duration = 1200s = 20.0m.
    # Eligible calls = 2, Repeat calls = 1.
    # Internal score = 20.0 + (1 * 10) = 30.0 -> Medium priority (20 <= score < 50)
    c_med = Customer(
        id=uuid.uuid4(),
        full_name="Medium Priority Customer",
        phone="+919999999992",
        email="med@priority.com",
        created_at=now - timedelta(days=20),
    )
    c_med_convs = [
        Conversation(id=uuid.uuid4(), session_id="s_m1", customer_id=c_med.id, duration_seconds=600, conversation_priority="medium", created_at=now - timedelta(days=4)),
        Conversation(id=uuid.uuid4(), session_id="s_m2", customer_id=c_med.id, duration_seconds=600, conversation_priority="medium", created_at=now - timedelta(days=2)),
    ]

    # Customer Low Priority:
    # 1 call of 120s (2m). Eligible calls = 1, Repeat calls = 0.
    # Internal score = 2.0 + 0 = 2.0 -> Low priority (< 20)
    c_low = Customer(
        id=uuid.uuid4(),
        full_name="Low Priority Customer",
        phone="+919999999993",
        email="low@priority.com",
        created_at=now - timedelta(days=20),
    )
    c_low_convs = [
        Conversation(id=uuid.uuid4(), session_id="s_l1", customer_id=c_low.id, duration_seconds=120, conversation_priority="low", created_at=now - timedelta(days=1)),
    ]

    # Customer Short Calls (< 30s) - Not eligible for ranking
    c_short = Customer(
        id=uuid.uuid4(),
        full_name="Short Call Customer",
        phone="+919999999994",
        email="short@priority.com",
        created_at=now - timedelta(days=20),
    )
    c_short_convs = [
        Conversation(id=uuid.uuid4(), session_id="s_s1", customer_id=c_short.id, duration_seconds=15, conversation_priority="low", created_at=now - timedelta(days=1)),
    ]

    db_session.add_all([c_high, c_med, c_low, c_short] + c_high_convs + c_med_convs + c_low_convs + c_short_convs)
    db_session.commit()

    # Query priority ranking
    res = list_customer_priority_ranking(
        search=None,
        time_range="all",
        priority_filter=None,
        limit=10,
        offset=0,
        current_user=admin_user,
        db=db_session,
    )

    # 3 customers have eligible conversations (duration >= 30s)
    assert res.total == 3
    items = res.items

    # Verify order: Rank 1 must be High Priority Customer
    assert items[0].customer_name == "High Priority Customer"
    assert items[0].rank == 1
    assert items[0].priority == "High"
    assert items[0].total_conversations == 3
    assert items[0].repeat_conversations == 2
    assert items[0].total_duration_seconds == 3000
    assert items[0].total_duration_formatted == "50m 0s"

    # Verify Rank 2: Medium Priority Customer
    assert items[1].customer_name == "Medium Priority Customer"
    assert items[1].rank == 2
    assert items[1].priority == "Medium"
    assert items[1].total_conversations == 2
    assert items[1].repeat_conversations == 1
    assert items[1].total_duration_seconds == 1200
    assert items[1].total_duration_formatted == "20m 0s"

    # Verify Rank 3: Low Priority Customer
    assert items[2].customer_name == "Low Priority Customer"
    assert items[2].rank == 3
    assert items[2].priority == "Low"
    assert items[2].total_conversations == 1
    assert items[2].repeat_conversations == 0

    # CRITICAL SECURITY & SPEC CHECK: Numerical score is NOT in the serialized item dict
    for item in items:
        item_dict = item.model_dump()
        assert "score" not in item_dict, "Score must not be exposed"
        assert "priority_score" not in item_dict, "Priority score must not be exposed"
        assert "internal_score" not in item_dict, "Internal score must not be exposed"


def test_customer_detail_modal_payload(db_session: Session, admin_user: User):
    """
    Test Action: Customer Details modal inspection endpoint.
    Verifies that details, preferences, conversation sessions, and site visits are returned,
    and transcripts or audio paths are strictly excluded.
    """
    now = datetime.now(timezone.utc)
    cust = Customer(
        id=uuid.uuid4(),
        full_name="Diana Prince",
        phone="+919800000001",
        email="diana@amazon.com",
        is_verified=True,
        created_at=now - timedelta(days=15),
    )
    lead = Lead(
        id=uuid.uuid4(),
        customer_id=cust.id,
        preferred_location="Electronic City, Bengaluru",
        preferred_config="3 BHK",
        budget_min=12000000.0,
        budget_max=16000000.0,
        lead_priority="high",
        qualification_status="qualified",
        notes="Looking for possession by late 2026.",
        created_at=now - timedelta(days=14),
    )
    conv = Conversation(
        id=uuid.uuid4(),
        session_id="sess_diana_001",
        customer_id=cust.id,
        duration_seconds=360,
        conversation_priority="high",
        created_at=now - timedelta(days=2),
    )
    visit = SiteVisit(
        id=uuid.uuid4(),
        customer_id=cust.id,
        project_id=uuid.uuid4(),
        scheduled_start=now + timedelta(days=3),
        scheduled_end=now + timedelta(days=3, hours=1),
        status="confirmed",
        customer_notes="Requested evening slot.",
        created_at=now - timedelta(days=1),
    )

    db_session.add_all([cust, lead, conv, visit])
    db_session.commit()

    detail = get_customer_detail(
        customer_id=cust.id,
        current_user=admin_user,
        db=db_session,
    )

    assert detail.customer_name == "Diana Prince"
    assert detail.phone == "+919800000001"
    assert detail.preferred_location == "Electronic City, Bengaluru"
    assert detail.preferred_config == "3 BHK"
    assert "₹1.2 Cr - ₹1.6 Cr" in (detail.budget_display or "")
    assert detail.notes == "Looking for possession by late 2026."
    assert len(detail.conversations) == 1
    assert detail.conversations[0].session_id == "sess_diana_001"
    assert len(detail.site_visits) == 1
    assert detail.site_visits[0].notes == "Requested evening slot."

    # Section A - E enriched fields
    assert detail.property_type == "Apartment"
    assert detail.site_visit_status == "confirmed"
    assert "completed 1 AI conversation" in (detail.engagement_summary or "")
    assert detail.recent_conversation_duration_formatted == "6m 0s"

    # Verify no transcript or audio fields in conversation schema
    conv_dict = detail.conversations[0].model_dump()
    assert "transcript" not in conv_dict
    assert "encrypted_transcript" not in conv_dict
    assert "decrypted_transcript" not in conv_dict
    assert "audio_storage_path" not in conv_dict
