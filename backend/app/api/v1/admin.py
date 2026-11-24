from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.site_visit import SiteVisit
from app.models.project import Project
from app.models.user import User
from app.schemas.admin import (
    AdminConversationItem,
    AdminCustomerDetailResponse,
    AdminCustomerItem,
    AdminCustomerPriorityRankingItem,
    AdminCustomerPriorityRankingResponse,
    AdminRegisteredCustomerItem,
    AdminRegisteredCustomersResponse,
    AdminSiteVisitSummary,
)

router = APIRouter(prefix="/admin", tags=["Admin Portal"])


def format_seconds_to_duration(seconds: int) -> str:
    """Formats an integer number of seconds into human-readable duration."""
    if seconds <= 0:
        return "0s"
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}h {mins}m"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def format_budget_range(b_min: Optional[Any], b_max: Optional[Any]) -> Optional[str]:
    """Formats minimum and maximum budget into standard Indian Lakh/Crore currency string."""
    if b_min is None and b_max is None:
        return None

    def _fmt(val: float) -> str:
        if val >= 10000000:
            cr = val / 10000000
            return f"₹{cr:.2f}".rstrip("0").rstrip(".") + " Cr"
        elif val >= 100000:
            lakh = val / 100000
            return f"₹{lakh:.2f}".rstrip("0").rstrip(".") + " L"
        else:
            return f"₹{int(val):,}"

    try:
        f_min = float(b_min) if b_min is not None else None
        f_max = float(b_max) if b_max is not None else None
        if f_min and f_max:
            return f"{_fmt(f_min)} - {_fmt(f_max)}"
        elif f_max:
            return f"Up to {_fmt(f_max)}"
        elif f_min:
            return f"From {_fmt(f_min)}"
    except Exception:
        pass
    return None


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
        latest_lead = db.execute(
            select(Lead).where(Lead.customer_id == cust.id).order_by(Lead.created_at.desc())
        ).scalars().first()

        if lead_priority:
            current_lead_pri = latest_lead.lead_priority if latest_lead else None
            if current_lead_pri != lead_priority.strip().lower():
                continue

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

    priority_weights = {"urgent": 1, "high": 2, "medium": 3, "low": 4}
    result.sort(
        key=lambda x: (
            priority_weights.get((x.lead_priority or "").lower(), 5),
            -(x.created_at.timestamp() if x.created_at else 0),
        )
    )

    return result[offset : offset + limit]


# =============================================================================
# TABLE 1: ALL REGISTERED CUSTOMERS ENDPOINT
# =============================================================================

@router.get("/customers/registered", response_model=AdminRegisteredCustomersResponse)
def list_registered_customers(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
    current_user: User = Depends(require_role(["admin", "super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Returns the All Registered Customers table.
    Includes:
    - Customer ID, Name, Phone, Email
    - Preferred City / Location, Preferred BHK, Budget
    - Registration Date, Total AI Conversations (including 0), Last Conversation Date
    - Status (Verified / Unverified)
    - Filterable by search text and status, paginated.
    """
    stmt = select(Customer)

    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Customer.full_name).like(pattern)
            | func.lower(Customer.email).like(pattern)
            | Customer.phone.like(pattern)
        )

    if status_filter:
        s_lower = status_filter.strip().lower()
        if s_lower == "verified":
            stmt = stmt.where(Customer.is_verified == True)
        elif s_lower == "unverified":
            stmt = stmt.where(Customer.is_verified == False)

    # Order by newest registration first
    stmt = stmt.order_by(Customer.created_at.desc())

    all_matched = db.execute(stmt).scalars().all()
    total_count = len(all_matched)

    paged_customers = all_matched[offset : offset + limit]
    items: List[AdminRegisteredCustomerItem] = []

    for cust in paged_customers:
        # Latest lead for preferences
        latest_lead = db.execute(
            select(Lead).where(Lead.customer_id == cust.id).order_by(Lead.created_at.desc())
        ).scalars().first()

        # Conversation aggregations
        conv_stats = db.execute(
            select(
                func.count(Conversation.id).label("total_convs"),
                func.max(Conversation.created_at).label("last_conv"),
            ).where(Conversation.customer_id == cust.id)
        ).first()

        tot_convs = conv_stats.total_convs if conv_stats else 0
        last_conv_dt = conv_stats.last_conv if conv_stats else None

        b_min = float(latest_lead.budget_min) if latest_lead and latest_lead.budget_min else None
        b_max = float(latest_lead.budget_max) if latest_lead and latest_lead.budget_max else None

        items.append(
            AdminRegisteredCustomerItem(
                customer_id=cust.id,
                customer_name=cust.full_name,
                phone=cust.phone,
                email=cust.email,
                preferred_location=latest_lead.preferred_location if latest_lead else None,
                preferred_config=latest_lead.preferred_config if latest_lead else None,
                budget_display=format_budget_range(b_min, b_max),
                budget_min=b_min,
                budget_max=b_max,
                registration_date=cust.created_at,
                total_conversations=tot_convs,
                last_conversation_date=last_conv_dt,
                is_verified=cust.is_verified,
                status="Verified" if cust.is_verified else "Unverified",
                qualification_status=latest_lead.qualification_status if latest_lead else None,
                lead_priority=latest_lead.lead_priority if latest_lead else None,
            )
        )

    return AdminRegisteredCustomersResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


# =============================================================================
# TABLE 2: CUSTOMER PRIORITY RANKING ENDPOINT
# =============================================================================

@router.get("/customers/priority-ranking", response_model=AdminCustomerPriorityRankingResponse)
def list_customer_priority_ranking(
    time_range: str = Query("all", pattern="^(7d|30d|all)$"),
    search: Optional[str] = None,
    priority: Optional[str] = None,
    priority_filter: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
    current_user: User = Depends(require_role(["admin", "super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Returns the Customer Priority Ranking Table.
    
    Ranking Rules:
    - Evaluates completed voice conversations with valid duration (>= 30 seconds).
    - Repeat Conversations = MAX(Eligible Completed Conversations - 1, 0).
    - Internal Priority Score = Total Eligible Duration in Minutes + (Repeat Conversations * 10).
    - Priority Levels: High (Score >= 50), Medium (20 <= Score < 50), Low (Score < 20).
    - Note: Numerical priority score is intentionally omitted from the response.
    - Sorted descending by engagement score, then total duration, then last conversation date.
    - Ranked sequentially 1, 2, 3...
    - Date filtering supported: 7d (Last 7 days), 30d (Last 30 days), all (All time).
    """
    # 1. Resolve date threshold
    date_threshold: Optional[datetime] = None
    now_utc = datetime.now(timezone.utc)
    if time_range == "7d":
        date_threshold = now_utc - timedelta(days=7)
    elif time_range == "30d":
        date_threshold = now_utc - timedelta(days=30)

    # 2. Query eligible completed conversations (duration_seconds >= 30)
    conv_stmt = select(Conversation).where(Conversation.duration_seconds >= 30)
    if date_threshold:
        conv_stmt = conv_stmt.where(Conversation.created_at >= date_threshold)

    eligible_convs = db.execute(conv_stmt).scalars().all()

    # Group conversations by customer_id
    customer_conv_map: dict[uuid.UUID, List[Conversation]] = {}
    for conv in eligible_convs:
        if conv.customer_id:
            customer_conv_map.setdefault(conv.customer_id, []).append(conv)

    # 3. Fetch all customers involved (or matching search)
    cust_stmt = select(Customer)
    if search:
        pattern = f"%{search.strip().lower()}%"
        cust_stmt = cust_stmt.where(
            func.lower(Customer.full_name).like(pattern) | Customer.phone.like(pattern)
        )

    matched_customers = db.execute(cust_stmt).scalars().all()
    matched_cust_ids = {c.id for c in matched_customers}

    # 4. Calculate internal score and metrics for each active customer
    ranked_candidates = []

    for cust in matched_customers:
        c_list = customer_conv_map.get(cust.id, [])
        # Only rank customers with at least one eligible conversation
        if not c_list:
            continue

        tot_eligible = len(c_list)
        rep_convs = max(tot_eligible - 1, 0)
        tot_dur_sec = sum(c.duration_seconds for c in c_list)
        tot_dur_min = tot_dur_sec / 60.0
        avg_dur_sec = int(tot_dur_sec / tot_eligible) if tot_eligible > 0 else 0
        last_conv_dt = max(c.created_at for c in c_list) if c_list else None

        # Priority calculation formula:
        # Score = Total Eligible Duration in Minutes + (Repeat Conversations * 10)
        score = tot_dur_min + (rep_convs * 10.0)

        # Engagement level categorization:
        # High: Score >= 50, Medium: Score >= 20 and < 50, Low: Score < 20
        if score >= 50.0:
            p_label = "High"
        elif score >= 20.0:
            p_label = "Medium"
        else:
            p_label = "Low"

        # Apply optional priority filter
        target_pri = priority or priority_filter
        if target_pri and p_label.lower() != target_pri.strip().lower():
            continue

        ranked_candidates.append({
            "customer_id": cust.id,
            "customer_name": cust.full_name,
            "phone": cust.phone,
            "email": cust.email,
            "total_conversations": tot_eligible,
            "repeat_conversations": rep_convs,
            "total_duration_seconds": tot_dur_sec,
            "total_duration_formatted": format_seconds_to_duration(tot_dur_sec),
            "avg_duration_seconds": avg_dur_sec,
            "avg_duration_formatted": format_seconds_to_duration(avg_dur_sec),
            "last_conversation_date": last_conv_dt,
            "priority": p_label,
            "_internal_score": score,
        })

    # 5. Sort candidates strictly: Highest internal score first -> Highest duration -> Most recent date
    ranked_candidates.sort(
        key=lambda item: (
            item["_internal_score"],
            item["total_duration_seconds"],
            item["last_conversation_date"].timestamp() if item["last_conversation_date"] else 0,
        ),
        reverse=True,
    )

    total_candidates = len(ranked_candidates)

    # 6. Assign 1-indexed sequential rank based on sorted engagement
    for idx, item in enumerate(ranked_candidates):
        item["rank"] = idx + 1

    # 7. Paginate
    paged_items = ranked_candidates[offset : offset + limit]

    output_items = [
        AdminCustomerPriorityRankingItem(
            rank=it["rank"],
            customer_id=it["customer_id"],
            customer_name=it["customer_name"],
            phone=it["phone"],
            email=it["email"],
            total_conversations=it["total_conversations"],
            repeat_conversations=it["repeat_conversations"],
            total_duration_seconds=it["total_duration_seconds"],
            total_duration_formatted=it["total_duration_formatted"],
            avg_duration_seconds=it["avg_duration_seconds"],
            avg_duration_formatted=it["avg_duration_formatted"],
            last_conversation_date=it["last_conversation_date"],
            priority=it["priority"],
        )
        for it in paged_items
    ]

    return AdminCustomerPriorityRankingResponse(
        items=output_items,
        total=total_candidates,
        limit=limit,
        offset=offset,
        time_range=time_range,
    )


# =============================================================================
# VIEW CUSTOMER DETAILS ACTION ENDPOINT
# =============================================================================

@router.get("/customers/{customer_id}/details", response_model=AdminCustomerDetailResponse)
def get_customer_operational_details(
    customer_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Returns comprehensive operational customer profile for the "View Details" action.
    
    SECURITY GUARANTEE:
    - Never includes raw audio recordings, transcripts, or authentication secrets.
    - Accessible only to authorized Admins and Super Owners.
    """
    cust = db.execute(select(Customer).where(Customer.id == customer_id)).scalar_one_or_none()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer record not found.",
        )

    latest_lead = db.execute(
        select(Lead).where(Lead.customer_id == cust.id).order_by(Lead.created_at.desc())
    ).scalars().first()

    # Conversations
    convs = db.execute(
        select(Conversation)
        .where(Conversation.customer_id == cust.id)
        .order_by(Conversation.created_at.desc())
    ).scalars().all()

    tot_convs = len(convs)
    tot_dur_sec = sum(c.duration_seconds for c in convs)
    rep_convs = max(tot_convs - 1, 0)
    last_conv_dt = convs[0].created_at if convs else None

    # Calculate engagement priority level
    tot_min = tot_dur_sec / 60.0
    score = tot_min + (rep_convs * 10.0)
    if score >= 50.0:
        p_level = "High"
    elif score >= 20.0:
        p_level = "Medium"
    else:
        p_level = "Low"

    # Site visits
    visits = db.execute(
        select(SiteVisit, Project.name.label("proj_name"))
        .outerjoin(Project, SiteVisit.project_id == Project.id)
        .where(SiteVisit.customer_id == cust.id)
        .order_by(SiteVisit.scheduled_start.desc())
    ).all()

    visit_summaries = [
        AdminSiteVisitSummary(
            id=v.SiteVisit.id,
            project_name=v.proj_name or "Project Visit",
            scheduled_start=v.SiteVisit.scheduled_start,
            status=v.SiteVisit.status,
            notes=getattr(v.SiteVisit, "customer_notes", None),
        )
        for v in visits
    ]

    conv_items = [
        AdminConversationItem(
            id=c.id,
            session_id=c.session_id,
            customer_id=c.customer_id,
            customer_name=cust.full_name,
            duration_seconds=c.duration_seconds,
            conversation_priority=c.conversation_priority,
            created_at=c.created_at,
        )
        for c in convs
    ]

    # Project name for latest lead if any
    interested_proj_name = None
    if latest_lead and latest_lead.project_id:
        proj = db.execute(select(Project).where(Project.id == latest_lead.project_id)).scalar_one_or_none()
        if proj:
            interested_proj_name = proj.name

    # Average duration and recent conversation duration
    avg_dur_sec = int(tot_dur_sec / tot_convs) if tot_convs > 0 else 0
    recent_dur_formatted = format_seconds_to_duration(convs[0].duration_seconds) if convs else None

    # Dynamic factual engagement summary
    if tot_convs == 0:
        eng_summary = "This customer has registered but has not yet completed any AI conversations."
    elif tot_convs == 1:
        eng_summary = f"This customer completed 1 AI conversation with a total talk time of {format_seconds_to_duration(tot_dur_sec)}."
    else:
        eng_summary = f"This customer completed {tot_convs} AI conversations, including {rep_convs} repeat conversation{'s' if rep_convs != 1 else ''}, with a total talk time of {format_seconds_to_duration(tot_dur_sec)}."

    # Site visits chronological analysis
    def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    site_visit_status = visits[0].SiteVisit.status if visits else None
    now_utc = datetime.now(timezone.utc)
    past_visits = [v for v in visits if _to_utc(v.SiteVisit.scheduled_start) <= now_utc]
    last_visit_dt = past_visits[0].SiteVisit.scheduled_start if past_visits else (visits[-1].SiteVisit.scheduled_start if visits else None)
    upcoming_visits = [v for v in visits if _to_utc(v.SiteVisit.scheduled_start) > now_utc]
    next_visit_dt = upcoming_visits[-1].SiteVisit.scheduled_start if upcoming_visits else None

    b_min = float(latest_lead.budget_min) if latest_lead and latest_lead.budget_min else None
    b_max = float(latest_lead.budget_max) if latest_lead and latest_lead.budget_max else None

    return AdminCustomerDetailResponse(
        customer_id=cust.id,
        customer_name=cust.full_name,
        phone=cust.phone,
        email=cust.email,
        is_verified=cust.is_verified,
        registration_date=cust.created_at,
        preferred_location=latest_lead.preferred_location if latest_lead else None,
        interested_project=interested_proj_name,
        property_type="Apartment" if (latest_lead and latest_lead.preferred_config) else None,
        preferred_config=latest_lead.preferred_config if latest_lead else None,
        budget_display=format_budget_range(b_min, b_max),
        budget_min=b_min,
        budget_max=b_max,
        lead_priority=latest_lead.lead_priority if latest_lead else None,
        qualification_status=latest_lead.qualification_status if latest_lead else None,
        notes=latest_lead.notes if latest_lead else None,
        total_conversations=tot_convs,
        total_duration_formatted=format_seconds_to_duration(tot_dur_sec),
        avg_duration_formatted=format_seconds_to_duration(avg_dur_sec),
        recent_conversation_duration_formatted=recent_dur_formatted,
        repeat_conversations=rep_convs,
        last_conversation_date=last_conv_dt,
        priority_level=p_level,
        engagement_summary=eng_summary,
        site_visit_status=site_visit_status,
        last_site_visit_date=last_visit_dt,
        next_scheduled_visit=next_visit_dt,
        conversations=conv_items,
        site_visits=visit_summaries,
    )

