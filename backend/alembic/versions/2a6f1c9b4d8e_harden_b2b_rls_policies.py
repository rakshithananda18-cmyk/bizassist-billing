"""harden_b2b_rls_policies

Revision ID: 2a6f1c9b4d8e
Revises: 9c2f4b8a1d3e
Create Date: 2026-07-02 04:10:00.000000
"""
from alembic import op


revision = "2a6f1c9b4d8e"
down_revision = "9c2f4b8a1d3e"
branch_labels = None
depends_on = None


BID = "nullif(current_setting('app.current_business_id', true), '')::integer"

B2B_PAIR_SCOPED_TABLES = [
    "b2b_connections",
    "b2b_orders",
    "b2b_ledgers",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in B2B_PAIR_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON public.{table};")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON public.{table}
            USING (buyer_business_id = {BID} OR seller_business_id = {BID})
            WITH CHECK (buyer_business_id = {BID} OR seller_business_id = {BID});
        """)

    op.execute("ALTER TABLE public.b2b_invite_codes FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS b2b_invite_codes_tenant_isolation ON public.b2b_invite_codes;")
    op.execute(f"""
        CREATE POLICY b2b_invite_codes_tenant_isolation ON public.b2b_invite_codes
        USING (true)
        WITH CHECK (seller_business_id = {BID});
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Keep hardened RLS policies in place on downgrade.
    pass
