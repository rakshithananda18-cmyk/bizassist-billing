"""create_rls_policies

Revision ID: d7e3a9c6f8b1
Revises: aea3a6d76429
Create Date: 2026-06-25 14:35:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd7e3a9c6f8b1'
down_revision = 'aea3a6d76429'
branch_labels = None
depends_on = None

# Tables with direct business_id scoping
DIRECT_SCOPED_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks", "idempotency_keys", "stock_ledger",
    "business_settings", "uploaded_files", "chat_messages", "document_embeddings",
    "token_usage", "rate_limit_configs", "alert_configs", "action_log", "feedback",
    "query_override", "business_facts"
]

def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Direct scoped tables
        for table in DIRECT_SCOPED_TABLES:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table};")
            op.execute(f"""
                CREATE POLICY tenant_isolation ON public.{table}
                USING (
                    nullif(current_setting('app.current_business_id', true), '') IS NULL
                    OR business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                );
            """)

        # 2. Users table policy
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON public.users;")
        op.execute("""
            CREATE POLICY users_tenant_isolation ON public.users
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR id = nullif(current_setting('app.current_business_id', true), '')::integer
                OR parent_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
            );
        """)

        # 3. B2B Connections
        op.execute("ALTER TABLE public.b2b_connections FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS b2b_connections_tenant_isolation ON public.b2b_connections;")
        op.execute("""
            CREATE POLICY b2b_connections_tenant_isolation ON public.b2b_connections
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR buyer_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                OR seller_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
            );
        """)

        # 4. Connection Codes
        op.execute("ALTER TABLE public.connection_codes FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS connection_codes_tenant_isolation ON public.connection_codes;")
        op.execute("""
            CREATE POLICY connection_codes_tenant_isolation ON public.connection_codes
            USING (true)
            WITH CHECK (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR seller_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
            );
        """)

        # 5. B2B Orders
        op.execute("ALTER TABLE public.b2b_orders FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS b2b_orders_tenant_isolation ON public.b2b_orders;")
        op.execute("""
            CREATE POLICY b2b_orders_tenant_isolation ON public.b2b_orders
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR buyer_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                OR seller_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
            );
        """)

        # 6. Shared Ledgers
        op.execute("ALTER TABLE public.shared_ledgers FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS shared_ledgers_tenant_isolation ON public.shared_ledgers;")
        op.execute("""
            CREATE POLICY shared_ledgers_tenant_isolation ON public.shared_ledgers
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR buyer_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                OR seller_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
            );
        """)

        # 7. Child Tables
        # invoice_line_items
        op.execute("ALTER TABLE public.invoice_line_items FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS invoice_line_items_tenant_isolation ON public.invoice_line_items;")
        op.execute("""
            CREATE POLICY invoice_line_items_tenant_isolation ON public.invoice_line_items
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.invoices i 
                    WHERE i.id = invoice_line_items.invoice_id 
                    AND i.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)

        # purchase_order_line_items
        op.execute("ALTER TABLE public.purchase_order_line_items FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS purchase_order_line_items_tenant_isolation ON public.purchase_order_line_items;")
        op.execute("""
            CREATE POLICY purchase_order_line_items_tenant_isolation ON public.purchase_order_line_items
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.purchase_orders po 
                    WHERE po.id = purchase_order_line_items.purchase_order_id 
                    AND po.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)

        # purchase_invoice_line_items
        op.execute("ALTER TABLE public.purchase_invoice_line_items FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS purchase_invoice_line_items_tenant_isolation ON public.purchase_invoice_line_items;")
        op.execute("""
            CREATE POLICY purchase_invoice_line_items_tenant_isolation ON public.purchase_invoice_line_items
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.purchase_invoices pi 
                    WHERE pi.id = purchase_invoice_line_items.purchase_invoice_id 
                    AND pi.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)

        # stock_transfer_line_items
        op.execute("ALTER TABLE public.stock_transfer_line_items FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS stock_transfer_line_items_tenant_isolation ON public.stock_transfer_line_items;")
        op.execute("""
            CREATE POLICY stock_transfer_line_items_tenant_isolation ON public.stock_transfer_line_items
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.stock_transfers st 
                    WHERE st.id = stock_transfer_line_items.stock_transfer_id 
                    AND st.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)

        # journal_lines
        op.execute("ALTER TABLE public.journal_lines FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS journal_lines_tenant_isolation ON public.journal_lines;")
        op.execute("""
            CREATE POLICY journal_lines_tenant_isolation ON public.journal_lines
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.journal_entries je 
                    WHERE je.id = journal_lines.journal_entry_id 
                    AND je.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)

        # b2b_order_line_items
        op.execute("ALTER TABLE public.b2b_order_line_items FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS b2b_order_line_items_tenant_isolation ON public.b2b_order_line_items;")
        op.execute("""
            CREATE POLICY b2b_order_line_items_tenant_isolation ON public.b2b_order_line_items
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.b2b_orders o 
                    WHERE o.id = b2b_order_line_items.b2b_order_id 
                    AND (
                        o.buyer_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                        OR o.seller_business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                    )
                )
            );
        """)

        # invoice_payments
        op.execute("ALTER TABLE public.invoice_payments FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS invoice_payments_tenant_isolation ON public.invoice_payments;")
        op.execute("""
            CREATE POLICY invoice_payments_tenant_isolation ON public.invoice_payments
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.invoices i 
                    WHERE i.id = invoice_payments.invoice_id 
                    AND i.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
                OR EXISTS (
                    SELECT 1 FROM public.payments p 
                    WHERE p.id = invoice_payments.payment_id 
                    AND p.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)

        # product_barcodes
        op.execute("ALTER TABLE public.product_barcodes FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS product_barcodes_tenant_isolation ON public.product_barcodes;")
        op.execute("""
            CREATE POLICY product_barcodes_tenant_isolation ON public.product_barcodes
            USING (
                nullif(current_setting('app.current_business_id', true), '') IS NULL
                OR EXISTS (
                    SELECT 1 FROM public.products p 
                    WHERE p.id = product_barcodes.product_id 
                    AND p.business_id = nullif(current_setting('app.current_business_id', true), '')::integer
                )
            );
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Direct scoped tables
        for table in DIRECT_SCOPED_TABLES:
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table};")

        # 2. Users
        op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON public.users;")

        # 3. B2B Connections
        op.execute("ALTER TABLE public.b2b_connections NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS b2b_connections_tenant_isolation ON public.b2b_connections;")

        # 4. Connection Codes
        op.execute("ALTER TABLE public.connection_codes NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS connection_codes_tenant_isolation ON public.connection_codes;")

        # 5. B2B Orders
        op.execute("ALTER TABLE public.b2b_orders NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS b2b_orders_tenant_isolation ON public.b2b_orders;")

        # 6. Shared Ledgers
        op.execute("ALTER TABLE public.shared_ledgers NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS shared_ledgers_tenant_isolation ON public.shared_ledgers;")

        # 7. Child Tables
        op.execute("ALTER TABLE public.invoice_line_items NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS invoice_line_items_tenant_isolation ON public.invoice_line_items;")

        op.execute("ALTER TABLE public.purchase_order_line_items NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS purchase_order_line_items_tenant_isolation ON public.purchase_order_line_items;")

        op.execute("ALTER TABLE public.purchase_invoice_line_items NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS purchase_invoice_line_items_tenant_isolation ON public.purchase_invoice_line_items;")

        op.execute("ALTER TABLE public.stock_transfer_line_items NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS stock_transfer_line_items_tenant_isolation ON public.stock_transfer_line_items;")

        op.execute("ALTER TABLE public.journal_lines NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS journal_lines_tenant_isolation ON public.journal_lines;")

        op.execute("ALTER TABLE public.b2b_order_line_items NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS b2b_order_line_items_tenant_isolation ON public.b2b_order_line_items;")

        op.execute("ALTER TABLE public.invoice_payments NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS invoice_payments_tenant_isolation ON public.invoice_payments;")

        op.execute("ALTER TABLE public.product_barcodes NO FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS product_barcodes_tenant_isolation ON public.product_barcodes;")
