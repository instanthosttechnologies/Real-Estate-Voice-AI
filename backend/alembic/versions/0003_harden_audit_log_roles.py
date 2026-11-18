"""harden audit log least privilege roles and permissions

Revision ID: 0003_harden_audit_log_roles
Revises: 0002_phase4_security_tokens
Create Date: 2026-11-13 16:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003_harden_audit_log_roles'
down_revision: Union[str, None] = '0002_phase4_security_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Restrict execution of the tampering function to prevent manual invocation or modification
        op.execute("""
            REVOKE ALL ON FUNCTION prevent_audit_log_tampering() FROM PUBLIC;
        """)

        # Ensure the trigger function is owned by current superuser/migrator
        op.execute("""
            ALTER FUNCTION prevent_audit_log_tampering() OWNER TO CURRENT_USER;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            GRANT EXECUTE ON FUNCTION prevent_audit_log_tampering() TO PUBLIC;
        """)
