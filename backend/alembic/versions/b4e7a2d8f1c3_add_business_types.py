"""add business_types (multi-type business, invoice-template system Phase 2)

business_settings.business_types — ordered JSON list of vertical keys; first is
the primary and always mirrors template_key. NULL resolves lazily to
[template_key] (core/templates/loader.resolve_billing_profile), so there is no
data backfill and existing single-type businesses behave exactly as before.
Mirrored for local SQLite in database/migration.py (_COLUMN_MIGRATIONS).

Revision ID: b4e7a2d8f1c3
Revises: a8d3f1c9e5b7
"""
from alembic import op
import sqlalchemy as sa

revision = "b4e7a2d8f1c3"
down_revision = "a8d3f1c9e5b7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("business_settings", sa.Column("business_types", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("business_settings", "business_types")
