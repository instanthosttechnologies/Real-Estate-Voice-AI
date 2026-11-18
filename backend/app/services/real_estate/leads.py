import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.lead import Lead
from app.services.real_estate.requirements import ExtractedCustomerRequirements
from app.services.real_estate.priority import calculate_lead_priority


class CreateLeadInput(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    requirements: ExtractedCustomerRequirements
    initial_notes: Optional[str] = None


class UpdateLeadInput(BaseModel):
    lead_id: uuid.UUID
    preferred_config: Optional[str] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    preferred_location: Optional[str] = None
    qualification_status: Optional[str] = None
    lead_priority: Optional[str] = None
    append_notes: Optional[str] = None


class LeadDetailResponse(BaseModel):
    lead_id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    phone: str
    email: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    preferred_config: Optional[str] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    preferred_location: Optional[str] = None
    lead_priority: str
    qualification_status: str
    source: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


def create_or_get_customer(
    db: Session,
    full_name: str,
    phone: str,
    email: Optional[str] = None
) -> Customer:
    """Finds existing customer by phone or creates a new profile."""
    clean_phone = phone.strip()
    cust = db.execute(select(Customer).where(Customer.phone == clean_phone)).scalar_one_or_none()
    if not cust:
        cust = Customer(
            full_name=full_name.strip(),
            phone=clean_phone,
            email=email.strip() if email else None,
        )
        db.add(cust)
        db.flush()
    return cust


def create_customer_lead(
    db: Session,
    input_data: CreateLeadInput
) -> LeadDetailResponse:
    """
    Creates or associates a customer and initializes a new qualified lead record.
    """
    customer = create_or_get_customer(
        db=db,
        full_name=input_data.full_name,
        phone=input_data.phone,
        email=input_data.email
    )

    # Evaluate priority
    priority_eval = calculate_lead_priority(input_data.requirements)

    # Determine qualification status
    qual_status = "unqualified"
    if input_data.requirements.is_complete:
        qual_status = "budget_matched"

    lead = Lead(
        customer_id=customer.id,
        project_id=input_data.project_id,
        preferred_config=input_data.requirements.configuration_type,
        budget_min=input_data.requirements.budget_min,
        budget_max=input_data.requirements.budget_max,
        preferred_location=input_data.requirements.preferred_city or input_data.requirements.preferred_location,
        lead_priority=priority_eval.lead_priority,
        qualification_status=qual_status,
        source="voice_ai",
        notes=f"[{datetime.now(timezone.utc).isoformat()}] Initial priority evaluated: {priority_eval.priority_reason}\n{input_data.initial_notes or ''}".strip(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    return LeadDetailResponse(
        lead_id=lead.id,
        customer_id=customer.id,
        customer_name=customer.full_name,
        phone=customer.phone,
        email=customer.email,
        project_id=lead.project_id,
        preferred_config=lead.preferred_config,
        budget_min=lead.budget_min,
        budget_max=lead.budget_max,
        preferred_location=lead.preferred_location,
        lead_priority=lead.lead_priority,
        qualification_status=lead.qualification_status,
        source=lead.source,
        notes=lead.notes,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def update_customer_lead(
    db: Session,
    input_data: UpdateLeadInput
) -> LeadDetailResponse:
    """
    Updates an existing customer lead with new requirements, status, or interaction notes.
    """
    lead = db.get(Lead, input_data.lead_id)
    if not lead:
        raise ValueError(f"Lead {input_data.lead_id} does not exist.")

    customer = db.get(Customer, lead.customer_id)

    if input_data.preferred_config is not None:
        lead.preferred_config = input_data.preferred_config
    if input_data.budget_min is not None:
        lead.budget_min = input_data.budget_min
    if input_data.budget_max is not None:
        lead.budget_max = input_data.budget_max
    if input_data.preferred_location is not None:
        lead.preferred_location = input_data.preferred_location
    if input_data.qualification_status is not None:
        lead.qualification_status = input_data.qualification_status
    if input_data.lead_priority is not None:
        lead.lead_priority = input_data.lead_priority

    if input_data.append_notes:
        now_str = datetime.now(timezone.utc).isoformat()
        lead.notes = (lead.notes or "") + f"\n[{now_str}] {input_data.append_notes}"

    lead.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lead)

    return LeadDetailResponse(
        lead_id=lead.id,
        customer_id=customer.id if customer else uuid.uuid4(),
        customer_name=customer.full_name if customer else "Unknown",
        phone=customer.phone if customer else "",
        email=customer.email if customer else None,
        project_id=lead.project_id,
        preferred_config=lead.preferred_config,
        budget_min=lead.budget_min,
        budget_max=lead.budget_max,
        preferred_location=lead.preferred_location,
        lead_priority=lead.lead_priority,
        qualification_status=lead.qualification_status,
        source=lead.source,
        notes=lead.notes,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )
