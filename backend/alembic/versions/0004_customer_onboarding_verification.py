"""customer onboarding verification fields

Revision ID: 0004_cust_onboard_verify
Revises: 0003_harden_audit_log_roles
Create Date: 2026-11-17 15:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004_cust_onboard_verify'
down_revision: Union[str, None] = '0003_harden_audit_log_roles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('is_verified', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('customers', sa.Column('otp_code', sa.String(length=10), nullable=True))
    op.add_column('customers', sa.Column('otp_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('customers', 'otp_expires_at')
    op.drop_column('customers', 'otp_code')
    op.drop_column('customers', 'is_verified')
