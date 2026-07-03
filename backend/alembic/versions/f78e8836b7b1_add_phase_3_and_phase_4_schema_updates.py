"""Add Phase 3 and Phase 4 schema updates

Revision ID: f78e8836b7b1
Revises: b4e7a2d8f1c3
Create Date: 2026-07-03 18:03:52.366511
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f78e8836b7b1'
down_revision = 'b4e7a2d8f1c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ── 1. Drop old-named indexes / constraints safely (IF EXISTS on PG, best-effort on SQLite) ──
    old_indexes = [
        # action_logs
        "ix_action_log_business_id", "ix_action_log_id",
        # ai_feedback
        "ix_feedback_business_id", "ix_feedback_id",
        # ai_query_overrides
        "ix_query_override_business_id", "ix_query_override_id", "ix_query_override_query_norm",
        # b2b_invite_codes
        "ix_connection_codes_code", "ix_connection_codes_id", "ix_connection_codes_seller_code",
        # b2b_ledgers
        "ix_shared_ledgers_id", "ix_shared_ledgers_seller_buyer",
        # godowns
        "ix_godowns_business",
        # stock_transfers
        "ix_stock_transfers_business",
    ]
    old_unique = [
        "uq_alert_configs_business_uid", "uq_business_settings_business_uid",
        "uq_customers_business_uid", "uq_expenses_business_uid",
        "uq_godowns_business_uid", "uq_inventory_business_uid",
        "uq_invoice_line_items_uid", "uq_invoice_payments_business_uid",
        "uq_invoices_business_uid", "uq_journal_entries_business_uid",
        "uq_payments_business_uid", "uq_period_locks_business_uid",
        "uq_product_barcodes_business_uid", "uq_products_business_uid",
        "uq_purchase_invoice_line_items_uid", "uq_purchase_invoices_business_uid",
        "uq_purchase_order_line_items_uid", "uq_purchase_orders_business_uid",
        "uq_query_override_biz_query", "uq_rate_limit_configs_business_uid",
        "uq_shared_ledgers_uid", "uq_stock_ledger_business_uid",
        "uq_stock_transfer_line_items_uid", "uq_stock_transfers_business_uid",
        "uq_vendors_business_uid",
    ]
    if is_pg:
        # On PG, unique constraints own their backing index — must drop constraint first.
        # Map each constraint name to the table it lives on.
        constraint_table_map = [
            ("uq_query_override_biz_query",          "ai_query_overrides"),
            ("uq_alert_configs_business_uid",         "alert_configs"),
            ("uq_business_settings_business_uid",     "business_settings"),
            ("uq_customers_business_uid",             "customers"),
            ("uq_expenses_business_uid",              "expenses"),
            ("uq_godowns_business_uid",               "godowns"),
            ("uq_inventory_business_uid",             "inventory"),
            ("uq_invoice_line_items_uid",             "invoice_line_items"),
            ("uq_invoice_payments_business_uid",      "invoice_payments"),
            ("uq_invoices_business_uid",              "invoices"),
            ("uq_journal_entries_business_uid",       "journal_entries"),
            ("uq_payments_business_uid",              "payments"),
            ("uq_period_locks_business_uid",          "period_locks"),
            ("uq_product_barcodes_business_uid",      "product_barcodes"),
            ("uq_products_business_uid",              "products"),
            ("uq_purchase_invoice_line_items_uid",    "purchase_invoice_line_items"),
            ("uq_purchase_invoices_business_uid",     "purchase_invoices"),
            ("uq_purchase_order_line_items_uid",      "purchase_order_line_items"),
            ("uq_purchase_orders_business_uid",       "purchase_orders"),
            ("uq_rate_limit_configs_business_uid",    "rate_limit_configs"),
            ("uq_shared_ledgers_uid",                 "b2b_ledgers"),
            ("uq_stock_ledger_business_uid",          "stock_ledger"),
            ("uq_stock_transfer_line_items_uid",      "stock_transfer_line_items"),
            ("uq_stock_transfers_business_uid",       "stock_transfers"),
            ("uq_vendors_business_uid",               "vendors"),
        ]
        # Drop constraints first (this also drops their backing indexes on PG)
        for constraint, tbl in constraint_table_map:
            op.execute(f'ALTER TABLE IF EXISTS {tbl} DROP CONSTRAINT IF EXISTS "{constraint}"')
        # Drop any remaining bare (non-constraint) indexes
        for idx in old_indexes:
            op.execute(f'DROP INDEX IF EXISTS "{idx}"')
    else:
        # SQLite: batch_alter_table handles it
        with op.batch_alter_table('action_logs', schema=None) as batch_op:
            try: batch_op.drop_index('ix_action_log_business_id')
            except Exception: pass
            try: batch_op.drop_index('ix_action_log_id')
            except Exception: pass
        with op.batch_alter_table('ai_feedback', schema=None) as batch_op:
            try: batch_op.drop_index('ix_feedback_business_id')
            except Exception: pass
            try: batch_op.drop_index('ix_feedback_id')
            except Exception: pass
        with op.batch_alter_table('ai_query_overrides', schema=None) as batch_op:
            try: batch_op.drop_index('ix_query_override_business_id')
            except Exception: pass
            try: batch_op.drop_index('ix_query_override_id')
            except Exception: pass
            try: batch_op.drop_index('ix_query_override_query_norm')
            except Exception: pass
            try: batch_op.drop_constraint('uq_query_override_biz_query', type_='unique')
            except Exception: pass
        with op.batch_alter_table('b2b_invite_codes', schema=None) as batch_op:
            try: batch_op.drop_index('ix_connection_codes_code')
            except Exception: pass
            try: batch_op.drop_index('ix_connection_codes_id')
            except Exception: pass
            try: batch_op.drop_index('ix_connection_codes_seller_code')
            except Exception: pass
        with op.batch_alter_table('b2b_ledgers', schema=None) as batch_op:
            try: batch_op.drop_index('ix_shared_ledgers_id')
            except Exception: pass
            try: batch_op.drop_index('ix_shared_ledgers_seller_buyer')
            except Exception: pass
            try: batch_op.drop_index('uq_shared_ledgers_uid')
            except Exception: pass
        for tbl in [
            'alert_configs', 'business_settings', 'customers', 'expenses',
            'godowns', 'inventory', 'invoice_line_items', 'invoice_payments',
            'invoices', 'journal_entries', 'payments', 'period_locks',
            'product_barcodes', 'products', 'purchase_invoice_line_items',
            'purchase_invoices', 'purchase_order_line_items', 'purchase_orders',
            'rate_limit_configs', 'stock_ledger', 'stock_transfer_line_items',
            'stock_transfers', 'vendors',
        ]:
            with op.batch_alter_table(tbl, schema=None) as batch_op:
                for uq in old_unique:
                    try: batch_op.drop_index(uq)
                    except Exception: pass
        with op.batch_alter_table('godowns', schema=None) as batch_op:
            try: batch_op.drop_index('ix_godowns_business')
            except Exception: pass
        with op.batch_alter_table('stock_transfers', schema=None) as batch_op:
            try: batch_op.drop_index('ix_stock_transfers_business')
            except Exception: pass

    # ── 2. Add new columns first (columns must exist before indexes can reference them) ──
    if is_pg:
        op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS uid_token VARCHAR")
        op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS print_template VARCHAR")
        op.execute("ALTER TABLE invoice_payments ADD COLUMN IF NOT EXISTS shift_id INTEGER")
        op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS shift_id INTEGER")
        op.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS shift_id INTEGER")
    else:
        with op.batch_alter_table('invoices', schema=None) as batch_op:
            batch_op.add_column(sa.Column('uid_token', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('print_template', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('shift_id', sa.Integer(), nullable=True))
        with op.batch_alter_table('invoice_payments', schema=None) as batch_op:
            batch_op.add_column(sa.Column('shift_id', sa.Integer(), nullable=True))
        with op.batch_alter_table('payments', schema=None) as batch_op:
            batch_op.add_column(sa.Column('shift_id', sa.Integer(), nullable=True))

    # ── 3. Create new indexes (IF NOT EXISTS on PG, otherwise safe on SQLite) ──
    if is_pg:
        op.execute("CREATE INDEX IF NOT EXISTS ix_action_logs_business_id ON action_logs (business_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_action_logs_id ON action_logs (id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_ai_feedback_business_id ON ai_feedback (business_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_ai_feedback_id ON ai_feedback (id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_ai_query_overrides_business_id ON ai_query_overrides (business_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_ai_query_overrides_id ON ai_query_overrides (id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_ai_query_overrides_query_norm ON ai_query_overrides (query_norm)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_query_overrides_biz_query ON ai_query_overrides (business_id, query_norm)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_b2b_invite_codes_code ON b2b_invite_codes (code)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_b2b_invite_codes_id ON b2b_invite_codes (id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_b2b_invite_codes_seller_code ON b2b_invite_codes (seller_business_id, code)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_b2b_ledgers_id ON b2b_ledgers (id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_b2b_ledgers_seller_buyer ON b2b_ledgers (seller_business_id, buyer_business_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_payments_shift_id ON invoice_payments (shift_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_shift_id ON invoices (shift_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_uid_token ON invoices (uid_token)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_payments_shift_id ON payments (shift_id)")
    else:
        with op.batch_alter_table('action_logs', schema=None) as batch_op:
            batch_op.create_index('ix_action_logs_business_id', ['business_id'], unique=False)
            batch_op.create_index('ix_action_logs_id', ['id'], unique=False)
        with op.batch_alter_table('ai_feedback', schema=None) as batch_op:
            batch_op.create_index('ix_ai_feedback_business_id', ['business_id'], unique=False)
            batch_op.create_index('ix_ai_feedback_id', ['id'], unique=False)
        with op.batch_alter_table('ai_query_overrides', schema=None) as batch_op:
            batch_op.create_index('ix_ai_query_overrides_business_id', ['business_id'], unique=False)
            batch_op.create_index('ix_ai_query_overrides_id', ['id'], unique=False)
            batch_op.create_index('ix_ai_query_overrides_query_norm', ['query_norm'], unique=False)
            batch_op.create_unique_constraint('uq_ai_query_overrides_biz_query', ['business_id', 'query_norm'])
        with op.batch_alter_table('b2b_invite_codes', schema=None) as batch_op:
            batch_op.create_index('ix_b2b_invite_codes_code', ['code'], unique=True)
            batch_op.create_index('ix_b2b_invite_codes_id', ['id'], unique=False)
            batch_op.create_index('ix_b2b_invite_codes_seller_code', ['seller_business_id', 'code'], unique=False)
        with op.batch_alter_table('b2b_ledgers', schema=None) as batch_op:
            batch_op.create_index('ix_b2b_ledgers_id', ['id'], unique=False)
            batch_op.create_index('ix_b2b_ledgers_seller_buyer', ['seller_business_id', 'buyer_business_id'], unique=False)
        with op.batch_alter_table('invoice_payments', schema=None) as batch_op:
            batch_op.create_index('ix_invoice_payments_shift_id', ['shift_id'], unique=False)
        with op.batch_alter_table('invoices', schema=None) as batch_op:
            batch_op.create_index('ix_invoices_shift_id', ['shift_id'], unique=False)
            batch_op.create_index('ix_invoices_uid_token', ['uid_token'], unique=True)
        with op.batch_alter_table('payments', schema=None) as batch_op:
            batch_op.create_index('ix_payments_shift_id', ['shift_id'], unique=False)

    # ── 4. Add register_shifts foreign keys (use savepoints on PG so a pre-existing FK doesn't abort the transaction) ──
    if is_pg:
        conn = op.get_bind()
        fk_stmts = [
            ("sp_fk1", "ALTER TABLE invoice_payments ADD CONSTRAINT fk_invoice_payments_shift_id_register_shifts FOREIGN KEY (shift_id) REFERENCES register_shifts(id)"),
            ("sp_fk2", "ALTER TABLE invoices ADD CONSTRAINT fk_invoices_shift_id_register_shifts FOREIGN KEY (shift_id) REFERENCES register_shifts(id)"),
            ("sp_fk3", "ALTER TABLE payments ADD CONSTRAINT fk_payments_shift_id_register_shifts FOREIGN KEY (shift_id) REFERENCES register_shifts(id)"),
        ]
        for sp, stmt in fk_stmts:
            conn.execute(sa.text(f"SAVEPOINT {sp}"))
            try:
                conn.execute(sa.text(stmt))
                conn.execute(sa.text(f"RELEASE SAVEPOINT {sp}"))
            except Exception:
                conn.execute(sa.text(f"ROLLBACK TO SAVEPOINT {sp}"))
    else:
        with op.batch_alter_table('invoice_payments', schema=None) as batch_op:
            batch_op.create_foreign_key('fk_invoice_payments_shift_id_register_shifts', 'register_shifts', ['shift_id'], ['id'])
        with op.batch_alter_table('invoices', schema=None) as batch_op:
            batch_op.create_foreign_key('fk_invoices_shift_id_register_shifts', 'register_shifts', ['shift_id'], ['id'])
        with op.batch_alter_table('payments', schema=None) as batch_op:
            batch_op.create_foreign_key('fk_payments_shift_id_register_shifts', 'register_shifts', ['shift_id'], ['id'])

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_vendors_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('staff_login_name',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
        batch_op.alter_column('counter_prefix',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)

    with op.batch_alter_table('stock_transfers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_stock_transfers_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.create_index(batch_op.f('ix_stock_transfers_business'), ['business_id'], unique=False)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('stock_transfer_line_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_stock_transfer_line_items_uid'), ['uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('stock_ledger', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_stock_ledger_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('register_shifts', schema=None) as batch_op:
        batch_op.alter_column('closing_float',
               existing_type=sa.Float(),
               type_=sa.REAL(),
               existing_nullable=True)
        batch_op.alter_column('opening_expected',
               existing_type=sa.Float(),
               type_=sa.REAL(),
               existing_nullable=True)

    with op.batch_alter_table('rate_limit_configs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_rate_limit_configs_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_purchase_orders_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('purchase_order_line_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_purchase_order_line_items_uid'), ['uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('purchase_invoices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_purchase_invoices_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('purchase_invoice_line_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_purchase_invoice_line_items_uid'), ['uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_products_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('product_barcodes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_product_barcodes_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('period_locks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_period_locks_business_uid'), ['business_id', 'uid'], unique=1)

    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_payments_shift_id_register_shifts'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_payments_shift_id'))
        batch_op.create_index(batch_op.f('uq_payments_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('journal_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_journal_entries_business_uid'), ['business_id', 'uid'], unique=1)

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_invoices_shift_id_register_shifts'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_invoices_uid_token'))
        batch_op.drop_index(batch_op.f('ix_invoices_shift_id'))
        batch_op.create_index(batch_op.f('uq_invoices_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)
        batch_op.alter_column('invoice_title',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
        batch_op.drop_column('print_template')
        batch_op.drop_column('uid_token')

    with op.batch_alter_table('invoice_payments', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_invoice_payments_shift_id_register_shifts'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_invoice_payments_shift_id'))
        batch_op.create_index(batch_op.f('uq_invoice_payments_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('invoice_line_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_invoice_line_items_uid'), ['uid'], unique=1)
        batch_op.alter_column('expiry_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
        batch_op.alter_column('mrp',
               existing_type=sa.Float(),
               type_=sa.REAL(),
               existing_nullable=True)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('inventory', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_inventory_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('godowns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_godowns_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.create_index(batch_op.f('ix_godowns_business'), ['business_id'], unique=False)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_expenses_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_customers_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)

    with op.batch_alter_table('business_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_business_settings_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('b2b_ledgers', schema=None) as batch_op:
        batch_op.drop_index('ix_b2b_ledgers_seller_buyer')
        batch_op.drop_index(batch_op.f('ix_b2b_ledgers_id'))
        batch_op.create_index(batch_op.f('uq_shared_ledgers_uid'), ['uid'], unique=1)
        batch_op.create_index(batch_op.f('ix_shared_ledgers_seller_buyer'), ['seller_business_id', 'buyer_business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_shared_ledgers_id'), ['id'], unique=False)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('b2b_invite_codes', schema=None) as batch_op:
        batch_op.drop_index('ix_b2b_invite_codes_seller_code')
        batch_op.drop_index(batch_op.f('ix_b2b_invite_codes_id'))
        batch_op.drop_index(batch_op.f('ix_b2b_invite_codes_code'))
        batch_op.create_index(batch_op.f('ix_connection_codes_seller_code'), ['seller_business_id', 'code'], unique=False)
        batch_op.create_index(batch_op.f('ix_connection_codes_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_connection_codes_code'), ['code'], unique=1)

    with op.batch_alter_table('alert_configs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('uq_alert_configs_business_uid'), ['business_id', 'uid'], unique=1)
        batch_op.alter_column('uid',
               existing_type=sa.String(length=36),
               type_=sa.TEXT(),
               nullable=False)

    with op.batch_alter_table('ai_query_overrides', schema=None) as batch_op:
        batch_op.drop_constraint('uq_ai_query_overrides_biz_query', type_='unique')
        batch_op.drop_index(batch_op.f('ix_ai_query_overrides_query_norm'))
        batch_op.drop_index(batch_op.f('ix_ai_query_overrides_id'))
        batch_op.drop_index(batch_op.f('ix_ai_query_overrides_business_id'))
        batch_op.create_unique_constraint(batch_op.f('uq_query_override_biz_query'), ['business_id', 'query_norm'])
        batch_op.create_index(batch_op.f('ix_query_override_query_norm'), ['query_norm'], unique=False)
        batch_op.create_index(batch_op.f('ix_query_override_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_query_override_business_id'), ['business_id'], unique=False)

    with op.batch_alter_table('ai_feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_feedback_id'))
        batch_op.drop_index(batch_op.f('ix_ai_feedback_business_id'))
        batch_op.create_index(batch_op.f('ix_feedback_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_feedback_business_id'), ['business_id'], unique=False)

    with op.batch_alter_table('action_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_action_logs_id'))
        batch_op.drop_index(batch_op.f('ix_action_logs_business_id'))
        batch_op.create_index(batch_op.f('ix_action_log_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_action_log_business_id'), ['business_id'], unique=False)

    # ### end Alembic commands ###
