"""add seller_invoice_id to b2b_orders (Phase 4 order→invoice sync)

Links a completed B2B order to the seller's sale invoice it posted; presence is
the exactly-once guard. Additive, nullable — safe online migration.

Revision ID: d6f2b4a8e913
Revises: c5e1a9d4f7b2
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'd6f2b4a8e913'
down_revision = 'c5e1a9d4f7b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('b2b_orders') as batch:
        batch.add_column(sa.Column('seller_invoice_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('b2b_orders') as batch:
        batch.drop_column('seller_invoice_id')
