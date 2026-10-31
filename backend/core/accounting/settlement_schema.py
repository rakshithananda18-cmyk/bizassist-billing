"""Idempotent additive financial upgrade, shared by Alembic and desktop startup."""
from sqlalchemy import inspect, text

TABLES = ("supplier_payments", "customer_refunds", "customer_credit_allocations")


def install_financial_schema(conn):
    from database.db import Base
    from core.accounting import settlement_models  # register tables
    inspector = inspect(conn)
    if inspector.has_table("invoices"):
        cols = {c["name"] for c in inspector.get_columns("invoices")}
        for name, datatype in (("legacy_paid_baseline", "REAL"),
                               ("legacy_paid_baseline_source", "VARCHAR"),
                               ("legacy_paid_baseline_date", "VARCHAR")):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE invoices ADD COLUMN {name} {datatype}"))
    if inspector.has_table("invoice_line_items"):
        cols = {c["name"] for c in inspector.get_columns("invoice_line_items")}
        if "cost_price" not in cols:
            conn.execute(text("ALTER TABLE invoice_line_items ADD COLUMN cost_price REAL"))
        if "cost_snapshot_known" not in cols:
            conn.execute(text("ALTER TABLE invoice_line_items ADD COLUMN cost_snapshot_known BOOLEAN"))
        # Never rewrite old zeros or guess historical values: the new NULL marker
        # explicitly means 'unverified historical snapshot', including provisional
        # zeros produced by the earlier unpublished/default-zero implementation.
        if conn.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE invoice_line_items ALTER COLUMN cost_price DROP DEFAULT"))
    if inspector.has_table("b2b_orders"):
        cols = {c["name"] for c in inspect(conn).get_columns("b2b_orders")}
        for name, datatype in (("quoted_place_of_supply", "VARCHAR"), ("quoted_seller_state", "VARCHAR"),
                               ("quoted_tax_inclusive", "BOOLEAN"), ("quoted_round_off_enabled", "BOOLEAN")):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE b2b_orders ADD COLUMN {name} {datatype}"))
    if inspector.has_table("purchase_invoices"):
        duplicate = conn.execute(text("SELECT business_id, invoice_number, COUNT(*) FROM purchase_invoices "
            "WHERE invoice_type='debit_note' GROUP BY business_id, invoice_number HAVING COUNT(*)>1 LIMIT 1")).first()
        if duplicate:
            raise RuntimeError("Duplicate debit-note numbers require evidence-based reconciliation before uniqueness can be installed")
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_invoices_biz_dn "
                          "ON purchase_invoices(business_id, invoice_number) WHERE invoice_type='debit_note'"))
    for name in TABLES:
        Base.metadata.tables[name].create(conn, checkfirst=True)
        cols = {column["name"] for column in inspect(conn).get_columns(name)}
        if "operator_name" not in cols:
            conn.execute(text(f"ALTER TABLE {name} ADD COLUMN operator_name VARCHAR DEFAULT 'Unknown operator' NOT NULL"))
    relations = {
        "supplier_payments": {"purchase_invoice_id": "purchase_invoices", "vendor_id": "vendors", "shift_id": "register_shifts"},
        "customer_refunds": {"credit_note_id": "invoices", "source_invoice_id": "invoices", "customer_id": "customers", "shift_id": "register_shifts"},
        "customer_credit_allocations": {"credit_note_id": "invoices", "source_invoice_id": "invoices", "target_invoice_id": "invoices", "customer_id": "customers"},
    }
    if conn.dialect.name == "postgresql":
        conn.execute(text("""CREATE OR REPLACE FUNCTION bizassist_settlement_immutable() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
            IF (to_jsonb(NEW)-'updated_at'-'operator_id') IS DISTINCT FROM (to_jsonb(OLD)-'updated_at'-'operator_id')
            THEN RAISE EXCEPTION 'Posted settlements are append-only'; END IF;
            RETURN NEW; END $$"""))
        for name, parents in relations.items():
            conn.execute(text(f'DROP TRIGGER IF EXISTS settlement_immutable ON "{name}"'))
            conn.execute(text(f'CREATE TRIGGER settlement_immutable BEFORE UPDATE ON "{name}" FOR EACH ROW EXECUTE FUNCTION bizassist_settlement_immutable()'))
            conn.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS settlement_tenant ON "{name}"'))
            conn.execute(text(f'CREATE POLICY settlement_tenant ON "{name}" USING '
                "(business_id = NULLIF(current_setting('app.current_business_id', true), '')::integer) "
                "WITH CHECK (business_id = NULLIF(current_setting('app.current_business_id', true), '')::integer)"))
            for column, parent in parents.items():
                conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_{parent}_settlement_parent" ON "{parent}"(business_id,id)'))
                constraint = f"fk_{name}_{column}_tenant"
                if not conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname=:name AND conrelid=to_regclass(:table)"),
                    {"name": constraint, "table": name}).first():
                    conn.execute(text(f'ALTER TABLE "{name}" ADD CONSTRAINT "{constraint}" FOREIGN KEY (business_id,"{column}") '
                                      f'REFERENCES "{parent}"(business_id,id)'))
    elif conn.dialect.name == "sqlite":
        for name, parents in relations.items():
            immutable = [column.name for column in Base.metadata.tables[name].columns if column.name not in {"updated_at", "operator_id"}]
            changed = " OR ".join(f'NEW."{column}" IS NOT OLD."{column}"' for column in immutable)
            conn.execute(text(f'CREATE TRIGGER IF NOT EXISTS "immutable_{name}" BEFORE UPDATE ON "{name}" WHEN {changed} '
                              "BEGIN SELECT RAISE(ABORT,'Posted settlements are append-only'); END"))
            for column, parent in parents.items():
                conn.execute(text(f'CREATE TRIGGER IF NOT EXISTS "fk_{name}_{column}_tenant" BEFORE INSERT ON "{name}" '
                    f'WHEN NEW."{column}" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "{parent}" '
                    f'WHERE id=NEW."{column}" AND business_id=NEW.business_id) '
                    "BEGIN SELECT RAISE(ABORT,'Settlement parent belongs to a different business'); END"))
