import uuid
from datetime import datetime
from typing import Optional
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
    Schema for Total Customer Details Table.
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
