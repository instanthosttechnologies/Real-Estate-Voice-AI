"""Add dynamic dataset grounding tables.

Revision ID: 0006_dynamic_dataset_grounding
Revises: 0005_secure_customer_otp

Creates dynamic_datasets and dynamic_dataset_records tables
for dynamic schema ingestion, versioning, and voice grounding.
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from app.db.types import GUID, JSONCompat

revision: str = "0006_dynamic_dataset_grounding"
down_revision: str | None = "0005_secure_customer_otp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create dynamic_datasets table
    op.create_table(
        "dynamic_datasets",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("uploaded_by_user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("primary_sheet", sa.String(length=100), nullable=False, server_default="Unified_AI_Dataset"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_registry", JSONCompat(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dynamic_datasets_file_hash", "dynamic_datasets", ["file_hash"])
    op.create_index("ix_dynamic_datasets_is_active", "dynamic_datasets", ["is_active"])
    op.create_index("ix_dynamic_datasets_uploaded_by_user_id", "dynamic_datasets", ["uploaded_by_user_id"])

    # 2. Create dynamic_dataset_records table
    op.create_table(
        "dynamic_dataset_records",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("dataset_id", GUID(), sa.ForeignKey("dynamic_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_name", sa.String(length=100), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("record_identifier", sa.String(length=100), nullable=True),
        sa.Column("raw_data", JSONCompat(), nullable=False),
        sa.Column("normalized_search", JSONCompat(), nullable=False),
        sa.Column("voice_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_dynamic_dataset_records_dataset_id", "dynamic_dataset_records", ["dataset_id"])
    op.create_index("ix_dynamic_dataset_records_sheet_name", "dynamic_dataset_records", ["sheet_name"])
    op.create_index("ix_dynamic_dataset_records_record_identifier", "dynamic_dataset_records", ["record_identifier"])


def downgrade() -> None:
    op.drop_table("dynamic_dataset_records")
    op.drop_table("dynamic_datasets")
