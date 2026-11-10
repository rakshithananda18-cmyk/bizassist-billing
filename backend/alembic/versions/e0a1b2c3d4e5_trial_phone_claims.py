"""Retain first-time trial eligibility across account deletion.

Revision ID: e0a1b2c3d4e5
Revises: d9f1a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa

revision = "e0a1b2c3d4e5"
down_revision = "d9f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("trial_phone_claims"):
        op.create_table("trial_phone_claims",
                        sa.Column("phone_hash", sa.String(64), primary_key=True),
                        sa.Column("claimed_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("trial_phone_claims")
