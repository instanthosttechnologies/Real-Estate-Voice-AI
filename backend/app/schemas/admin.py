import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class AdminConversationItem(BaseModel):
    """
    Schema for Conversation Priority Table.
    CRITICAL SECURITY & PRIVACY REQUIREMENT:
    Private transcripts and audio storage paths are strictly omitted from this model.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: str
    customer_id: Optional[uuid.UUID] = None
    customer_name: Optional[str] = None
    duration_seconds: int
    conversation_priority: str
    created_at: datetime


class AdminCustomerItem(BaseModel):
    """
    Schema for Total Customer Details Table (legacy/backward compatibility).
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: Optional[str] = None
    phone: str
    lead_priority: Optional[str] = None
    qualification_status: Optional[str] = None
    total_site_visits: int = 0
    created_at: datetime


# =============================================================================
# TABLE 1: ALL REGISTERED CUSTOMERS SCHEMAS
# =============================================================================

class AdminRegisteredCustomerItem(BaseModel):
    """
    Schema for All Registered Customers Table.
    Displays comprehensive operational customer profiles including lead preferences
    and conversational activity.
    """
    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    customer_name: str
    phone: str
    email: Optional[str] = None
    preferred_location: Optional[str] = None
    preferred_config: Optional[str] = None
    budget_display: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    registration_date: datetime
    total_conversations: int = 0
    last_conversation_date: Optional[datetime] = None
    is_verified: bool = False
    status: str = "Registered"  # e.g., "Verified", "Unverified", "Qualified"
    qualification_status: Optional[str] = None
    lead_priority: Optional[str] = None


class AdminRegisteredCustomersResponse(BaseModel):
    items: List[AdminRegisteredCustomerItem]
    total: int
    limit: int
    offset: int


# =============================================================================
# TABLE 2: CUSTOMER PRIORITY RANKING SCHEMAS
# =============================================================================

class AdminCustomerPriorityRankingItem(BaseModel):
    """
    Schema for Customer Priority Ranking Table.
    Ranks customers based on conversation duration, repeat engagement, and recency.
    Note: Numerical priority score is intentionally omitted per requirements.
    """
    model_config = ConfigDict(from_attributes=True)

    rank: int
    customer_id: uuid.UUID
    customer_name: str
    phone: str
    email: Optional[str] = None
    total_conversations: int
    repeat_conversations: int
    total_duration_seconds: int
    total_duration_formatted: str
    avg_duration_seconds: int
    avg_duration_formatted: str
    last_conversation_date: Optional[datetime] = None
    priority: str  # "High" | "Medium" | "Low"


class AdminCustomerPriorityRankingResponse(BaseModel):
    items: List[AdminCustomerPriorityRankingItem]
    total: int
    limit: int
    offset: int
    time_range: str


# =============================================================================
# CUSTOMER DETAILS ACTION MODAL SCHEMA
# =============================================================================

class AdminSiteVisitSummary(BaseModel):
    id: uuid.UUID
    project_name: Optional[str] = None
    scheduled_start: datetime
    status: str
    notes: Optional[str] = None


class AdminCustomerDetailResponse(BaseModel):
    """
    Detailed operational customer view for expanded row inspection.
    Strictly omits raw audio, transcripts, and credentials.
    """
    customer_id: uuid.UUID
    customer_name: str
    phone: str
    email: Optional[str] = None
    is_verified: bool
    registration_date: datetime
    preferred_location: Optional[str] = None
    interested_project: Optional[str] = None
    property_type: Optional[str] = None
    preferred_config: Optional[str] = None
    budget_display: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    lead_priority: Optional[str] = None
    qualification_status: Optional[str] = None
    notes: Optional[str] = None
    total_conversations: int = 0
    total_duration_formatted: str = "0s"
    avg_duration_formatted: str = "0s"
    recent_conversation_duration_formatted: Optional[str] = None
    repeat_conversations: int = 0
    last_conversation_date: Optional[datetime] = None
    priority_level: str = "Low"
    current_rank: Optional[int] = None
    engagement_summary: Optional[str] = None
    site_visit_status: Optional[str] = None
    last_site_visit_date: Optional[datetime] = None
    next_scheduled_visit: Optional[datetime] = None
    conversations: List[AdminConversationItem] = []
    site_visits: List[AdminSiteVisitSummary] = []

