"""Add tenant company isolation and universal dataset field approval columns.

Revision ID: 0007_universal_dataset_isolation
Revises: 0006_dynamic_dataset_grounding

Adds:
- company_id to users (tenant assignment for Admin accounts)
- company_id to dynamic_datasets (strict tenant boundary for datasets)
- approved_fields, field_labels, display_identifier, domain_name, welcome_greeting
  to dynamic_datasets for Admin schema approval and custom domain configuration.
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from app.db.types import GUID, JSONCompat

revision: str = "0007_universal_dataset_isolation"
down_revision: str | None = "0006_dynamic_dataset_grounding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add company_id to users table for Admin tenant association
    op.add_column(
        "users",
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_company_id", "users", ["company_id"])

    # 2. Add company_id and schema approval columns to dynamic_datasets
    op.add_column(
        "dynamic_datasets",
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=True,  # Backfilled on existing rows before setting NOT NULL
        ),
    )
    op.create_index("ix_dynamic_datasets_company_id", "dynamic_datasets", ["company_id"])

    op.add_column(
        "dynamic_datasets",
        sa.Column("approved_fields", JSONCompat(), nullable=True),
    )
    op.add_column(
        "dynamic_datasets",
        sa.Column("field_labels", JSONCompat(), nullable=True),
    )
    op.add_column(
        "dynamic_datasets",
        sa.Column("display_identifier", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "dynamic_datasets",
        sa.Column("domain_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "dynamic_datasets",
        sa.Column("welcome_greeting", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dynamic_datasets", "welcome_greeting")
    op.drop_column("dynamic_datasets", "domain_name")
    op.drop_column("dynamic_datasets", "display_identifier")
    op.drop_column("dynamic_datasets", "field_labels")
    op.drop_column("dynamic_datasets", "approved_fields")
    op.drop_index("ix_dynamic_datasets_company_id", table_name="dynamic_datasets")
    op.drop_column("dynamic_datasets", "company_id")

    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_column("users", "company_id")
