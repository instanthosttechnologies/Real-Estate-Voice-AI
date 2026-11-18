import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.lead import Lead
from app.models.project import Project
from app.models.property import PropertyUnit
from app.models.site_visit import SiteVisit


class TimeSlot(BaseModel):
    start_time: datetime
    end_time: datetime
    is_available: bool
    booked_count: int = 0
    local_start_time: Optional[str] = None
    local_end_time: Optional[str] = None
    local_display: Optional[str] = None
    timezone: Optional[str] = None


class AvailableSlotsResponse(BaseModel):
    project_id: uuid.UUID
    target_date: date
    project_timezone: str = "UTC"
    slots: List[TimeSlot]


class BookVisitInput(BaseModel):
    customer_id: uuid.UUID
    project_id: uuid.UUID
    unit_id: Optional[uuid.UUID] = None
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None  # Default +1 hour
    assigned_agent_name: Optional[str] = "Senior Sales Advisor"
    customer_notes: Optional[str] = None


class RescheduleVisitInput(BaseModel):
    visit_id: uuid.UUID
    new_scheduled_start: datetime
    new_scheduled_end: Optional[datetime] = None
    reschedule_reason: Optional[str] = None


class SiteVisitDetailResponse(BaseModel):
    visit_id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    customer_phone: str
    project_id: uuid.UUID
    project_name: str
    unit_id: Optional[uuid.UUID] = None
    unit_number: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    assigned_agent_name: Optional[str] = None
    customer_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


def get_available_visit_slots(
    db: Session,
    project_id: uuid.UUID,
    target_date: date,
    max_concurrent_visits_per_slot: int = 2
) -> AvailableSlotsResponse:
    """
    Computes available 1-hour appointment slots between 09:00 and 18:00
    in the project's local timezone on the specified target date.
    """
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found.")

    proj_tz_str = project.timezone or "UTC"
    try:
        proj_tz = ZoneInfo(proj_tz_str)
    except Exception:
        proj_tz = timezone.utc
        proj_tz_str = "UTC"

    # Generate 1-hour slots from 09:00 to 18:00 in project-local timezone
    local_slots = []
    for hour in range(9, 18):
        local_start = datetime.combine(target_date, time(hour, 0)).replace(tzinfo=proj_tz)
        local_end = local_start + timedelta(hours=1)
        utc_start = local_start.astimezone(timezone.utc)
        utc_end = local_end.astimezone(timezone.utc)
        local_slots.append((local_start, local_end, utc_start, utc_end))

    # UTC window covering all local slots
    min_utc = min(s[2] for s in local_slots)
    max_utc = max(s[3] for s in local_slots)

    # Query all active visits for this project covering this window
    existing_visits = db.execute(
        select(SiteVisit).where(
            SiteVisit.project_id == project_id,
            SiteVisit.status.in_(["scheduled", "rescheduled"]),
            SiteVisit.scheduled_start < max_utc,
            SiteVisit.scheduled_end > min_utc,
        )
    ).scalars().all()

    slots_result: List[TimeSlot] = []

    for local_start, local_end, utc_start, utc_end in local_slots:
        overlapping = [
            v for v in existing_visits
            if (
                (v.scheduled_start.replace(tzinfo=timezone.utc) if v.scheduled_start.tzinfo is None else v.scheduled_start) < utc_end
                and (v.scheduled_end.replace(tzinfo=timezone.utc) if v.scheduled_end.tzinfo is None else v.scheduled_end) > utc_start
            )
        ]
        count = len(overlapping)
        is_avail = count < max_concurrent_visits_per_slot

        slots_result.append(
            TimeSlot(
                start_time=utc_start,
                end_time=utc_end,
                is_available=is_avail,
                booked_count=count,
                local_start_time=local_start.isoformat(),
                local_end_time=local_end.isoformat(),
                local_display=f"{local_start.strftime('%I:%M %p')} - {local_end.strftime('%I:%M %p')} {proj_tz_str}",
                timezone=proj_tz_str,
            )
        )

    return AvailableSlotsResponse(
        project_id=project_id,
        target_date=target_date,
        project_timezone=proj_tz_str,
        slots=slots_result,
    )


def book_site_visit(
    db: Session,
    input_data: BookVisitInput,
    max_concurrent_visits: int = 2
) -> SiteVisitDetailResponse:
    """
    Books a site visit appointment and enforces double-booking prevention.
    Applies PostgreSQL-safe row-level locking (with_for_update) to serialize concurrent booking transactions.
    Validates appointment times against project-local operating hours (09:00 - 18:00 local time).
    """
    # 0. Acquire row-level locks on project and customer to serialize concurrent transactions
    project = db.execute(
        select(Project).where(Project.id == input_data.project_id).with_for_update()
    ).scalar_one_or_none()
    if not project:
        raise ValueError(f"Project {input_data.project_id} does not exist.")

    customer = db.execute(
        select(Customer).where(Customer.id == input_data.customer_id).with_for_update()
    ).scalar_one_or_none()
    if not customer:
        raise ValueError(f"Customer {input_data.customer_id} does not exist.")

    # Time normalization
    proj_tz_str = project.timezone or "UTC"
    try:
        proj_tz = ZoneInfo(proj_tz_str)
    except Exception:
        proj_tz = timezone.utc

    raw_start = input_data.scheduled_start
    if raw_start.tzinfo is None:
        local_start = raw_start.replace(tzinfo=proj_tz)
        start_time = local_start.astimezone(timezone.utc)
    else:
        start_time = raw_start.astimezone(timezone.utc)
        local_start = raw_start.astimezone(proj_tz)

    raw_end = input_data.scheduled_end or (raw_start + timedelta(hours=1))
    if raw_end.tzinfo is None:
        local_end = raw_end.replace(tzinfo=proj_tz)
        end_time = local_end.astimezone(timezone.utc)
    else:
        end_time = raw_end.astimezone(timezone.utc)
        local_end = raw_end.astimezone(proj_tz)

    if end_time <= start_time:
        raise ValueError("Appointment end time must be strictly after start time.")

    # Validate against project-local operating hours (09:00 - 18:00 local time)
    if local_start.time() < time(9, 0) or local_end.time() > time(18, 0) or local_start.date() != local_end.date():
        raise ValueError(
            f"Site visits must be scheduled within project operating hours (09:00 - 18:00 {proj_tz_str}). "
            f"Requested: {local_start.strftime('%H:%M')} to {local_end.strftime('%H:%M')} {proj_tz_str}."
        )

    # 1. Prevent customer double booking across any project
    cust_conflict = db.execute(
        select(SiteVisit).where(
            SiteVisit.customer_id == customer.id,
            SiteVisit.status.in_(["scheduled", "rescheduled"]),
            SiteVisit.scheduled_start < end_time,
            SiteVisit.scheduled_end > start_time,
        )
    ).scalar_one_or_none()

    if cust_conflict:
        raise ValueError(
            f"Customer already has an active site visit scheduled from "
            f"{cust_conflict.scheduled_start.isoformat()} to {cust_conflict.scheduled_end.isoformat()}."
        )

    # 2. Prevent unit double booking if specific unit selected
    unit_obj = None
    if input_data.unit_id:
        unit_obj = db.get(PropertyUnit, input_data.unit_id)
        if unit_obj:
            unit_conflict = db.execute(
                select(SiteVisit).where(
                    SiteVisit.unit_id == unit_obj.id,
                    SiteVisit.status.in_(["scheduled", "rescheduled"]),
                    SiteVisit.scheduled_start < end_time,
                    SiteVisit.scheduled_end > start_time,
                )
            ).scalar_one_or_none()
            if unit_conflict:
                raise ValueError(
                    f"Unit {unit_obj.unit_number} already has a scheduled visit during this slot."
                )

    # 3. Check project capacity for this slot
    concurrent_visits = db.execute(
        select(SiteVisit).where(
            SiteVisit.project_id == project.id,
            SiteVisit.status.in_(["scheduled", "rescheduled"]),
            SiteVisit.scheduled_start < end_time,
            SiteVisit.scheduled_end > start_time,
        )
    ).scalars().all()

    if len(concurrent_visits) >= max_concurrent_visits:
        raise ValueError("Selected time slot has reached maximum capacity for this project.")

    # Create site visit record
    visit = SiteVisit(
        customer_id=customer.id,
        project_id=project.id,
        unit_id=input_data.unit_id,
        scheduled_start=start_time,
        scheduled_end=end_time,
        status="scheduled",
        assigned_agent_name=input_data.assigned_agent_name,
        customer_notes=input_data.customer_notes,
    )
    db.add(visit)

    # Update associated customer lead status to 'ready_to_visit'
    latest_lead = db.execute(
        select(Lead).where(Lead.customer_id == customer.id).order_by(Lead.created_at.desc())
    ).scalars().first()
    if latest_lead:
        latest_lead.qualification_status = "ready_to_visit"
        latest_lead.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(visit)

    return SiteVisitDetailResponse(
        visit_id=visit.id,
        customer_id=customer.id,
        customer_name=customer.full_name,
        customer_phone=customer.phone,
        project_id=project.id,
        project_name=project.name,
        unit_id=visit.unit_id,
        unit_number=unit_obj.unit_number if unit_obj else None,
        scheduled_start=visit.scheduled_start,
        scheduled_end=visit.scheduled_end,
        status=visit.status,
        assigned_agent_name=visit.assigned_agent_name,
        customer_notes=visit.customer_notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
    )


def reschedule_site_visit(
    db: Session,
    input_data: RescheduleVisitInput,
    max_concurrent_visits: int = 2
) -> SiteVisitDetailResponse:
    """
    Reschedules an active site visit to a new conflict-free time slot.
    Applies row-level locking and verifies project-local operating hours.
    """
    visit = db.execute(
        select(SiteVisit).where(SiteVisit.id == input_data.visit_id).with_for_update()
    ).scalar_one_or_none()
    if not visit:
        raise ValueError(f"Site visit {input_data.visit_id} does not exist.")
    if visit.status == "cancelled":
        raise ValueError("Cannot reschedule a cancelled visit.")

    project = db.get(Project, visit.project_id)
    proj_tz_str = project.timezone if project and project.timezone else "UTC"
    try:
        proj_tz = ZoneInfo(proj_tz_str)
    except Exception:
        proj_tz = timezone.utc

    raw_start = input_data.new_scheduled_start
    if raw_start.tzinfo is None:
        local_start = raw_start.replace(tzinfo=proj_tz)
        new_start = local_start.astimezone(timezone.utc)
    else:
        new_start = raw_start.astimezone(timezone.utc)
        local_start = raw_start.astimezone(proj_tz)

    raw_end = input_data.new_scheduled_end or (raw_start + timedelta(hours=1))
    if raw_end.tzinfo is None:
        local_end = raw_end.replace(tzinfo=proj_tz)
        new_end = local_end.astimezone(timezone.utc)
    else:
        new_end = raw_end.astimezone(timezone.utc)
        local_end = raw_end.astimezone(proj_tz)

    if new_end <= new_start:
        raise ValueError("New appointment end time must be after start time.")

    # Operating hours check
    if local_start.time() < time(9, 0) or local_end.time() > time(18, 0) or local_start.date() != local_end.date():
        raise ValueError(
            f"Site visits must be scheduled within project operating hours (09:00 - 18:00 {proj_tz_str}). "
            f"Requested: {local_start.strftime('%H:%M')} to {local_end.strftime('%H:%M')} {proj_tz_str}."
        )

    # Check project capacity excluding current visit
    conflicting = db.execute(
        select(SiteVisit).where(
            SiteVisit.id != visit.id,
            SiteVisit.project_id == visit.project_id,
            SiteVisit.status.in_(["scheduled", "rescheduled"]),
            SiteVisit.scheduled_start < new_end,
            SiteVisit.scheduled_end > new_start,
        )
    ).scalars().all()

    if len(conflicting) >= max_concurrent_visits:
        raise ValueError("New time slot has reached maximum capacity.")

    visit.scheduled_start = new_start
    visit.scheduled_end = new_end
    visit.status = "rescheduled"
    if input_data.reschedule_reason:
        now_str = datetime.now(timezone.utc).isoformat()
        visit.customer_notes = (visit.customer_notes or "") + f"\n[{now_str}] Rescheduled: {input_data.reschedule_reason}"
    visit.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(visit)

    customer = db.get(Customer, visit.customer_id)
    project = db.get(Project, visit.project_id)
    unit_obj = db.get(PropertyUnit, visit.unit_id) if visit.unit_id else None

    return SiteVisitDetailResponse(
        visit_id=visit.id,
        customer_id=visit.customer_id,
        customer_name=customer.full_name if customer else "Unknown",
        customer_phone=customer.phone if customer else "",
        project_id=visit.project_id,
        project_name=project.name if project else "Unknown",
        unit_id=visit.unit_id,
        unit_number=unit_obj.unit_number if unit_obj else None,
        scheduled_start=visit.scheduled_start,
        scheduled_end=visit.scheduled_end,
        status=visit.status,
        assigned_agent_name=visit.assigned_agent_name,
        customer_notes=visit.customer_notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
    )
    visit.scheduled_end = new_end
    visit.status = "rescheduled"
    if input_data.reschedule_reason:
        now_str = datetime.now(timezone.utc).isoformat()
        visit.customer_notes = (visit.customer_notes or "") + f"\n[{now_str}] Rescheduled: {input_data.reschedule_reason}"
    visit.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(visit)

    customer = db.get(Customer, visit.customer_id)
    project = db.get(Project, visit.project_id)
    unit_obj = db.get(PropertyUnit, visit.unit_id) if visit.unit_id else None

    return SiteVisitDetailResponse(
        visit_id=visit.id,
        customer_id=visit.customer_id,
        customer_name=customer.full_name if customer else "Unknown",
        customer_phone=customer.phone if customer else "",
        project_id=visit.project_id,
        project_name=project.name if project else "Unknown",
        unit_id=visit.unit_id,
        unit_number=unit_obj.unit_number if unit_obj else None,
        scheduled_start=visit.scheduled_start,
        scheduled_end=visit.scheduled_end,
        status=visit.status,
        assigned_agent_name=visit.assigned_agent_name,
        customer_notes=visit.customer_notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
    )


def cancel_site_visit(
    db: Session,
    visit_id: uuid.UUID,
    cancellation_reason: Optional[str] = None
) -> SiteVisitDetailResponse:
    """
    Cancels an active site visit appointment.
    """
    visit = db.get(SiteVisit, visit_id)
    if not visit:
        raise ValueError(f"Site visit {visit_id} does not exist.")
    if visit.status == "cancelled":
        raise ValueError("Site visit is already cancelled.")

    visit.status = "cancelled"
    now_str = datetime.now(timezone.utc).isoformat()
    visit.customer_notes = (visit.customer_notes or "") + f"\n[{now_str}] Cancelled: {cancellation_reason or 'No reason provided'}"
    visit.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(visit)

    customer = db.get(Customer, visit.customer_id)
    project = db.get(Project, visit.project_id)
    unit_obj = db.get(PropertyUnit, visit.unit_id) if visit.unit_id else None

    return SiteVisitDetailResponse(
        visit_id=visit.id,
        customer_id=visit.customer_id,
        customer_name=customer.full_name if customer else "Unknown",
        customer_phone=customer.phone if customer else "",
        project_id=visit.project_id,
        project_name=project.name if project else "Unknown",
        unit_id=visit.unit_id,
        unit_number=unit_obj.unit_number if unit_obj else None,
        scheduled_start=visit.scheduled_start,
        scheduled_end=visit.scheduled_end,
        status=visit.status,
        assigned_agent_name=visit.assigned_agent_name,
        customer_notes=visit.customer_notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
    )
