"""optimize_rls_init_plan

Revision ID: 3b7d5e0a9c1f
Revises: 2a6f1c9b4d8e
Create Date: 2026-07-02 05:10:00.000000
"""
from alembic import op


revision = "3b7d5e0a9c1f"
down_revision = "2a6f1c9b4d8e"
branch_labels = None
depends_on = None


DIRECT_SCOPED_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks", "idempotency_keys", "stock_ledger",
    "business_settings", "uploaded_files", "chat_messages", "document_embeddings",
    "token_usage", "rate_limit_configs", "alert_configs", "action_logs", "ai_feedback",
    "ai_query_overrides", "business_facts",
]


B2B_PAIR_SCOPED_TABLES = [
    "b2b_connections",
    "b2b_orders",
    "b2b_ledgers",
]


BID = "(select nullif(current_setting('app.current_business_id', true), '')::integer)"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in DIRECT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table};")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON public.{table}
            USING (business_id = {BID})
            WITH CHECK (business_id = {BID});
        """)

    op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON public.users;")
    op.execute(f"""
        CREATE POLICY users_tenant_isolation ON public.users
        USING (id = {BID} OR parent_business_id = {BID})
        WITH CHECK (id = {BID} OR parent_business_id = {BID});
    """)

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
        USING (seller_business_id = {BID} OR (is_used = false AND expires_at > now()))
        WITH CHECK (seller_business_id = {BID});
    """)

    child_policies = {
        "invoice_line_items": (
            "invoice_line_items_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.invoices i WHERE i.id = invoice_line_items.invoice_id AND i.business_id = {BID})",
        ),
        "purchase_order_line_items": (
            "purchase_order_line_items_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.purchase_orders po WHERE po.id = purchase_order_line_items.purchase_order_id AND po.business_id = {BID})",
        ),
        "purchase_invoice_line_items": (
            "purchase_invoice_line_items_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.purchase_invoices pi WHERE pi.id = purchase_invoice_line_items.purchase_invoice_id AND pi.business_id = {BID})",
        ),
        "stock_transfer_line_items": (
            "stock_transfer_line_items_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.stock_transfers st WHERE st.id = stock_transfer_line_items.transfer_id AND st.business_id = {BID})",
        ),
        "journal_lines": (
            "journal_lines_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.journal_entries je WHERE je.id = journal_lines.entry_id AND je.business_id = {BID})",
        ),
        "b2b_order_line_items": (
            "b2b_order_line_items_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.b2b_orders o WHERE o.id = b2b_order_line_items.order_id AND (o.buyer_business_id = {BID} OR o.seller_business_id = {BID}))",
        ),
        "invoice_payments": (
            "invoice_payments_tenant_isolation",
            f"business_id = {BID}",
        ),
        "product_barcodes": (
            "product_barcodes_tenant_isolation",
            f"EXISTS (SELECT 1 FROM public.products p WHERE p.id = product_barcodes.product_id AND p.business_id = {BID})",
        ),
    }

    for table, (policy, predicate) in child_policies.items():
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table};")
        op.execute(f"""
            CREATE POLICY {policy} ON public.{table}
            USING ({predicate});
        """)

    op.execute("DROP INDEX IF EXISTS public.ix_godowns_business;")
    op.execute("DROP INDEX IF EXISTS public.ix_stock_transfers_business;")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Keep optimized RLS policies in place on downgrade.
    pass
