"""Add secure Email and SMS OTP fields to customers.

Revision ID: 0005_secure_customer_otp
Revises: 0004_cust_onboard_verify

This migration adds OTP security fields without deleting
existing customer records or legacy OTP columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.types import GUID

# Alembic revision identifiers
revision: str = "0005_secure_customer_otp"

down_revision: str | None = "0004_cust_onboard_verify"

branch_labels: str | Sequence[str] | None = None

depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add secure OTP tracking fields."""

    op.add_column(
        "customers",
        sa.Column(
            "otp_hash",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.add_column(
        "customers",
        sa.Column(
            "otp_channel",
            sa.String(length=10),
            nullable=True,
        ),
    )

    op.add_column(
        "customers",
        sa.Column(
            "otp_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    op.add_column(
        "customers",
        sa.Column(
            "otp_last_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "customers",
        sa.Column(
            "otp_locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "customers",
        sa.Column(
            "otp_challenge_id",
            GUID(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove only fields introduced by this migration."""

    op.drop_column(
        "customers",
        "otp_challenge_id",
    )

    op.drop_column(
        "customers",
        "otp_locked_until",
    )

    op.drop_column(
        "customers",
        "otp_last_requested_at",
    )

    op.drop_column(
        "customers",
        "otp_attempts",
    )

    op.drop_column(
        "customers",
        "otp_channel",
    )

    op.drop_column(
        "customers",
        "otp_hash",
    )
