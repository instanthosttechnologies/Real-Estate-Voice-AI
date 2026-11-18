import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.models.audit_log import AuditLog
from app.services.real_estate.requirements import ExtractedCustomerRequirements


class PriorityEvaluationResult(BaseModel):
    lead_priority: str  # 'low', 'medium', 'high', 'urgent'
    priority_score: int = Field(..., ge=0, le=100)
    priority_reason: str
    evaluated_at: datetime


def calculate_lead_priority(
    requirements: ExtractedCustomerRequirements,
    has_scheduled_visit: bool = False,
    is_preapproved_loan_or_cash: bool = False,
) -> PriorityEvaluationResult:
    """
    Deterministic rule-based lead priority evaluation combining extracted customer intent,
    purchase timeline, financial readiness, and appointment requests.
    """
    score = 0
    reasons = []

    # 1. Timeline readiness (Max 40 points)
    if requirements.purchase_timeline == "immediate":
        score += 40
        reasons.append("Immediate purchase timeline (ready to buy/move).")
    elif requirements.purchase_timeline == "1_month":
        score += 30
        reasons.append("Short-term timeline within 30 days.")
    elif requirements.purchase_timeline == "1_3_months":
        score += 20
        reasons.append("Medium-term timeline (1 to 3 months).")
    elif requirements.purchase_timeline == "exploring":
        score += 5
        reasons.append("Early exploratory stage / indefinite timeline.")
    else:
        score += 10
        reasons.append("Timeline not yet specified.")

    # 2. Budget certainty (Max 25 points)
    if requirements.budget_max is not None and requirements.budget_max > 0:
        score += 25
        reasons.append(f"Confirmed budget cap ({requirements.currency} {requirements.budget_max:,.0f}).")
    elif requirements.budget_min is not None:
        score += 15
        reasons.append("Minimum budget indicated.")
    else:
        reasons.append("Budget undefined.")

    # 3. Requirement completeness (Max 15 points)
    if requirements.is_complete:
        score += 15
        reasons.append("Complete search criteria provided (Location, Layout, Budget).")
    elif requirements.configuration_type and (requirements.preferred_city or requirements.preferred_location):
        score += 10
        reasons.append("Layout and location specified.")
    else:
        reasons.append("Incomplete search criteria.")

    # 4. Behavioral commitment / Actions (Max 20 points)
    if has_scheduled_visit:
        score += 15
        reasons.append("Requested/booked a property site visit.")
    if is_preapproved_loan_or_cash:
        score += 5
        reasons.append("Financially pre-approved or cash buyer.")

    final_score = min(score, 100)

    # Classify priority
    if final_score >= 80:
        level = "urgent"
    elif final_score >= 60:
        level = "high"
    elif final_score >= 35:
        level = "medium"
    else:
        level = "low"

    now = datetime.now(timezone.utc)
    summary_reason = "; ".join(reasons)

    return PriorityEvaluationResult(
        lead_priority=level,
        priority_score=final_score,
        priority_reason=summary_reason,
        evaluated_at=now,
    )


def apply_manual_priority_override(
    db: Session,
    lead_id: uuid.UUID,
    new_priority: str,
    override_reason: str,
    actor_user_id: uuid.UUID,
    actor_role: str,
) -> Lead:
    """
    Manually overrides lead priority and records an immutable audit log entry.
    """
    if new_priority not in ["low", "medium", "high", "urgent"]:
        raise ValueError(f"Invalid priority level: {new_priority}")

    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found.")

    old_priority = lead.lead_priority
    lead.lead_priority = new_priority
    lead.notes = (lead.notes or "") + f"\n[{datetime.now(timezone.utc).isoformat()}] Manual priority override by {actor_role} to {new_priority}: {override_reason}"

    # Record immutable audit log
    audit_entry = AuditLog(
        user_id=actor_user_id,
        user_role=actor_role,
        action="MANUAL_LEAD_PRIORITY_OVERRIDE",
        resource_type="lead",
        resource_id=str(lead.id),
        meta_info={
            "old_priority": old_priority,
            "new_priority": new_priority,
            "override_reason": override_reason,
        },
        timestamp=datetime.now(timezone.utc),
    )
    db.add(audit_entry)
    db.commit()
    db.refresh(lead)
    return lead
