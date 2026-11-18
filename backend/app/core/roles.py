from enum import Enum
from typing import Set


class UserRole(str, Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    SUPER_OWNER = "super_owner"


# Permission scopes
ROLE_HIERARCHY = {
    UserRole.CUSTOMER: {
        "voice:interact",
        "customer:read_self",
        "site_visit:create_self",
    },
    UserRole.ADMIN: {
        "conversations:read_priority",
        "customers:read_all",
        "leads:manage",
        "site_visits:manage",
        "properties:read",
        "ingestion:view_status",
    },
    UserRole.SUPER_OWNER: {
        # Super Owner inherits admin rights plus audited access to private transcripts/audio and ingestion
        "conversations:read_priority",
        "customers:read_all",
        "leads:manage",
        "site_visits:manage",
        "properties:read",
        "properties:write",
        "conversations:read_transcript",  # Subject to audit logging
        "conversations:read_audio",       # Subject to audit logging
        "ingestion:manage",               # Upload, map, confirm, rollback
        "audit_logs:read",
        "users:manage",
    }
}


def has_permission(role: str, permission: str) -> bool:
    try:
        user_role = UserRole(role)
        return permission in ROLE_HIERARCHY.get(user_role, set())
    except ValueError:
        return False
