import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.services.real_estate.search import PropertySearchResultItem
from app.services.real_estate.details import PropertyUnitDetail
from app.services.real_estate.availability import AvailabilityStatusReport
from app.services.real_estate.requirements import ExtractedCustomerRequirements
from app.services.real_estate.priority import PriorityEvaluationResult
from app.services.real_estate.leads import LeadDetailResponse
from app.services.real_estate.site_visits import AvailableSlotsResponse, SiteVisitDetailResponse


# -----------------------------------------------------------------------------
# Tool Input Schemas
# -----------------------------------------------------------------------------

class SearchPropertiesToolInput(BaseModel):
    city: Optional[str] = Field(None, description="City name e.g. 'Seattle', 'Austin'")
    location_query: Optional[str] = Field(None, description="Neighborhood, landmark, or zip code")
    company_name: Optional[str] = Field(None, description="Developer or company name")
    project_name: Optional[str] = Field(None, description="Project or community name")
    property_type: Optional[str] = Field(None, description="Type e.g. 'apartment', 'villa', 'commercial'")
    configuration_type: Optional[str] = Field(None, description="e.g. '1BHK', '2BHK', '3BHK', 'Studio', 'Penthouse'")
    min_budget: Optional[Decimal] = Field(None, ge=0, description="Minimum price in currency")
    max_budget: Optional[Decimal] = Field(None, ge=0, description="Maximum price in currency")
    currency: Optional[str] = Field(None, description="ISO 4217 currency code e.g. USD, INR, EUR, AED, GBP. Never assumed.")
    min_carpet_area: Optional[Decimal] = Field(None, gt=0, description="Min carpet area in sqft")
    max_carpet_area: Optional[Decimal] = Field(None, gt=0, description="Max carpet area in sqft")
    required_amenities: Optional[List[str]] = Field(default_factory=list, description="Amenities required e.g. ['Gym', 'Swimming Pool']")
    availability_status: Optional[str] = Field(default="available", description="'available', 'all'")
    limit: int = Field(default=10, ge=1, le=50)


class GetPropertyDetailsToolInput(BaseModel):
    unit_id: str = Field(..., description="Unique UUID or identifier of the property unit")
    include_pricing_history: bool = Field(default=False, description="Whether to include historical pricing records")


class GetPropertyPriceToolInput(BaseModel):
    unit_id: str = Field(..., description="Unique UUID or identifier of the property unit")


class CheckPropertyAvailabilityToolInput(BaseModel):
    unit_id: str = Field(..., description="Unique UUID or identifier of the property unit")


class ComparePropertiesToolInput(BaseModel):
    unit_ids: List[str] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="List of 2 to 5 property unit UUIDs or identifiers to compare side-by-side"
    )


class ExtractRequirementsToolInput(BaseModel):
    customer_utterance: str = Field(..., description="The spoken or written message from the customer")
    existing_requirements: Optional[ExtractedCustomerRequirements] = None


class CreateLeadToolInput(BaseModel):
    full_name: str = Field(..., min_length=1, description="Customer's full name")
    phone: str = Field(..., min_length=7, description="Customer's phone number")
    email: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    requirements: ExtractedCustomerRequirements
    notes: Optional[str] = None


class UpdateLeadToolInput(BaseModel):
    lead_id: uuid.UUID
    preferred_config: Optional[str] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    preferred_location: Optional[str] = None
    qualification_status: Optional[str] = None
    lead_priority: Optional[str] = None
    append_notes: Optional[str] = None


class CalculateLeadPriorityToolInput(BaseModel):
    requirements: ExtractedCustomerRequirements
    has_scheduled_visit: bool = False
    is_preapproved_loan_or_cash: bool = False


class CheckVisitSlotsToolInput(BaseModel):
    project_id: uuid.UUID = Field(..., description="Project UUID to check slots for")
    target_date: date = Field(..., description="Date for appointment (YYYY-MM-DD)")


class BookSiteVisitToolInput(BaseModel):
    customer_id: uuid.UUID = Field(..., description="Customer UUID")
    project_id: uuid.UUID = Field(..., description="Project UUID")
    unit_id: Optional[uuid.UUID] = Field(None, description="Optional specific unit UUID")
    scheduled_start: datetime = Field(..., description="Visit start timestamp (ISO 8601)")
    scheduled_end: Optional[datetime] = None
    assigned_agent_name: Optional[str] = "Senior Sales Advisor"
    customer_notes: Optional[str] = None


class RescheduleSiteVisitToolInput(BaseModel):
    visit_id: uuid.UUID = Field(..., description="Visit appointment UUID")
    new_scheduled_start: datetime = Field(..., description="New start timestamp")
    new_scheduled_end: Optional[datetime] = None
    reschedule_reason: Optional[str] = None


class CancelSiteVisitToolInput(BaseModel):
    visit_id: uuid.UUID = Field(..., description="Visit appointment UUID to cancel")
    cancellation_reason: Optional[str] = None


class TransferToHumanToolInput(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    customer_phone: Optional[str] = None
    reason: str = Field(..., description="Reason for handoff ticket request (e.g. complex legal question, customer request)")
    department: str = Field(default="sales", description="Target department e.g. 'sales', 'support', 'escalations'")
    conversation_summary: Optional[str] = None


class QueryActiveDatasetToolInput(BaseModel):
    query: str = Field(..., description="Natural language search inquiry, e.g. 'DLF 2BHK in Gurugram' or 'Godrej projects with clubhouse'")
    developer: Optional[str] = Field(None, description="Developer or company name e.g. 'DLF', 'Godrej', 'Lodha'")
    city: Optional[str] = Field(None, description="City or primary location e.g. 'Gurugram', 'Mumbai', 'Bengaluru'")
    configuration: Optional[str] = Field(None, description="BHK or layout e.g. '2BHK', '3BHK', 'Penthouse'")
    limit: int = Field(default=4, ge=1, le=10, description="Max matching records to return")


# Alias for explicit handoff semantics
RequestHumanHandoffToolInput = TransferToHumanToolInput


# -----------------------------------------------------------------------------
# Tool Standard Envelope Response
# -----------------------------------------------------------------------------

class AgentToolResponse(BaseModel):
    tool_name: str
    success: bool
    data: Optional[Any] = None
    error_message: Optional[str] = None
    anti_hallucination_guidance: str = Field(
        default="State only the facts returned in 'data'. Do not quote details, prices or units not present in data."
    )
