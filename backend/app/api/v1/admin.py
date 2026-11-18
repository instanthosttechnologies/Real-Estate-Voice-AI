from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.site_visit import SiteVisit
from app.models.user import User
from app.schemas.admin import AdminConversationItem, AdminCustomerItem

router = APIRouter(prefix="/admin", tags=["Admin Portal"])


@router.get("/conversations", response_model=List[AdminConversationItem])
def list_conversation_priority_table(
    priority: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role(["admin", "super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Returns the Conversation Priority Table.
    
    CRITICAL SECURITY & PRIVACY CONTROLS:
    - Transcripts and audio paths are strictly omitted at both the SQL query level and API schema level.
    - Admins can only view operational triage metadata (priority, session ID, duration).
    - Sorted strictly by priority: High -> Medium -> Low -> Urgent, newest first within each priority.
    """
    # Priority rank: Urgent (1) -> High (2) -> Medium (3) -> Low (4)
    priority_order = case(
        (Conversation.conversation_priority == "urgent", 1),
        (Conversation.conversation_priority == "high", 2),
        (Conversation.conversation_priority == "medium", 3),
        (Conversation.conversation_priority == "low", 4),
        else_=5,
    )

    stmt = (
        select(
            Conversation.id,
            Conversation.session_id,
            Conversation.customer_id,
            Customer.full_name.label("customer_name"),
            Conversation.duration_seconds,
            Conversation.conversation_priority,
            Conversation.created_at,
        )
        .outerjoin(Customer, Conversation.customer_id == Customer.id)
    )

    if priority:
        stmt = stmt.where(Conversation.conversation_priority == priority.strip().lower())
    if date_from:
        stmt = stmt.where(Conversation.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Conversation.created_at <= date_to)

    stmt = stmt.order_by(priority_order.asc(), Conversation.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)

    rows = db.execute(stmt).all()
    return [
        AdminConversationItem(
            id=r.id,
            session_id=r.session_id,
            customer_id=r.customer_id,
            customer_name=r.customer_name,
            duration_seconds=r.duration_seconds,
            conversation_priority=r.conversation_priority,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/customers", response_model=List[AdminCustomerItem])
def list_total_customer_details_table(
    search: Optional[str] = None,
    lead_priority: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role(["admin", "super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Returns the Total Customer Details Table with aggregate lead priorities and visit bookings.
    Strictly omits private conversations, audio, and transcript fields.
    """
    stmt = select(Customer).order_by(Customer.created_at.desc())

    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Customer.full_name).like(pattern)
            | func.lower(Customer.email).like(pattern)
            | Customer.phone.like(pattern)
        )

    all_customers = db.execute(stmt).scalars().all()
    result: List[AdminCustomerItem] = []

    for cust in all_customers:
        # Latest lead
        latest_lead = db.execute(
            select(Lead).where(Lead.customer_id == cust.id).order_by(Lead.created_at.desc())
        ).scalars().first()

        # Filter by lead_priority if specified
        if lead_priority:
            current_lead_pri = latest_lead.lead_priority if latest_lead else None
            if current_lead_pri != lead_priority.strip().lower():
                continue

        # Count visits
        visit_count = db.execute(
            select(func.count(SiteVisit.id)).where(SiteVisit.customer_id == cust.id)
        ).scalar() or 0

        result.append(
            AdminCustomerItem(
                id=cust.id,
                full_name=cust.full_name,
                email=cust.email,
                phone=cust.phone,
                lead_priority=latest_lead.lead_priority if latest_lead else None,
                qualification_status=latest_lead.qualification_status if latest_lead else None,
                total_site_visits=visit_count,
                created_at=cust.created_at,
            )
        )

    # Sort results consistently: Urgent -> High -> Medium -> Low, newest first within each priority
    priority_weights = {"urgent": 1, "high": 2, "medium": 3, "low": 4}
    result.sort(
        key=lambda x: (
            priority_weights.get((x.lead_priority or "").lower(), 5),
            -(x.created_at.timestamp() if x.created_at else 0),
        )
    )

    # Slice pagination
    return result[offset : offset + limit]
