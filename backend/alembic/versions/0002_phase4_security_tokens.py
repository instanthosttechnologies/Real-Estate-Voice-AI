"""phase4 refresh tokens and audit log immutability triggers

Revision ID: 0002_phase4_refresh_tokens_and_audit_trigger
Revises: 0001_initial_schema
Create Date: 2026-11-13 15:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002_phase4_security_tokens'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID_TYPE = sa.UUID(as_uuid=True)


def upgrade() -> None:
    # 1. Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('user_id', UUID_TYPE, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('token_hash', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('revoked', sa.Boolean(), default=False, nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 2. Database-level immutability triggers for audit_logs on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_audit_log_tampering()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Audit logs are strictly immutable and cannot be updated or deleted.';
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute("""
            CREATE TRIGGER trg_audit_logs_prevent_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_tampering();
        """)
        op.execute("""
            CREATE TRIGGER trg_audit_logs_prevent_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_tampering();
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_prevent_delete ON audit_logs;")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_prevent_update ON audit_logs;")
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_tampering();")

    op.drop_table('refresh_tokens')
