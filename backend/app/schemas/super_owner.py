import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class SuperOwnerTranscriptResponse(BaseModel):
    session_id: str
    decrypted_transcript: str
    duration_seconds: int
    conversation_priority: str
    access_audited: bool = True
    accessed_at: datetime


class SuperOwnerAudioStreamResponse(BaseModel):
    session_id: str
    audio_stream_url: str
    access_audited: bool = True
    expires_in_seconds: int = 60


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    user_role: str
    action: str
    resource_type: str
    resource_id: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    meta_info: Optional[Dict[str, Any]]
    timestamp: datetime
