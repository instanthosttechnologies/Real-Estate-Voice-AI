from typing import Optional

from app.api.deps import get_current_customer
from app.db.session import get_db
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.site_visit import SiteVisit
from app.schemas.customer import (
    CustomerLeadResponse,
    CustomerProfileResponse,
    CustomerRequirementUpdateRequest,
    CustomerSiteVisitResponse,
)
from app.services.real_estate.priority import calculate_lead_priority
from app.services.real_estate.requirements import ExtractedCustomerRequirements
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/customer", tags=["Customer Portal"])


@router.get("/profile", response_model=CustomerProfileResponse)
def get_customer_profile(
    current_customer: Customer = Depends(get_current_customer),
):
    # OTP verification check
    if not current_customer.is_verified:
        raise HTTPException(
            status_code=403,
            detail="OTP verification is required to access the customer profile.",
        )

    return current_customer


@router.get("/leads", response_model=list[CustomerLeadResponse])
def list_customer_leads(
    current_customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Returns the authenticated customer's own lead records only (if verified)."""
    if not current_customer.is_verified:
        return []
    leads = (
        db.execute(
            select(Lead)
            .where(Lead.customer_id == current_customer.id)
            .order_by(Lead.created_at.desc())
        )
        .scalars()
        .all()
    )
    return leads


@router.get("/requirements", response_model=Optional[CustomerLeadResponse])
def get_customer_requirements(
    current_customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Returns the customer's most recent submitted requirements (if verified)."""
    if not current_customer.is_verified:
        return None
    latest_lead = (
        db.execute(
            select(Lead)
            .where(Lead.customer_id == current_customer.id)
            .order_by(Lead.created_at.desc())
        )
        .scalars()
        .first()
    )
    return latest_lead


@router.put("/requirements", response_model=CustomerLeadResponse)
def update_customer_requirements(
    req: CustomerRequirementUpdateRequest,
    current_customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Updates or registers customer requirements.
    Re-evaluates priority score and priority reason deterministically.
    """
    # Check if a lead exists to update, else create new
    lead = (
        db.execute(
            select(Lead)
            .where(Lead.customer_id == current_customer.id)
            .order_by(Lead.created_at.desc())
        )
        .scalars()
        .first()
    )

    if not lead:
        lead = Lead(customer_id=current_customer.id)
        db.add(lead)

    if req.preferred_location is not None:
        lead.preferred_location = req.preferred_location
    if req.preferred_configuration is not None:
        lead.preferred_config = req.preferred_configuration
    if req.budget_min is not None:
        lead.budget_min = req.budget_min
    if req.budget_max is not None:
        lead.budget_max = req.budget_max

    # Re-evaluate priority
    extracted = ExtractedCustomerRequirements(
        preferred_city=req.preferred_city,
        preferred_location=lead.preferred_location,
        configuration_type=lead.preferred_config,
        budget_min=float(lead.budget_min) if lead.budget_min else None,
        budget_max=float(lead.budget_max) if lead.budget_max else None,
        currency=req.currency or "INR",
        purchase_timeline=req.purchase_timeline,
        required_amenities=req.required_amenities or [],
    )
    eval_res = calculate_lead_priority(extracted)
    lead.lead_priority = eval_res.lead_priority
    lead.notes = (
        f"Score: {eval_res.priority_score}/100. Reason: {eval_res.priority_reason}"
    )

    db.commit()
    db.refresh(lead)
    return lead


@router.get("/site-visits", response_model=list[CustomerSiteVisitResponse])
def list_customer_site_visits(
    current_customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Returns the authenticated customer's own site visit bookings only (if verified)."""
    if not current_customer.is_verified:
        return []
    visits = (
        db.execute(
            select(SiteVisit)
            .where(SiteVisit.customer_id == current_customer.id)
            .order_by(SiteVisit.scheduled_start.desc())
        )
        .scalars()
        .all()
    )
    return visits
