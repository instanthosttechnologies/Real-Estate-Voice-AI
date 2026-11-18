"""initial normalized real estate schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-13 13:18:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Platform-independent UUID column type
UUID_TYPE = sa.UUID(as_uuid=True)


def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, default='customer'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 2. companies
    op.create_table(
        'companies',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('registration_number', sa.String(100), unique=True, nullable=True),
        sa.Column('contact_email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 3. locations
    op.create_table(
        'locations',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('address_line_1', sa.String(255), nullable=False),
        sa.Column('address_line_2', sa.String(255), nullable=True),
        sa.Column('city', sa.String(100), nullable=False, index=True),
        sa.Column('state', sa.String(100), nullable=False, index=True),
        sa.Column('postal_code', sa.String(20), nullable=False, index=True),
        sa.Column('country', sa.String(100), nullable=False, default='USA'),
        sa.Column('latitude', sa.Numeric(10, 7), nullable=True),
        sa.Column('longitude', sa.Numeric(10, 7), nullable=True),
        sa.Column('landmark', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 4. projects
    op.create_table(
        'projects',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('company_id', UUID_TYPE, sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('location_id', UUID_TYPE, sa.ForeignKey('locations.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False, index=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='UTC'),
        sa.Column('status', sa.String(50), nullable=False, default='under_construction'),
        sa.Column('launch_date', sa.Date(), nullable=True),
        sa.Column('completion_date', sa.Date(), nullable=True),
        sa.Column('total_phases', sa.Integer(), nullable=False, default=1),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('company_id', 'name', name='uq_project_company_name'),
    )

    # 5. amenities
    op.create_table(
        'amenities',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
    )

    # 6. project_amenities
    op.create_table(
        'project_amenities',
        sa.Column('project_id', UUID_TYPE, sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('amenity_id', UUID_TYPE, sa.ForeignKey('amenities.id', ondelete='CASCADE'), primary_key=True),
    )

    # 7. properties
    op.create_table(
        'properties',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('project_id', UUID_TYPE, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('property_type', sa.String(50), nullable=False, default='apartment'),
        sa.Column('total_floors', sa.Integer(), nullable=True),
        sa.Column('construction_status', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('project_id', 'name', name='uq_property_project_name'),
    )

    # 8. property_units
    op.create_table(
        'property_units',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('property_id', UUID_TYPE, sa.ForeignKey('properties.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('unit_number', sa.String(50), nullable=False),
        sa.Column('floor_number', sa.Integer(), nullable=True),
        sa.Column('configuration_type', sa.String(50), nullable=False, index=True),
        sa.Column('carpet_area_sqft', sa.Numeric(10, 2), nullable=False),
        sa.Column('super_built_up_area_sqft', sa.Numeric(10, 2), nullable=True),
        sa.Column('facing', sa.String(50), nullable=True),
        sa.Column('balcony_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('property_id', 'unit_number', name='uq_unit_property_number'),
        sa.CheckConstraint('carpet_area_sqft > 0', name='chk_positive_carpet_area'),
    )

    # 9. pricing (historical tracking)
    op.create_table(
        'pricing',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('unit_id', UUID_TYPE, sa.ForeignKey('property_units.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('base_price', sa.Numeric(14, 2), nullable=False),
        sa.Column('currency', sa.String(10), nullable=False, default='USD'),
        sa.Column('maintenance_charge_monthly', sa.Numeric(10, 2), nullable=False, default=0),
        sa.Column('parking_charge', sa.Numeric(10, 2), nullable=False, default=0),
        sa.Column('estimated_tax', sa.Numeric(10, 2), nullable=False, default=0),
        sa.Column('total_estimated_price', sa.Numeric(14, 2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True, index=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('base_price >= 0', name='chk_non_negative_base_price'),
        sa.CheckConstraint('total_estimated_price >= 0', name='chk_non_negative_total_price'),
    )

    # 10. availability (historical tracking)
    op.create_table(
        'availability',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('unit_id', UUID_TYPE, sa.ForeignKey('property_units.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', sa.String(50), nullable=False, default='available', index=True),
        sa.Column('available_from', sa.Date(), nullable=True),
        sa.Column('hold_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False, default=True, index=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 11. customers
    op.create_table(
        'customers',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('user_id', UUID_TYPE, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 12. leads
    op.create_table(
        'leads',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('customer_id', UUID_TYPE, sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('project_id', UUID_TYPE, sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('preferred_config', sa.String(50), nullable=True),
        sa.Column('budget_min', sa.Numeric(14, 2), nullable=True),
        sa.Column('budget_max', sa.Numeric(14, 2), nullable=True),
        sa.Column('preferred_location', sa.String(255), nullable=True),
        sa.Column('lead_priority', sa.String(50), nullable=False, default='medium', index=True),
        sa.Column('qualification_status', sa.String(50), nullable=False, default='unqualified', index=True),
        sa.Column('source', sa.String(50), nullable=False, default='voice_ai'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 13. site_visits
    op.create_table(
        'site_visits',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('customer_id', UUID_TYPE, sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('project_id', UUID_TYPE, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('unit_id', UUID_TYPE, sa.ForeignKey('property_units.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, default='scheduled', index=True),
        sa.Column('assigned_agent_name', sa.String(255), nullable=True),
        sa.Column('customer_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # 14. conversations (AES-256-GCM transcript ciphertext)
    op.create_table(
        'conversations',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('customer_id', UUID_TYPE, sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('session_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=False, default=0),
        sa.Column('conversation_priority', sa.String(50), nullable=False, default='medium', index=True),
        sa.Column('audio_storage_path', sa.String(500), nullable=True),
        sa.Column('encrypted_transcript', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
    )

    # 15. audit_logs
    op.create_table(
        'audit_logs',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('user_id', UUID_TYPE, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('user_role', sa.String(50), nullable=False),
        sa.Column('action', sa.String(100), nullable=False, index=True),
        sa.Column('resource_type', sa.String(100), nullable=False, index=True),
        sa.Column('resource_id', sa.String(255), nullable=False, index=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('meta_info', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, index=True),
    )

    # 16. ingestion_batches
    op.create_table(
        'ingestion_batches',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_format', sa.String(20), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False, index=True),
        sa.Column('uploaded_by_user_id', UUID_TYPE, sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('status', sa.String(50), nullable=False, default='pending_mapping', index=True),
        sa.Column('total_rows', sa.Integer(), nullable=False, default=0),
        sa.Column('imported_rows', sa.Integer(), nullable=False, default=0),
        sa.Column('skipped_rows', sa.Integer(), nullable=False, default=0),
        sa.Column('failed_rows', sa.Integer(), nullable=False, default=0),
        sa.Column('error_summary', sa.JSON(), nullable=True),
        sa.Column('mapping_config', sa.JSON(), nullable=True),
        sa.Column('can_rollback', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # 17. ingestion_records
    op.create_table(
        'ingestion_records',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('batch_id', UUID_TYPE, sa.ForeignKey('ingestion_batches.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('entity_type', sa.String(50), nullable=False, index=True),
        sa.Column('entity_id', UUID_TYPE, nullable=False, index=True),
        sa.Column('source_row_index', sa.Integer(), nullable=False),
        sa.Column('action_taken', sa.String(50), nullable=False),
        sa.Column('previous_state', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('ingestion_records')
    op.drop_table('ingestion_batches')
    op.drop_table('audit_logs')
    op.drop_table('conversations')
    op.drop_table('site_visits')
    op.drop_table('leads')
    op.drop_table('customers')
    op.drop_table('availability')
    op.drop_table('pricing')
    op.drop_table('property_units')
    op.drop_table('properties')
    op.drop_table('project_amenities')
    op.drop_table('amenities')
    op.drop_table('projects')
    op.drop_table('locations')
    op.drop_table('companies')
    op.drop_table('users')
