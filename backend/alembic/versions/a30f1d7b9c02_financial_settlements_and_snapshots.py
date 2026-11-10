"""Add settlement facts, verified cost snapshots, immutable B2B quote policy and DN uniqueness.

Revision ID: a30f1d7b9c02
Revises: f7b8c9d0e1f2
"""
from alembic import op

revision = "a30f1d7b9c02"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    from core.accounting.settlement_schema import install_financial_schema
    install_financial_schema(op.get_bind())


def downgrade():
    # Financial facts and verified historical snapshots are intentionally retained.
    pass
