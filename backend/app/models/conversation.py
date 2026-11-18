import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, utc_now
from app.db.types import GUID


class Conversation(Base):
    """
    Stores conversational metadata and AES-256-GCM encrypted transcripts.
    Transcripts and audio paths are never directly queried by Admin endpoints.
    """
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversation_priority: Mapped[str] = mapped_column(
        String(50), default="medium", index=True, nullable=False
    )  # 'low', 'medium', 'high', 'urgent'
    audio_storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    encrypted_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)

    # Relationships
    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="conversations")
