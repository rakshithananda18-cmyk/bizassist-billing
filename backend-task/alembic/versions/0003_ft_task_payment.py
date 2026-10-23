"""ft_tasks.payment_mode / payment_ref — how a field collection was paid.

Additive only: two nullable columns. Billing uses them when the owner confirms
the collection in Contacts & Payments.

Revision ID: 0003_ft_task_payment
Revises: 0002_ft_task_invoices
Create Date: 2026-10-23 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003_ft_task_payment'
down_revision = '0002_ft_task_invoices'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ft_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_mode', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('payment_ref', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ft_tasks', schema=None) as batch_op:
        batch_op.drop_column('payment_ref')
        batch_op.drop_column('payment_mode')
