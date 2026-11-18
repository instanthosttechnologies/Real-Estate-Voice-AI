import logging
from typing import Any, Dict, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("audit")


async def record_audit_log(
    db: AsyncSession,
    user_id: Optional[UUID],
    user_role: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Records an immutable audit event in the database and structured logger.
    """
    from app.models.audit_log import AuditLog

    audit_entry = AuditLog(
        user_id=user_id,
        user_role=user_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        meta_info=metadata or {},
    )
    db.add(audit_entry)
    await db.flush()

    logger.info(
        f"[AUDIT] user={user_id} role={user_role} action={action} "
        f"resource={resource_type}:{resource_id} ip={ip_address}"
    )


def record_audit_log_sync(
    db: Any,
    user_id: Optional[UUID],
    user_role: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    meta_info: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Synchronous helper to record an immutable audit event in the database.
    """
    from datetime import datetime, timezone
    from app.models.audit_log import AuditLog

    audit_entry = AuditLog(
        user_id=user_id,
        user_role=user_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        meta_info=meta_info or {},
        timestamp=datetime.now(timezone.utc),
    )
    db.add(audit_entry)
    db.commit()
    logger.info(
        f"[AUDIT] user={user_id} role={user_role} action={action} "
        f"resource={resource_type}:{resource_id} ip={ip_address}"
    )
    return audit_entry
