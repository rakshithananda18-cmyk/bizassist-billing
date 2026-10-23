"""ft_task_invoices — link tasks to the billing invoices they deliver or collect.

Additive only: one new `ft_*` table. `invoice_id` points at billing's
`invoices.id` without a foreign key, because that table belongs to billing's
own Alembic chain. On Postgres it gets the same fail-closed tenant policy as
every other ft_* table (0001_ft_initial).

Revision ID: 0002_ft_task_invoices
Revises: 0001_ft_initial
Create Date: 2026-10-23 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002_ft_task_invoices'
down_revision = '0001_ft_initial'
branch_labels = None
depends_on = None

TABLE = "ft_task_invoices"
BID = "nullif(current_setting('app.current_business_id', true), '')::integer"


def upgrade() -> None:
    op.create_table(TABLE,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('invoice_id', sa.Integer(), nullable=False),
    sa.Column('invoice_number', sa.String(), nullable=True),
    sa.Column('invoice_date', sa.String(), nullable=True),
    sa.Column('total', sa.Float(), nullable=True),
    sa.Column('balance_due', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['ft_tasks.id'], name=op.f('fk_ft_task_invoices_task_id_ft_tasks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_task_invoices')),
    sa.UniqueConstraint('task_id', 'invoice_id', name='uq_ft_task_invoices_task_invoice')
    )
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.create_index('ix_ft_task_invoices_business_invoice', ['business_id', 'invoice_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ft_task_invoices_task_id'), ['task_id'], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON public.{TABLE};")
        op.execute(f"""
            CREATE POLICY {TABLE}_tenant_isolation ON public.{TABLE}
            USING (business_id = {BID})
            WITH CHECK (business_id = {BID});
        """)


def downgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_task_invoices_task_id'))
        batch_op.drop_index('ix_ft_task_invoices_business_invoice')

    op.drop_table(TABLE)
