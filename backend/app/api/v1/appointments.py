from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.appointment import Appointment
from app.services.real_estate.demo_dataset import DemoDatasetService

router = APIRouter(prefix="/appointments", tags=["Appointments & Calendar"])

STANDARD_SLOTS = [
    "10:00 AM - 11:00 AM",
    "11:30 AM - 12:30 PM",
    "02:00 PM - 03:00 PM",
    "03:30 PM - 04:30 PM",
    "05:00 PM - 06:00 PM",
]


class AppointmentSchema(BaseModel):
    id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    customer_name: str
    contact_number: Optional[str] = None
    project_id: str
    property_name: str
    city: str
    visit_date: date
    visit_time: str
    timezone: str = "Asia/Kolkata"
    appointment_type: str = "In-Person Site Visit"
    booking_status: str = "confirmed"
    conversation_id: Optional[str] = None
    booking_source: str = "AI Voice"
    customer_notes: Optional[str] = None
    assigned_agent: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AppointmentListResponse(BaseModel):
    total: int
    items: List[AppointmentSchema]
    active_confirmed_count: int
    rescheduled_count: int
    cancelled_count: int


class CreateAppointmentRequest(BaseModel):
    customer_name: str = Field(..., min_length=1)
    contact_number: Optional[str] = None
    project_id: Optional[str] = None
    property_name: str = Field(..., min_length=1)
    city: Optional[str] = None
    visit_date: date
    visit_time: str = Field(..., min_length=1)
    appointment_type: Optional[str] = "In-Person Site Visit"
    customer_notes: Optional[str] = None
    assigned_agent: Optional[str] = "Senior Property Advisor"


class RescheduleAppointmentRequest(BaseModel):
    new_visit_date: date
    new_visit_time: str
    reschedule_reason: Optional[str] = None


class SlotsResponse(BaseModel):
    project_id: str
    property_name: str
    visit_date: date
    all_slots: List[str]
    available_slots: List[str]
    booked_slots: List[str]
    total_available: int


@router.get("", response_model=AppointmentListResponse)
def list_appointments(
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    city: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Lists appointments with rich filtering for the Admin Calendar and Booking Management.
    """
    stmt = select(Appointment)

    if status_filter and status_filter.lower() != "all":
        stmt = stmt.where(Appointment.booking_status == status_filter.lower())

    if date_from:
        stmt = stmt.where(Appointment.visit_date >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.visit_date <= date_to)

    if city:
        stmt = stmt.where(Appointment.city.ilike(f"%{city}%"))

    if search:
        s = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Appointment.customer_name.ilike(s),
                Appointment.property_name.ilike(s),
                Appointment.contact_number.ilike(s),
            )
        )

    # Count total
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # Get status breakdown counts
    confirmed_cnt = db.scalar(
        select(func.count(Appointment.id)).where(Appointment.booking_status == "confirmed")
    ) or 0
    rescheduled_cnt = db.scalar(
        select(func.count(Appointment.id)).where(Appointment.booking_status == "rescheduled")
    ) or 0
    cancelled_cnt = db.scalar(
        select(func.count(Appointment.id)).where(Appointment.booking_status == "cancelled")
    ) or 0

    # Sort by visit_date, then created_at desc
    stmt = stmt.order_by(Appointment.visit_date.asc(), Appointment.visit_time.asc()).offset(offset).limit(limit)
    items = db.scalars(stmt).all()

    return AppointmentListResponse(
        total=total,
        items=items,
        active_confirmed_count=confirmed_cnt,
        rescheduled_count=rescheduled_cnt,
        cancelled_count=cancelled_cnt,
    )


@router.get("/slots", response_model=SlotsResponse)
def get_appointment_slots(
    project_identifier: str = Query(..., description="Project name or ID"),
    target_date: date = Query(..., description="Date to check (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    """
    Queries slot availability for a specific project and date with double-booking checks.
    """
    demo_svc = DemoDatasetService.get_instance()
    details = demo_svc.get_property_details(project_identifier)
    proj_id = details["project_id"] if details else project_identifier
    proj_name = details["project_name"] if details else project_identifier

    # Query confirmed/rescheduled bookings
    stmt = select(Appointment.visit_time).where(
        or_(
            Appointment.project_id == proj_id,
            Appointment.property_name.ilike(f"%{proj_name}%"),
        ),
        Appointment.visit_date == target_date,
        Appointment.booking_status.in_(["confirmed", "rescheduled"]),
    )
    booked_slots = set(db.scalars(stmt).all())
    available_slots = [s for s in STANDARD_SLOTS if s not in booked_slots]

    return SlotsResponse(
        project_id=proj_id,
        property_name=proj_name,
        visit_date=target_date,
        all_slots=STANDARD_SLOTS,
        available_slots=available_slots,
        booked_slots=list(booked_slots),
        total_available=len(available_slots),
    )


@router.post("", response_model=AppointmentSchema, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: CreateAppointmentRequest,
    db: Session = Depends(get_db),
):
    """
    Creates a new appointment with strict double-booking prevention.
    """
    demo_svc = DemoDatasetService.get_instance()
    details = demo_svc.get_property_details(payload.property_name)
    proj_id = payload.project_id or (details["project_id"] if details else "PROJ_GEN")
    proj_name = details["project_name"] if details else payload.property_name
    city = payload.city or (details.get("city") if details else "Primary Location")

    # Double booking check
    conflict = db.scalars(
        select(Appointment).where(
            or_(
                Appointment.project_id == proj_id,
                Appointment.property_name.ilike(f"%{proj_name}%"),
            ),
            Appointment.visit_date == payload.visit_date,
            Appointment.visit_time == payload.visit_time,
            Appointment.booking_status.in_(["confirmed", "rescheduled"]),
        )
    ).first()

    if conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The time slot '{payload.visit_time}' on {payload.visit_date} for {proj_name} is already booked.",
        )

    appt = Appointment(
        id=uuid.uuid4(),
        customer_name=payload.customer_name,
        contact_number=payload.contact_number,
        project_id=proj_id,
        property_name=proj_name,
        city=city,
        visit_date=payload.visit_date,
        visit_time=payload.visit_time,
        timezone="Asia/Kolkata",
        appointment_type=payload.appointment_type or "In-Person Site Visit",
        booking_status="confirmed",
        booking_source="Admin Portal",
        customer_notes=payload.customer_notes,
        assigned_agent=payload.assigned_agent or "Senior Property Advisor",
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


@router.get("/{appointment_id}", response_model=AppointmentSchema)
def get_appointment(
    appointment_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@router.put("/{appointment_id}/reschedule", response_model=AppointmentSchema)
def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: RescheduleAppointmentRequest,
    db: Session = Depends(get_db),
):
    """
    Reschedules an appointment to a new date and time slot, checking for slot conflict.
    """
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Conflict check on new date & time slot
    conflict = db.scalars(
        select(Appointment).where(
            Appointment.id != appointment_id,
            or_(
                Appointment.project_id == appt.project_id,
                Appointment.property_name.ilike(f"%{appt.property_name}%"),
            ),
            Appointment.visit_date == payload.new_visit_date,
            Appointment.visit_time == payload.new_visit_time,
            Appointment.booking_status.in_(["confirmed", "rescheduled"]),
        )
    ).first()

    if conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The slot '{payload.new_visit_time}' on {payload.new_visit_date} is already reserved by another customer.",
        )

    old_date = appt.visit_date
    old_time = appt.visit_time
    appt.visit_date = payload.new_visit_date
    appt.visit_time = payload.new_visit_time
    appt.booking_status = "rescheduled"

    reason_note = f"\n[Rescheduled from {old_date} {old_time} to {payload.new_visit_date} {payload.new_visit_time}]"
    if payload.reschedule_reason:
        reason_note += f" Reason: {payload.reschedule_reason}"
    appt.customer_notes = (appt.customer_notes or "") + reason_note

    db.commit()
    db.refresh(appt)
    return appt


@router.delete("/{appointment_id}", response_model=AppointmentSchema)
def cancel_appointment(
    appointment_id: uuid.UUID,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Cancels an appointment and marks status as 'cancelled'.
    """
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    appt.booking_status = "cancelled"
    cancel_note = f"\n[Cancelled on {datetime.now(timezone.utc).isoformat()}]"
    if reason:
        cancel_note += f" Reason: {reason}"
    appt.customer_notes = (appt.customer_notes or "") + cancel_note

    db.commit()
    db.refresh(appt)
    return appt
