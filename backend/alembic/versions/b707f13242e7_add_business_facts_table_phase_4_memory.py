"""add business_facts table (Phase 4 memory)

Revision ID: b707f13242e7
Revises: a7c4e9f02b13
Create Date: 2026-06-14 00:34:05.616902
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b707f13242e7'
down_revision = 'a7c4e9f02b13'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 4 - Proactive Memory: durable, distilled business facts.
    # Idempotent: skip if Base.metadata.create_all() already made the table
    # at app boot, so `alembic upgrade head` never collides with it.
    bind = op.get_bind()
    if sa.inspect(bind).has_table("business_facts"):
        return

    op.create_table(
        "business_facts",
        sa.Column("id",          sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("fact_key",    sa.String(),  nullable=False),
        sa.Column("category",    sa.String(),  nullable=True),
        sa.Column("fact_text",   sa.Text(),    nullable=False),
        sa.Column("confidence",  sa.Float(),   nullable=True, server_default="1.0"),
        sa.Column("created_at",  sa.DateTime(), nullable=True),
        sa.Column("updated_at",  sa.DateTime(), nullable=True),
        sa.UniqueConstraint("business_id", "fact_key", name="uq_business_facts_biz_key"),
    )
    op.create_index("ix_business_facts_id",         "business_facts", ["id"])
    op.create_index("ix_business_facts_business_id", "business_facts", ["business_id"])
    op.create_index("ix_business_facts_fact_key",    "business_facts", ["fact_key"])


def downgrade() -> None:
    op.drop_table("business_facts")
