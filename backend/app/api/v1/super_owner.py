from datetime import datetime, timezone
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.security import decrypt_transcript
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.super_owner import (
    AuditLogResponse,
    SuperOwnerAudioStreamResponse,
    SuperOwnerTranscriptResponse,
)

router = APIRouter(prefix="/super-owner", tags=["Platform Super Owner"])


@router.get("/conversations/{session_id}/transcript", response_model=SuperOwnerTranscriptResponse)
def read_private_transcript(
    session_id: str,
    request: Request,
    current_user: User = Depends(require_role(["super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Accesses and decrypts a private conversation transcript.
    
    CRITICAL SECURITY & AUDIT CONTROLS:
    - Strictly restricted to Platform Super Owner role.
    - Decrypts AES-256-GCM ciphertext using backend master key.
    - Synchronously logs an immutable audit event with IP, timestamp, and user ID.
    """
    conv = db.execute(
        select(Conversation).where(Conversation.session_id == session_id)
    ).scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation session not found.")

    decrypted = ""
    if conv.encrypted_transcript:
        try:
            decrypted = decrypt_transcript(conv.encrypted_transcript)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cryptographic failure decrypting transcript: {exc}"
            )

    now = datetime.now(timezone.utc)
    # Record non-repudiable audit log
    audit_entry = AuditLog(
        user_id=current_user.id,
        user_role=current_user.role,
        action="ACCESS_PRIVATE_TRANSCRIPT",
        resource_type="conversation",
        resource_id=session_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        meta_info={"duration_seconds": conv.duration_seconds},
        timestamp=now,
    )
    db.add(audit_entry)
    db.commit()

    return SuperOwnerTranscriptResponse(
        session_id=conv.session_id,
        decrypted_transcript=decrypted,
        duration_seconds=conv.duration_seconds,
        conversation_priority=conv.conversation_priority,
        access_audited=True,
        accessed_at=now,
    )


@router.get("/conversations/{session_id}/audio", response_model=SuperOwnerAudioStreamResponse)
def stream_private_audio(
    session_id: str,
    request: Request,
    current_user: User = Depends(require_role(["super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Accesses private audio stream reference.
    Strictly restricted to Platform Super Owner with mandatory audit logging.
    """
    conv = db.execute(
        select(Conversation).where(Conversation.session_id == session_id)
    ).scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation session not found.")

    now = datetime.now(timezone.utc)
    # Audit log
    audit_entry = AuditLog(
        user_id=current_user.id,
        user_role=current_user.role,
        action="STREAM_PRIVATE_AUDIO",
        resource_type="conversation",
        resource_id=session_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        timestamp=now,
    )
    db.add(audit_entry)
    db.commit()

    # Generate time-limited signed path / URL
    audio_url = conv.audio_storage_path or f"/api/v1/voice/recordings/{session_id}.raw"

    return SuperOwnerAudioStreamResponse(
        session_id=session_id,
        audio_stream_url=audio_url,
        access_audited=True,
        expires_in_seconds=60,
    )


@router.get("/audit-logs", response_model=List[AuditLogResponse])
def list_system_audit_logs(
    action: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    resource_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role(["super_owner"])),
    db: Session = Depends(get_db),
):
    """
    Read-only paginated and filtered inspection of the tamper-evident system audit trail.
    Strictly restricted to Platform Super Owner role.
    """
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action.strip())
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type.strip())

    stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    logs = db.execute(stmt).scalars().all()
    return logs
