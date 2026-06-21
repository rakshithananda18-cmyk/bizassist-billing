"""add business_settings (Business Template System, Phase 1B)

Additive + backward-compatible: a brand-new table only. One row per business
holds its chosen vertical `template_key` and the owner's JSON `overrides`. The
effective config is computed at read time (template ⊕ overrides). Nothing
existing is touched, so all current data and tests are unaffected.

Revision ID: a4c9d2e7b3f1
Revises: f3b8c1e6a2d7
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "a4c9d2e7b3f1"
down_revision = "f3b8c1e6a2d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(), nullable=False, server_default="general"),
        sa.Column("overrides", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("business_id", name="uq_business_settings_biz"),
    )
    op.create_index("ix_business_settings_id", "business_settings", ["id"])
    op.create_index("ix_business_settings_business_id", "business_settings", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_business_settings_business_id", table_name="business_settings")
    op.drop_index("ix_business_settings_id", table_name="business_settings")
    op.drop_table("business_settings")
