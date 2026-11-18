import uuid
from typing import Any, Dict, Optional
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, utc_now
from app.db.types import GUID, JSONCompat


class AuditLogTamperingError(RuntimeError):
    """Raised when an attempt is made to update or delete an immutable audit log entry."""
    pass


class AuditLog(Base):
    """
    Immutable audit trail recording access to sensitive records (transcripts, audio, rollbacks).
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_role: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    meta_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONCompat(), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)

    # Relationships
    user = relationship("User", back_populates="audit_logs")


@event.listens_for(AuditLog, "before_update")
def prevent_audit_log_update(mapper, connection, target):
    raise AuditLogTamperingError("Audit logs are strictly immutable and cannot be updated.")


@event.listens_for(AuditLog, "before_delete")
def prevent_audit_log_delete(mapper, connection, target):
    raise AuditLogTamperingError("Audit logs are strictly immutable and cannot be deleted.")


@event.listens_for(AuditLog.__table__, "after_create")
def create_sqlite_audit_triggers(target, connection, **kw):
    if connection.dialect.name == "sqlite":
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update "
            "BEFORE UPDATE ON audit_logs BEGIN "
            "SELECT RAISE(ABORT, 'Audit logs are immutable and cannot be updated.'); END;"
        ))
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete "
            "BEFORE DELETE ON audit_logs BEGIN "
            "SELECT RAISE(ABORT, 'Audit logs are immutable and cannot be deleted.'); END;"
        ))
