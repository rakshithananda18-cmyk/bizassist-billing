"""
database/migration.py
=====================
Schema migration and seed runner.

Open/Closed principle: add a migration by appending to _COLUMN_MIGRATIONS.
Never modify existing entries, never scatter ALTER TABLE code across the file.
"""

import logging
import os
from sqlalchemy import text
from database.db import engine, SessionLocal
from database.models import Base, User
from services.auth import hash_password

logger = logging.getLogger("bizassist.migration")


# ---------------------------------------------------------------------------
# DECLARATIVE COLUMN MIGRATIONS
# Append a new dict to add a column. Never remove or edit existing entries.
# ---------------------------------------------------------------------------

_COLUMN_MIGRATIONS = [
    # invoices
    {"table": "invoices", "column": "business_id",     "ddl": "ALTER TABLE invoices ADD COLUMN business_id INTEGER"},
    {"table": "invoices", "column": "file_id",         "ddl": "ALTER TABLE invoices ADD COLUMN file_id INTEGER"},
    {"table": "invoices", "column": "customer_id",     "ddl": "ALTER TABLE invoices ADD COLUMN customer_id INTEGER"},
    {"table": "invoices", "column": "paid_amount",     "ddl": "ALTER TABLE invoices ADD COLUMN paid_amount REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "payment_date",    "ddl": "ALTER TABLE invoices ADD COLUMN payment_date TEXT"},
    {"table": "invoices", "column": "payment_mode",    "ddl": "ALTER TABLE invoices ADD COLUMN payment_mode TEXT"},
    {"table": "invoices", "column": "notes",           "ddl": "ALTER TABLE invoices ADD COLUMN notes TEXT"},
    {"table": "invoices", "column": "gstin_buyer",     "ddl": "ALTER TABLE invoices ADD COLUMN gstin_buyer TEXT"},
    {"table": "invoices", "column": "place_of_supply", "ddl": "ALTER TABLE invoices ADD COLUMN place_of_supply TEXT"},
    {"table": "invoices", "column": "invoice_type",    "ddl": "ALTER TABLE invoices ADD COLUMN invoice_type TEXT"},
    {"table": "invoices", "column": "subtotal",        "ddl": "ALTER TABLE invoices ADD COLUMN subtotal REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "cgst_total",      "ddl": "ALTER TABLE invoices ADD COLUMN cgst_total REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "sgst_total",      "ddl": "ALTER TABLE invoices ADD COLUMN sgst_total REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "igst_total",      "ddl": "ALTER TABLE invoices ADD COLUMN igst_total REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "cess_total",      "ddl": "ALTER TABLE invoices ADD COLUMN cess_total REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "total_amount",    "ddl": "ALTER TABLE invoices ADD COLUMN total_amount REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "irn",             "ddl": "ALTER TABLE invoices ADD COLUMN irn TEXT"},
    {"table": "invoices", "column": "ack_no",          "ddl": "ALTER TABLE invoices ADD COLUMN ack_no TEXT"},
    {"table": "invoices", "column": "ack_date",        "ddl": "ALTER TABLE invoices ADD COLUMN ack_date TEXT"},
    {"table": "invoices", "column": "qr_code",         "ddl": "ALTER TABLE invoices ADD COLUMN qr_code TEXT"},
    {"table": "invoices", "column": "created_at",      "ddl": "ALTER TABLE invoices ADD COLUMN created_at DATETIME"},
    {"table": "invoices", "column": "updated_at",      "ddl": "ALTER TABLE invoices ADD COLUMN updated_at DATETIME"},
    # inventory
    {"table": "inventory", "column": "business_id",    "ddl": "ALTER TABLE inventory ADD COLUMN business_id INTEGER"},
    {"table": "inventory", "column": "file_id",        "ddl": "ALTER TABLE inventory ADD COLUMN file_id INTEGER"},
    {"table": "inventory", "column": "vendor_id",      "ddl": "ALTER TABLE inventory ADD COLUMN vendor_id INTEGER"},
    {"table": "inventory", "column": "product_id",     "ddl": "ALTER TABLE inventory ADD COLUMN product_id INTEGER"},
    {"table": "inventory", "column": "unit",           "ddl": "ALTER TABLE inventory ADD COLUMN unit TEXT DEFAULT 'Nos'"},
    {"table": "inventory", "column": "hsn_sac",        "ddl": "ALTER TABLE inventory ADD COLUMN hsn_sac TEXT"},
    {"table": "inventory", "column": "barcode",        "ddl": "ALTER TABLE inventory ADD COLUMN barcode TEXT"},
    {"table": "inventory", "column": "batch_no",       "ddl": "ALTER TABLE inventory ADD COLUMN batch_no TEXT"},
    {"table": "inventory", "column": "mrp",            "ddl": "ALTER TABLE inventory ADD COLUMN mrp REAL"},
    {"table": "inventory", "column": "cost_price",     "ddl": "ALTER TABLE inventory ADD COLUMN cost_price REAL DEFAULT 0.0"},
    {"table": "inventory", "column": "selling_price",  "ddl": "ALTER TABLE inventory ADD COLUMN selling_price REAL DEFAULT 0.0"},
    {"table": "inventory", "column": "reorder_point",  "ddl": "ALTER TABLE inventory ADD COLUMN reorder_point INTEGER DEFAULT 10"},
    {"table": "inventory", "column": "category",       "ddl": "ALTER TABLE inventory ADD COLUMN category TEXT"},
    {"table": "inventory", "column": "created_at",     "ddl": "ALTER TABLE inventory ADD COLUMN created_at DATETIME"},
    {"table": "inventory", "column": "updated_at",     "ddl": "ALTER TABLE inventory ADD COLUMN updated_at DATETIME"},
    # payments
    {"table": "payments", "column": "business_id",     "ddl": "ALTER TABLE payments ADD COLUMN business_id INTEGER"},
    {"table": "payments", "column": "file_id",         "ddl": "ALTER TABLE payments ADD COLUMN file_id INTEGER"},
    {"table": "payments", "column": "invoice_id",      "ddl": "ALTER TABLE payments ADD COLUMN invoice_id INTEGER"},
    {"table": "payments", "column": "payment_mode",    "ddl": "ALTER TABLE payments ADD COLUMN payment_mode TEXT"},
    {"table": "payments", "column": "created_at",      "ddl": "ALTER TABLE payments ADD COLUMN created_at DATETIME"},
    {"table": "payments", "column": "updated_at",      "ddl": "ALTER TABLE payments ADD COLUMN updated_at DATETIME"},
    # uploaded_files
    {"table": "uploaded_files", "column": "business_id", "ddl": "ALTER TABLE uploaded_files ADD COLUMN business_id INTEGER"},
    {"table": "uploaded_files", "column": "file_hash",   "ddl": "ALTER TABLE uploaded_files ADD COLUMN file_hash TEXT"},
    {"table": "uploaded_files", "column": "created_at",  "ddl": "ALTER TABLE uploaded_files ADD COLUMN created_at DATETIME"},
    {"table": "uploaded_files", "column": "updated_at",  "ddl": "ALTER TABLE uploaded_files ADD COLUMN updated_at DATETIME"},
    # chat_messages
    {"table": "chat_messages", "column": "session_id",    "ddl": "ALTER TABLE chat_messages ADD COLUMN session_id TEXT"},
    {"table": "chat_messages", "column": "session_title", "ddl": "ALTER TABLE chat_messages ADD COLUMN session_title TEXT"},
    {"table": "chat_messages", "column": "source",        "ddl": "ALTER TABLE chat_messages ADD COLUMN source TEXT"},
    {"table": "chat_messages", "column": "model_tier",    "ddl": "ALTER TABLE chat_messages ADD COLUMN model_tier TEXT"},
    {"table": "chat_messages", "column": "cached",        "ddl": "ALTER TABLE chat_messages ADD COLUMN cached INTEGER DEFAULT 0"},
    {"table": "chat_messages", "column": "created_at",    "ddl": "ALTER TABLE chat_messages ADD COLUMN created_at DATETIME"},
    {"table": "chat_messages", "column": "updated_at",    "ddl": "ALTER TABLE chat_messages ADD COLUMN updated_at DATETIME"},
    # users
    {"table": "users", "column": "gstin",      "ddl": "ALTER TABLE users ADD COLUMN gstin TEXT"},
    {"table": "users", "column": "phone",      "ddl": "ALTER TABLE users ADD COLUMN phone TEXT"},
    {"table": "users", "column": "email",      "ddl": "ALTER TABLE users ADD COLUMN email TEXT"},
    {"table": "users", "column": "address",    "ddl": "ALTER TABLE users ADD COLUMN address TEXT"},
    {"table": "users", "column": "state_code", "ddl": "ALTER TABLE users ADD COLUMN state_code TEXT"},
    {"table": "users", "column": "pan",        "ddl": "ALTER TABLE users ADD COLUMN pan TEXT"},
    {"table": "users", "column": "created_at", "ddl": "ALTER TABLE users ADD COLUMN created_at DATETIME"},
    {"table": "users", "column": "updated_at", "ddl": "ALTER TABLE users ADD COLUMN updated_at DATETIME"},
    # rate_limit_configs — gained TimestampMixin in schema upgrade
    {"table": "rate_limit_configs", "column": "created_at", "ddl": "ALTER TABLE rate_limit_configs ADD COLUMN created_at DATETIME"},
    # alert_configs — created_at/updated_at already existed but ensure updated_at is present
    {"table": "alert_configs", "column": "created_at", "ddl": "ALTER TABLE alert_configs ADD COLUMN created_at DATETIME"},
    {"table": "alert_configs", "column": "updated_at", "ddl": "ALTER TABLE alert_configs ADD COLUMN updated_at DATETIME"},
    # action_logs — created_at already existed, add updated_at for TimestampMixin
    {"table": "action_logs", "column": "created_at", "ddl": "ALTER TABLE action_logs ADD COLUMN created_at DATETIME"},
    {"table": "action_logs", "column": "updated_at", "ddl": "ALTER TABLE action_logs ADD COLUMN updated_at DATETIME"},
    # token_usage — gained TimestampMixin
    {"table": "token_usage", "column": "created_at", "ddl": "ALTER TABLE token_usage ADD COLUMN created_at DATETIME"},
    {"table": "token_usage", "column": "updated_at", "ddl": "ALTER TABLE token_usage ADD COLUMN updated_at DATETIME"},
    # users — app settings JSON blob
    {"table": "users", "column": "settings", "ddl": "ALTER TABLE users ADD COLUMN settings TEXT"},
    {"table": "users", "column": "logo",     "ddl": "ALTER TABLE users ADD COLUMN logo TEXT"},
    # users — per-login POS counter prefix (multi-terminal POS §9.3a)
    {"table": "users", "column": "counter_prefix", "ddl": "ALTER TABLE users ADD COLUMN counter_prefix TEXT"},
    # users — per-business staff display/login name (§9.5 multi-tenant staff)
    {"table": "users", "column": "staff_login_name", "ddl": "ALTER TABLE users ADD COLUMN staff_login_name TEXT"},
    {"table": "users", "column": "is_premium",       "ddl": "ALTER TABLE users ADD COLUMN is_premium BOOLEAN DEFAULT 0 NOT NULL"},
    {"table": "users", "column": "upi_vpa",           "ddl": "ALTER TABLE users ADD COLUMN upi_vpa TEXT"},
    # users — session revocation counter (REVIEW_1 GAP-1: force logout / token revoke)
    {"table": "users", "column": "token_version",     "ddl": "ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0 NOT NULL"},
    # invoices additions
    {"table": "invoices", "column": "godown_id",        "ddl": "ALTER TABLE invoices ADD COLUMN godown_id INTEGER"},
    {"table": "invoices", "column": "reverse_charge",   "ddl": "ALTER TABLE invoices ADD COLUMN reverse_charge BOOLEAN DEFAULT FALSE"},
    {"table": "invoices", "column": "is_tax_inclusive", "ddl": "ALTER TABLE invoices ADD COLUMN is_tax_inclusive BOOLEAN DEFAULT FALSE"},
    {"table": "invoices", "column": "discount_total",   "ddl": "ALTER TABLE invoices ADD COLUMN discount_total REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "round_off",        "ddl": "ALTER TABLE invoices ADD COLUMN round_off REAL DEFAULT 0.0"},
    {"table": "invoices", "column": "cash_discount",    "ddl": "ALTER TABLE invoices ADD COLUMN cash_discount REAL DEFAULT 0.0"},
    # inventory additions
    {"table": "inventory", "column": "godown_id",       "ddl": "ALTER TABLE inventory ADD COLUMN godown_id INTEGER"},
    # users additions
    {"table": "users", "column": "parent_business_id",  "ddl": "ALTER TABLE users ADD COLUMN parent_business_id INTEGER"},
    {"table": "users", "column": "public_id",           "ddl": "ALTER TABLE users ADD COLUMN public_id TEXT"},
    # products additions
    {"table": "products", "column": "wholesale_price",   "ddl": "ALTER TABLE products ADD COLUMN wholesale_price REAL DEFAULT 0.0"},
    {"table": "products", "column": "distributor_price", "ddl": "ALTER TABLE products ADD COLUMN distributor_price REAL DEFAULT 0.0"},
    {"table": "products", "column": "sku",               "ddl": "ALTER TABLE products ADD COLUMN sku TEXT"},
    {"table": "products", "column": "brand",             "ddl": "ALTER TABLE products ADD COLUMN brand TEXT"},
    {"table": "products", "column": "manufacturer",      "ddl": "ALTER TABLE products ADD COLUMN manufacturer TEXT"},
    {"table": "products", "column": "category",          "ddl": "ALTER TABLE products ADD COLUMN category TEXT"},
    {"table": "products", "column": "track_inventory",   "ddl": "ALTER TABLE products ADD COLUMN track_inventory BOOLEAN DEFAULT TRUE"},
    {"table": "products", "column": "price_includes_tax","ddl": "ALTER TABLE products ADD COLUMN price_includes_tax BOOLEAN DEFAULT FALSE"},
    {"table": "products", "column": "purchase_unit",     "ddl": "ALTER TABLE products ADD COLUMN purchase_unit TEXT"},
    {"table": "products", "column": "conversion_factor", "ddl": "ALTER TABLE products ADD COLUMN conversion_factor REAL DEFAULT 1.0"},
    {"table": "products", "column": "variant_of",        "ddl": "ALTER TABLE products ADD COLUMN variant_of INTEGER"},
    {"table": "products", "column": "attributes",        "ddl": "ALTER TABLE products ADD COLUMN attributes TEXT"},
    # invoice_line_items additions
    {"table": "invoice_line_items", "column": "description", "ddl": "ALTER TABLE invoice_line_items ADD COLUMN description TEXT"},
    {"table": "invoice_line_items", "column": "batch_no",    "ddl": "ALTER TABLE invoice_line_items ADD COLUMN batch_no TEXT"},
    {"table": "invoice_line_items", "column": "serial_no",   "ddl": "ALTER TABLE invoice_line_items ADD COLUMN serial_no TEXT"},
    # purchase_orders additions
    {"table": "purchase_orders", "column": "reverse_charge",   "ddl": "ALTER TABLE purchase_orders ADD COLUMN reverse_charge BOOLEAN DEFAULT FALSE"},
    {"table": "purchase_orders", "column": "is_tax_inclusive", "ddl": "ALTER TABLE purchase_orders ADD COLUMN is_tax_inclusive BOOLEAN DEFAULT FALSE"},
    {"table": "purchase_orders", "column": "discount_total",   "ddl": "ALTER TABLE purchase_orders ADD COLUMN discount_total REAL DEFAULT 0.0"},
    {"table": "purchase_orders", "column": "round_off",        "ddl": "ALTER TABLE purchase_orders ADD COLUMN round_off REAL DEFAULT 0.0"},
    # purchase_invoices additions
    {"table": "purchase_invoices", "column": "godown_id",      "ddl": "ALTER TABLE purchase_invoices ADD COLUMN godown_id INTEGER"},
    # customers additions
    {"table": "customers", "column": "price_tier", "ddl": "ALTER TABLE customers ADD COLUMN price_tier TEXT DEFAULT 'standard'"},
    {"table": "customers", "column": "credit_balance", "ddl": "ALTER TABLE customers ADD COLUMN credit_balance REAL DEFAULT 0.0"},
    # b2b_orders additions
    {"table": "b2b_orders", "column": "seller_invoice_id", "ddl": "ALTER TABLE b2b_orders ADD COLUMN seller_invoice_id INTEGER"},
    # b2b_connections — consent hardening (Jul-2026, review findings F-1/F-2).
    # A connection requested by BizID is now created 'pending' and only the
    # COUNTERPARTY can accept it, so we must record who asked and when it was
    # answered. Mirrors alembic revision e5c9a1d7b3f2 for local SQLite installs
    # that boot through this path instead of the alembic chain.
    {"table": "b2b_connections", "column": "requested_by_business_id", "ddl": "ALTER TABLE b2b_connections ADD COLUMN requested_by_business_id INTEGER"},
    {"table": "b2b_connections", "column": "request_message",          "ddl": "ALTER TABLE b2b_connections ADD COLUMN request_message TEXT"},
    {"table": "b2b_connections", "column": "responded_at",             "ddl": "ALTER TABLE b2b_connections ADD COLUMN responded_at DATETIME"},
    # uid on the B2B tables — durable cross-DB key for the cloud->local mirror
    # (alembic f6a2d8c4b1e9). Backfilled by _backfill_null_uids via _UID_TABLES.
    {"table": "b2b_connections",      "column": "uid", "ddl": "ALTER TABLE b2b_connections ADD COLUMN uid TEXT"},
    {"table": "b2b_orders",           "column": "uid", "ddl": "ALTER TABLE b2b_orders ADD COLUMN uid TEXT"},
    {"table": "b2b_order_line_items", "column": "uid", "ddl": "ALTER TABLE b2b_order_line_items ADD COLUMN uid TEXT"},
    # journal_entries additions
    {"table": "journal_entries", "column": "prev_hash", "ddl": "ALTER TABLE journal_entries ADD COLUMN prev_hash TEXT"},
    {"table": "journal_entries", "column": "entry_hash", "ddl": "ALTER TABLE journal_entries ADD COLUMN entry_hash TEXT"},
    # stock_ledger additions
    {"table": "stock_ledger", "column": "godown_id", "ddl": "ALTER TABLE stock_ledger ADD COLUMN godown_id INTEGER"},
    {"table": "stock_ledger", "column": "batch_no", "ddl": "ALTER TABLE stock_ledger ADD COLUMN batch_no TEXT"},
    {"table": "stock_ledger", "column": "expiry_date", "ddl": "ALTER TABLE stock_ledger ADD COLUMN expiry_date TEXT"},
    # uid — Step 3 (R-3) durable sync key on every BusinessOwnedMixin table.
    # TEXT is valid on both SQLite and Postgres. Backfilled by _backfill_null_uids.
    {"table": "customers",         "column": "uid", "ddl": "ALTER TABLE customers ADD COLUMN uid TEXT"},
    {"table": "vendors",           "column": "uid", "ddl": "ALTER TABLE vendors ADD COLUMN uid TEXT"},
    {"table": "products",          "column": "uid", "ddl": "ALTER TABLE products ADD COLUMN uid TEXT"},
    {"table": "invoices",          "column": "uid", "ddl": "ALTER TABLE invoices ADD COLUMN uid TEXT"},
    {"table": "inventory",         "column": "uid", "ddl": "ALTER TABLE inventory ADD COLUMN uid TEXT"},
    {"table": "payments",          "column": "uid", "ddl": "ALTER TABLE payments ADD COLUMN uid TEXT"},
    {"table": "purchase_orders",   "column": "uid", "ddl": "ALTER TABLE purchase_orders ADD COLUMN uid TEXT"},
    {"table": "purchase_invoices", "column": "uid", "ddl": "ALTER TABLE purchase_invoices ADD COLUMN uid TEXT"},
    {"table": "expenses",          "column": "uid", "ddl": "ALTER TABLE expenses ADD COLUMN uid TEXT"},
    {"table": "godowns",           "column": "uid", "ddl": "ALTER TABLE godowns ADD COLUMN uid TEXT"},
    {"table": "stock_transfers",   "column": "uid", "ddl": "ALTER TABLE stock_transfers ADD COLUMN uid TEXT"},
    {"table": "journal_entries",   "column": "uid", "ddl": "ALTER TABLE journal_entries ADD COLUMN uid TEXT"},
    {"table": "period_locks",      "column": "uid", "ddl": "ALTER TABLE period_locks ADD COLUMN uid TEXT"},
    {"table": "invoice_line_items",         "column": "uid", "ddl": "ALTER TABLE invoice_line_items ADD COLUMN uid TEXT"},
    {"table": "purchase_order_line_items",   "column": "uid", "ddl": "ALTER TABLE purchase_order_line_items ADD COLUMN uid TEXT"},
    {"table": "purchase_invoice_line_items", "column": "uid", "ddl": "ALTER TABLE purchase_invoice_line_items ADD COLUMN uid TEXT"},
    {"table": "rate_limit_configs",         "column": "uid", "ddl": "ALTER TABLE rate_limit_configs ADD COLUMN uid TEXT"},
    {"table": "alert_configs",              "column": "uid", "ddl": "ALTER TABLE alert_configs ADD COLUMN uid TEXT"},
    {"table": "stock_ledger",               "column": "uid", "ddl": "ALTER TABLE stock_ledger ADD COLUMN uid TEXT"},
    {"table": "product_barcodes",           "column": "uid", "ddl": "ALTER TABLE product_barcodes ADD COLUMN uid TEXT"},
    {"table": "business_settings",          "column": "uid", "ddl": "ALTER TABLE business_settings ADD COLUMN uid TEXT"},
    {"table": "invoice_payments",           "column": "uid", "ddl": "ALTER TABLE invoice_payments ADD COLUMN uid TEXT"},
    {"table": "b2b_ledgers",             "column": "uid", "ddl": "ALTER TABLE b2b_ledgers ADD COLUMN uid TEXT"},
    {"table": "stock_transfer_line_items",  "column": "uid", "ddl": "ALTER TABLE stock_transfer_line_items ADD COLUMN uid TEXT"},
    # Invoice-template system, Phase 1 (plan §1.1) — print-payload snapshot fields.
    {"table": "invoices",           "column": "invoice_title", "ddl": "ALTER TABLE invoices ADD COLUMN invoice_title TEXT"},
    {"table": "invoice_line_items", "column": "mrp",           "ddl": "ALTER TABLE invoice_line_items ADD COLUMN mrp REAL"},
    {"table": "invoice_line_items", "column": "expiry_date",   "ddl": "ALTER TABLE invoice_line_items ADD COLUMN expiry_date TEXT"},
    {"table": "invoice_line_items", "column": "attributes",    "ddl": "ALTER TABLE invoice_line_items ADD COLUMN attributes TEXT"},
    # Multi-type business, Phase 2 (plan §2.1) — ordered vertical list, first = primary.
    {"table": "business_settings", "column": "business_types", "ddl": "ALTER TABLE business_settings ADD COLUMN business_types TEXT"},
    # Shift & cash-drawer management, Phase 3 — link money rows to the register
    # shift they were rung under (register_shifts table itself comes via create_all).
    {"table": "invoices",         "column": "shift_id", "ddl": "ALTER TABLE invoices ADD COLUMN shift_id INTEGER"},
    {"table": "payments",         "column": "shift_id", "ddl": "ALTER TABLE payments ADD COLUMN shift_id INTEGER"},
    {"table": "invoice_payments", "column": "shift_id", "ddl": "ALTER TABLE invoice_payments ADD COLUMN shift_id INTEGER"},
    # Public share link & invoice templates, Phase 4
    {"table": "invoices", "column": "uid_token",      "ddl": "ALTER TABLE invoices ADD COLUMN uid_token TEXT"},
    {"table": "invoices", "column": "print_template", "ddl": "ALTER TABLE invoices ADD COLUMN print_template TEXT"},
    # Shift Phase 3b — float carry-forward + cash movements (paid in/out, bank,
    # expense). shift_cash_movements table itself comes via create_all.
    {"table": "register_shifts", "column": "opening_expected", "ddl": "ALTER TABLE register_shifts ADD COLUMN opening_expected REAL"},
    {"table": "register_shifts", "column": "closing_float",    "ddl": "ALTER TABLE register_shifts ADD COLUMN closing_float REAL"},
]


# Tables that carry a durable `uid` (BusinessOwnedMixin and synced child/aux tables). Used by the uid backfill.
_UID_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks",
    "invoice_line_items", "purchase_order_line_items", "purchase_invoice_line_items",
    "rate_limit_configs", "alert_configs", "stock_ledger", "product_barcodes",
    "business_settings", "invoice_payments", "b2b_ledgers", "stock_transfer_line_items",
    "register_shifts", "shift_cash_movements",
    # B2B mirror tables — uid is the cross-DB key the cloud->local pull matches on.
    "b2b_connections", "b2b_orders", "b2b_order_line_items",
]


# ---------------------------------------------------------------------------
# MIGRATION RUNNER
# ---------------------------------------------------------------------------

def _run_column_migrations(conn):
    from sqlalchemy import inspect
    inspector = inspect(conn)
    for m in _COLUMN_MIGRATIONS:
        table, column, ddl = m["table"], m["column"], m["ddl"]
        try:
            columns = [c["name"] for c in inspector.get_columns(table)]
            if column not in columns:
                conn.execute(text(ddl))
                logger.info(f"[Migration] Added {table}.{column}")
                # Refresh inspector because schema changed
                inspector = inspect(conn)
        except Exception as e:
            logger.error(f"[Migration] Failed to add {table}.{column}: {e}")
    conn.commit()


def _check_schema_integrity(conn):
    from sqlalchemy import inspect
    inspector = inspect(conn)
    missing = []
    for table_name, table in Base.metadata.tables.items():
        try:
            if inspector.has_table(table_name):
                db_columns = {c["name"] for c in inspector.get_columns(table_name)}
                for column in table.columns:
                    if column.name not in db_columns:
                        missing.append(f"{table_name}.{column.name}")
        except Exception as e:
            logger.error(f"[Migration Check] Error inspecting table {table_name}: {e}")
    
    if missing:
        msg = (
            f"CRITICAL: Database schema mismatch! The following columns are defined in SQLAlchemy "
            f"models but missing from the database: {', '.join(missing)}. "
            f"Please add them to _COLUMN_MIGRATIONS in backend/database/migration.py."
        )
        logger.critical(msg)
        raise RuntimeError(msg)


def _backfill_null_business_ids(conn):
    for table in ("invoices", "inventory", "payments", "uploaded_files"):
        try:
            conn.execute(text(f"UPDATE {table} SET business_id = 2 WHERE business_id IS NULL"))
        except Exception as e:
            logger.error(f"[Migration] Backfill business_id {table}: {e}")
    conn.commit()


def _backfill_staff_login_name(conn):
    """(§9.5) Existing staff predate `staff_login_name` — set it to their current
    `username` so the new owner-scoped staff login keeps resolving them. New staff
    get a bare `staff_login_name` + an auto-derived unique `username` at creation."""
    try:
        conn.execute(text(
            "UPDATE users SET staff_login_name = username "
            "WHERE parent_business_id IS NOT NULL AND staff_login_name IS NULL"
        ))
        conn.commit()
    except Exception as e:
        logger.warning(f"[Migration] staff_login_name backfill skipped: {e}")


def _backfill_null_uids(conn):
    """Step 3 (R-3) — fill `uid` on rows that predate the column. New rows get a
    uid ORM-side (default); existing rows are NULL after ALTER ADD COLUMN. Phase B
    matches on uid, so every row needs one. Postgres: single fast UPDATE with
    gen_random_uuid(). SQLite: per-row uuid4 (no SQL UUID function). Idempotent —
    only touches NULLs."""
    import uuid as _uuid
    is_pg = conn.dialect.name == "postgresql"
    for table in _UID_TABLES:
        try:
            if is_pg:
                conn.execute(text(
                    f'UPDATE {table} SET uid = gen_random_uuid()::text WHERE uid IS NULL'
                ))
            else:
                rows = conn.execute(
                    text(f'SELECT id FROM {table} WHERE uid IS NULL')
                ).fetchall()
                for (row_id,) in rows:
                    conn.execute(
                        text(f'UPDATE {table} SET uid = :u WHERE id = :i'),
                        {"u": str(_uuid.uuid4()), "i": row_id},
                    )
        except Exception as e:
            logger.error(f"[Migration] Backfill uid {table}: {e}")
    conn.commit()


def _ensure_invoice_number_unique_index(conn):
    """Enforce invoice-number uniqueness IN THE DATABASE (review finding M-3).

    ``core/billing/sequence.py`` guarantees a number is never issued twice — but
    only for callers that go through it. An import, a sync apply, or a repair
    script writing an ``Invoice`` directly can still land a duplicate, and the
    first anyone would notice is a mismatched GSTR filing. Application-level
    uniqueness is not uniqueness (architecture rule 11).

    PARTIAL index (``WHERE invoice_id IS NOT NULL``): CSV-imported rows may carry
    no number at all, and multiple NULLs must not conflict with each other.

    REFUSES TO CREATE OVER EXISTING DUPLICATES. If a business already holds two
    invoices with one number, creating the index would fail — and the honest
    response is to report exactly which documents are affected, not to "fix" them.
    Renumbering an already-issued tax invoice is not ours to do silently: the
    number may be printed on a customer's copy and filed in a GST return. So we
    log them at ERROR and skip, and the index goes in on the next boot once the
    owner has resolved them.
    """
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(conn)
    if "invoices" not in set(inspector.get_table_names()):
        return

    idx_name = "uix_invoices_biz_number_notnull"
    is_pg = conn.dialect.name == "postgresql"
    try:
        if is_pg:
            already = conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": idx_name}).fetchone()
        else:
            already = conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name = :n"),
                {"n": idx_name}).fetchone()
        if already:
            return                      # already enforced — no scan needed

        dupes = conn.execute(text(
            "SELECT business_id, invoice_id, COUNT(*) AS n FROM invoices "
            "WHERE invoice_id IS NOT NULL "
            "GROUP BY business_id, invoice_id HAVING COUNT(*) > 1"
        )).fetchall()
        if dupes:
            logger.error(
                "[Migration] M-3: cannot enforce invoice-number uniqueness — %s "
                "duplicate number(s) already exist and need manual resolution "
                "(a number printed on a customer's copy must not be silently "
                "reassigned): %s",
                len(dupes),
                "; ".join(f"biz {d[0]} '{d[1]}' x{d[2]}" for d in dupes[:25]),
            )
            return

        conn.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} "
            f"ON invoices (business_id, invoice_id) WHERE invoice_id IS NOT NULL"
        ))
        conn.commit()
        logger.info("[Migration] M-3: invoice-number uniqueness now enforced by the DB")
    except Exception as e:
        logger.error("[Migration] M-3: failed to create %s: %s", idx_name, e)


def _ensure_single_open_shift_index(conn):
    """One OPEN shift per (business, operator) — enforced by the DATABASE (M-11).

    `core/shifts/service.py` states the rule in its first line of documentation
    ("ONE OPEN shift per user at a time") and `open_shift` enforces it by calling
    `get_open_shift` first. That check is keyed on `(business_id, user_id)`, and
    **`user_id` is a column sync can populate wrongly** — `register_shifts` is in
    `sync_map._USER_FK_REPOINT_ENTITIES` precisely because a shift arriving from
    another database carries that database's integer user id.

    Found in real data on 26 Jul 2026, business 7:

        shift 3  user=7  OPEN  08 Jul 18:26 -> 10 Jul 22:36
        shift 4  user=9  OPEN  08 Jul 18:30 -> never closed

    Shift 4 opened FOUR MINUTES into shift 3 and was accepted, because with
    `user_id=9` the one-open-shift check was asking about a different operator.
    Nobody could see it (`get_open_shift` looks up the logged-in user) and nobody
    could close it. **Three cash sales totalling ₹2,485 were rung against it**,
    and that cash never reached a drawer tally anyone could reconcile — an owner
    counting the till would have been ₹2,485 over with no explanation.

    Same shape as M-2 and M-7: every subsystem individually correct (the invoices,
    the receipts and the journal are all right), the defect living *between* them
    in the reconciliation layer, and nothing looking broken.

    Architecture rule 11 — application-level uniqueness is not uniqueness. A
    partial unique index makes the overlap impossible regardless of what any
    caller believes about `user_id`.

    REFUSES TO CREATE OVER EXISTING DUPLICATES, like the M-3 index: closing a
    shift writes `closing_cash_actual`, which is a COUNTED figure. A migration
    inventing a cash count would be fabricating evidence. It reports them instead,
    and installs once the owner has closed the extra shift.
    """
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(conn)
    if "register_shifts" not in set(inspector.get_table_names()):
        return

    idx_name = "uix_register_shifts_one_open_per_user"
    is_pg = conn.dialect.name == "postgresql"
    try:
        if is_pg:
            already = conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": idx_name}).fetchone()
        else:
            already = conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name = :n"),
                {"n": idx_name}).fetchone()
        if already:
            return

        dupes = conn.execute(text(
            "SELECT business_id, user_id, COUNT(*) AS n FROM register_shifts "
            "WHERE status = 'OPEN' GROUP BY business_id, user_id HAVING COUNT(*) > 1"
        )).fetchall()
        if dupes:
            logger.error(
                "[Migration] M-11: cannot enforce one-open-shift-per-operator — %s "
                "operator(s) already hold more than one OPEN shift: %s. Each extra "
                "shift may hold real receipts that never entered a drawer tally. "
                "Close them from the register screen (the tally is computed from "
                "the payment ledger); they are NOT being closed automatically "
                "because a closing cash figure is a COUNT, not a calculation. "
                "The guard installs on the next boot.",
                len(dupes),
                "; ".join(f"biz {d[0]} user {d[1]} x{d[2]}" for d in dupes[:25]),
            )
            return

        conn.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} "
            f"ON register_shifts (business_id, user_id) WHERE status = 'OPEN'"
        ))
        conn.commit()
        logger.info("[Migration] M-11: one-open-shift-per-operator now enforced by the DB")
    except Exception as e:
        logger.error("[Migration] M-11: failed to create %s: %s", idx_name, e)


def _ensure_line_item_overfill_guard(conn):
    """Make it IMPOSSIBLE to append a line item to a completed invoice (M-16/M-17).

    THE DEFECT THIS PREVENTS, twice over
    -----------------------------------
    A batch process appended `invoice_line_items` rows to invoices that were
    already complete. It happened on 2026-07-17 (M-16: 63 rows, businesses 6 and
    7 — Brownie Factory's P&L read a ₹-6,715 loss instead of its real ₹+4,648
    profit) and again across 2026-06-29..07-03 (M-17: 15 rows, business 6,
    ₹3,298.30, COGS overstated by ₹2,422.57).

    Nothing detected either one, because every subsystem was individually correct:
    the invoice headers were untouched, the journal is posted FROM the headers so
    it footed and the hash chain verified, and the payment ledger agreed. Only the
    lines were inflated. COGS is `invoice_line_items x Product.cost_price`, so the
    P&L was wrong and nothing objected.

    WHY THIS IS AN "OVERFILL" GUARD AND NOT `SUM(lines) == total`
    ------------------------------------------------------------
    The obvious constraint is unimplementable, and shipping it would have broken
    every sale. Verified in the code, not assumed:

      * `create_sale_invoice` writes the header WITH its final total first
        (`total_amount=grand`, `db.add(inv)`, `db.flush()`) and only THEN adds the
        line items one at a time. So after line 1 of 3, `SUM(line_total)` is a
        third of `total_amount` — the equality is transiently false on every
        multi-line sale.
      * The sync pull applies `invoice_line_items` in its `_child_last` group,
        i.e. AFTER the invoice, one row at a time. Same transient state, and it is
        the normal case for every synced document.

    A row-level equality trigger would therefore reject every multi-line sale and
    every synced line item. What it CAN assert is the asymmetry: a legitimate
    build-up only ever fills *up to* the header target, while the corruption
    *exceeds* it. So:

        SUM(existing lines) + NEW.line_total  <=  target + tolerance
        where target = total_amount + cash_discount - round_off

    (The discount and round-off live on the header, not the lines — omitting them
    is what produced five false positives the first time audit check I was
    written; `LCL-OW-0027` is 337.65 == 323 + 15 - 0.35.)

    This is precise because the write surface is small and was verified: the ONLY
    code that creates `InvoiceLineItem` rows is `create_sale_invoice` and
    `create_credit_note`, both inside the transaction that just wrote the header,
    and there is no invoice-edit or add-line route anywhere in the app.

    WHAT IT DOES NOT CATCH, stated plainly
    --------------------------------------
    * MISSING lines (an under-filled invoice). Not the observed defect, and
      audit check I covers that direction.
    * UPDATEs that inflate an existing line. Guarding those would risk rejecting a
      legitimate header/line recomputation, and no such path exists today; check I
      catches it after the fact.
    * A writer that also rewrites the header to match. Nothing can distinguish
      that from a real invoice.

    Existing over-filled rows do NOT block installation — unlike the M-3 and M-11
    unique indexes, a trigger constrains future writes only. They are reported at
    ERROR so they are not mistaken for clean.
    """
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())

    TOL = 1.00
    is_pg = conn.dialect.name == "postgresql"

    # (child table, parent table, FK column, parent target expression, fn suffix)
    #
    # TWO tables, because the corruption has now been found on both:
    #   * invoices / invoice_line_items      -> M-16, M-17
    #   * b2b_orders / b2b_order_line_items  -> M-18 (2 of 2 live orders affected)
    #
    # The B2B pair carries no discount or round-off column, so its target is the
    # plain total. Driving both from one spec keeps the rule in a single place
    # rather than growing a second near-identical installer that can drift.
    SPECS = [
        ("invoice_line_items", "invoices", "invoice_id",
         "COALESCE(total_amount,0) + COALESCE(cash_discount,0) - COALESCE(round_off,0)",
         "line_item"),
        ("b2b_order_line_items", "b2b_orders", "order_id",
         "COALESCE(total_amount,0)",
         "b2b_order_line"),
    ]

    for child, parent, fk, TARGET, suffix in SPECS:
        if not {parent, child} <= tables:
            continue
        _install_overfill_guard(conn, child, parent, fk, TARGET, suffix, TOL, is_pg)


def _install_overfill_guard(conn, child, parent, fk, TARGET, suffix, TOL, is_pg):
    """Install one overfill guard. See _ensure_line_item_overfill_guard for the
    reasoning; this is the per-table mechanics."""
    name = f"ck_{child}_no_overfill"
    try:
        # Report — never silently — any invoice already over-filled.
        qualified = TARGET.replace("COALESCE(", "COALESCE(p.")
        bad = conn.execute(text(f"""
            SELECT p.id, ROUND(SUM(c.line_total) - ({qualified}), 2) AS over
              FROM {parent} p JOIN {child} c ON c.{fk} = p.id
             WHERE COALESCE(p.total_amount,0) <> 0
             GROUP BY p.id
            HAVING SUM(c.line_total) > ({qualified}) + {TOL}
        """)).fetchall()
        if bad:
            logger.error(
                "[Migration] overfill: %s %s row(s) already hold MORE line value "
                "than was billed (ids: %s). The guard only constrains NEW writes; "
                "these are existing corruption. Repair with: python "
                "scripts/repair_line_items_by_invariant.py --apply",
                len(bad), parent,
                "; ".join(f"{b[0]} +{b[1]}" for b in bad[:25]),
            )

        if is_pg:
            already = conn.execute(text(
                "SELECT 1 FROM pg_trigger WHERE tgname = :n"), {"n": name}).fetchone()
            if already:
                return
            # A CHECK constraint cannot contain a subquery, so Postgres needs a
            # real trigger function.
            fn = f"bizassist_guard_{suffix}_overfill"
            conn.execute(text(f"""
                CREATE OR REPLACE FUNCTION {fn}()
                RETURNS trigger AS $$
                DECLARE tgt numeric; cur numeric;
                BEGIN
                    SELECT {TARGET} INTO tgt FROM {parent} WHERE id = NEW.{fk};
                    IF tgt IS NULL OR tgt = 0 THEN RETURN NEW; END IF;
                    SELECT COALESCE(SUM(line_total), 0) INTO cur
                      FROM {child} WHERE {fk} = NEW.{fk};
                    IF (cur + COALESCE(NEW.line_total, 0)) > tgt + {TOL} THEN
                        RAISE EXCEPTION 'overfill guard: line items for {parent} % would total %, exceeding the billed amount % - refusing to append to a completed document',
                          NEW.{fk}, cur + COALESCE(NEW.line_total,0), tgt;
                    END IF;
                    RETURN NEW;
                END $$ LANGUAGE plpgsql;"""))
            conn.execute(text(f"""
                CREATE TRIGGER {name}
                BEFORE INSERT ON {child}
                FOR EACH ROW EXECUTE FUNCTION {fn}();"""))
        else:
            already = conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name = :n"),
                {"n": name}).fetchone()
            if already:
                return
            tgt_sql = f"(SELECT {TARGET} FROM {parent} WHERE id = NEW.{fk})"
            cur_sql = (f"COALESCE((SELECT SUM(line_total) FROM {child} "
                       f"WHERE {fk} = NEW.{fk}), 0)")
            conn.execute(text(f"""
                CREATE TRIGGER IF NOT EXISTS {name}
                BEFORE INSERT ON {child}
                FOR EACH ROW
                WHEN {tgt_sql} > 0
                 AND ({cur_sql} + COALESCE(NEW.line_total, 0)) > {tgt_sql} + {TOL}
                BEGIN
                    SELECT RAISE(ABORT, 'overfill guard: line items would exceed the document total - refusing to append a line to a completed document');
                END;"""))
        conn.commit()
        logger.info("[Migration] overfill guard installed on %s (%s)",
                    child, conn.dialect.name)
    except Exception as e:
        logger.error("[Migration] failed to install %s: %s", name, e)


def _ensure_money_invariants(conn):
    """Install the DB-level money invariants (review finding N4).

    Thin wrapper: the rules and the per-dialect DDL live in
    ``core/accounting/db_invariants.py`` so they sit next to
    ``core/accounting/integrity.py``, which already defines what "intact" means
    for the books. Detection and prevention should not be able to drift apart.

    Deliberately never raises. A guard that cannot be installed must not stop the
    app booting — the owner still needs to bill. It reports instead, at ERROR,
    naming the rows that block it.
    """
    try:
        from core.accounting.db_invariants import ensure_invariants
        report = ensure_invariants(conn)
        if report["skipped_violations"]:
            logger.error(
                "[Migration] N4: %s money invariant(s) NOT enforced because "
                "existing rows violate them: %s",
                len(report["skipped_violations"]), report["skipped_violations"],
            )
        if report["errors"]:
            logger.error("[Migration] N4: invariant install errors: %s", report["errors"])
        return report
    except Exception as e:
        logger.error("[Migration] N4: money invariants step failed: %s", e, exc_info=True)
        return None


def _repair_invoice_paid_state(conn):
    """Repair invoices whose paid_amount/status disagree with their payment ledger.

    WHY THIS EXISTS (review finding M-7)
    ------------------------------------
    ``Invoice.paid_amount`` and ``Invoice.status`` are a PROJECTION of the
    append-only ``invoice_payments`` ledger. The cloud re-derived them on every
    push; the local pull worker did not, because the reconciliation lived inside
    ``routes/sync.py`` where the worker could not reach it. Every invoice pulled
    cloud→local therefore kept whatever status was serialised on the cloud at
    snapshot time — the reported "history shows the payment but the invoice is
    still Pending".

    The code fix (``core/sync/apply_hooks.py``) only protects FUTURE syncs. Rows
    already written are still wrong, and a wrong status is not cosmetic: it
    drives receivables, the pending-dues list and customer chasing. So this runs
    once on boot and re-derives them from the ledger.

    DIRECTION SAFETY — THE HARD-WON RULE
    ------------------------------------
    The first version of this repair treated the payment ledger as complete
    truth and rewrote ``paid_amount`` to match it in BOTH directions. Run
    against real data it immediately did harm::

        C1-0002 (biz 6): Paid/2533.00  ->  Partial/104.00
        OW-0003 (biz 6): Paid/124.00   ->  Paid/311.00

    The first invented a ₹2,429 debt against a customer who may well have paid.
    The second recorded a ₹187 overpayment on a ₹124 invoice.

    The error was assuming the ledger is COMPLETE. In a system we have just
    proved was silently dropping rows across sync, the absence of a payment row
    is not evidence that no payment happened. And the M-7 bug only ever
    manifested as UNDER-reporting — "history shows the payment, invoice says
    Pending". It never inflated a paid figure. So the repair only needs to move
    in one direction, and moving in the other is pure risk.

    Rules, by case:

    ``ledger > recorded`` and ``ledger <= total``
        RAISE. There are payment rows evidencing money that the invoice does not
        reflect. This is the M-7 bug and the only case that is written.

    ``ledger > total``
        REPORT ONLY. Almost always a payment row attached to the wrong invoice.
        Writing it would invent a customer credit — as wrong as inventing a debt.

    ``ledger < recorded``
        REPORT ONLY. Either payment rows have not synced down yet, or the
        recorded figure is inflated. We cannot tell from here, and guessing
        wrong means chasing a customer for money they already paid.

    Both anomaly classes are printed at ERROR with the numbers so a human can
    settle them against the actual receipts. Refusing to guess and saying so is
    the correct behaviour for money.

    OTHER SAFETY
    ------------
    · Only touches invoices that HAVE payment rows. Legacy invoices marked paid
      with no ledger rows are left exactly as they are.
    · Only writes rows that actually disagree, so it is a no-op from the second
      boot onwards and never churns ``updated_at`` into a sync loop.
    · Reports what it changed at WARNING with the invoice numbers. A silent
      repair of money data is not a repair, it is a second mystery.
    """
    try:
        rows = conn.execute(text(
            """
            SELECT i.id,
                   i.business_id,
                   i.invoice_id,
                   COALESCE(i.total_amount, i.amount, 0)  AS grand,
                   COALESCE(i.paid_amount, 0)             AS stored_paid,
                   i.status                               AS stored_status,
                   COALESCE(SUM(p.amount_paid), 0)        AS ledger_paid
              FROM invoices i
              JOIN invoice_payments p
                ON p.invoice_id = i.id
               AND p.business_id = i.business_id
             GROUP BY i.id, i.business_id, i.invoice_id,
                      i.total_amount, i.amount, i.paid_amount, i.status
            """
        )).fetchall()
    except Exception as e:
        # Table may not exist yet on a brand-new DB — nothing to repair.
        logger.info("[Migration] paid-state repair skipped: %s", e)
        return

    def _status_for(paid: float, total: float) -> str:
        if total > 0 and paid >= total:
            return "Paid"
        return "Partial" if paid > 0 else "Pending"

    fixed, over_ledger, under_ledger = [], [], []
    for r in rows:
        inv_id, biz, number, grand, stored_paid, stored_status, ledger_paid = r
        ledger = round(float(ledger_paid or 0.0), 2)
        recorded = round(float(stored_paid or 0.0), 2)
        grand = round(float(grand or 0.0), 2)
        label = f"{number or inv_id}(biz {biz})"

        # ── Anomalies: report, never write. See the docstring. ──────────────
        if ledger > grand + 0.01:
            over_ledger.append(
                f"{label}: total {grand}, but payment rows sum to {ledger} "
                f"(recorded {recorded}) — a receipt is probably attached to the "
                f"wrong invoice")
            continue
        if ledger < recorded - 0.01:
            under_ledger.append(
                f"{label}: recorded paid {recorded}, but payment rows sum to only "
                f"{ledger} — either receipts have not synced down or the recorded "
                f"figure is wrong. NOT changed.")
            continue

        # ── The M-7 case: ledger evidences money the invoice doesn't show ───
        if ledger > recorded + 0.01:
            status = _status_for(ledger, grand)
            try:
                conn.execute(
                    text("UPDATE invoices SET paid_amount = :p, status = :s WHERE id = :i"),
                    {"p": ledger, "s": status, "i": inv_id})
                fixed.append(f"{label}: {stored_status}/{recorded} -> {status}/{ledger}")
            except Exception as e:
                logger.error("[Migration] paid-state repair FAILED for invoice %s: %s",
                             inv_id, e)
            continue

        # ── Amounts agree; only the status label is stale ───────────────────
        status = _status_for(recorded, grand)
        if stored_status != status:
            try:
                conn.execute(text("UPDATE invoices SET status = :s WHERE id = :i"),
                             {"s": status, "i": inv_id})
                fixed.append(f"{label}: status {stored_status} -> {status} "
                             f"(amount {recorded} unchanged)")
            except Exception as e:
                logger.error("[Migration] status repair FAILED for invoice %s: %s",
                             inv_id, e)

    if fixed:
        conn.commit()
        logger.warning(
            "[Migration] M-7 repair: raised paid state on %s invoice(s) whose "
            "payment rows evidenced money the invoice did not show: %s",
            len(fixed), "; ".join(fixed[:25]) + (" …" if len(fixed) > 25 else ""),
        )
    for bucket, headline in (
        (under_ledger, "invoice(s) record MORE paid than their payment rows show"),
        (over_ledger, "invoice(s) have payment rows exceeding the invoice total"),
    ):
        if bucket:
            logger.error(
                "[Migration] M-7 anomaly — %s %s. NOT auto-corrected: guessing "
                "wrong here either invents a debt or invents a credit. Settle "
                "these against the actual receipts: %s",
                len(bucket), headline,
                "; ".join(bucket[:25]) + (" …" if len(bucket) > 25 else ""),
            )


def _backfill_b2b_connection_consent(conn):
    """Jul-2026 consent hardening (review findings F-1/F-2).

    Connections created under the old auto-accept behaviour are LEFT ACCEPTED —
    back-dating them to 'pending' would silently sever live supplier
    relationships and strand in-flight orders. They only need `responded_at`
    stamped so the UI classifies them as settled rather than parking them in the
    "awaiting your approval" inbox forever.

    Also creates the status index the Approved/Pending/Sent tabs filter on.
    Idempotent — only touches NULLs, and the index create is guarded."""
    try:
        conn.execute(text(
            "UPDATE b2b_connections "
            "SET responded_at = COALESCE(responded_at, updated_at, created_at) "
            "WHERE status = 'accepted' AND responded_at IS NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_b2b_connections_status "
            "ON b2b_connections (status)"
        ))
        conn.commit()
    except Exception as e:
        # A fresh DB may not have the table yet on the very first boot; the ORM
        # create_all above normally handles that, so this is only defensive.
        logger.warning(f"[Migration] Backfill b2b connection consent: {e}")


# ---------------------------------------------------------------------------
# UID DEDUP + UNIQUE INDEX
#
# Dedup runs ONCE per table — only when the partial unique index doesn't exist
# yet (first boot after this code shipped).  Once the index is in place the DB
# itself prevents duplicates, so the table scan is never repeated.
# ---------------------------------------------------------------------------

# Financially meaningful tables where uid duplicates must be cleaned first.
_DEDUP_TABLES = [
    "invoices", "invoice_payments", "customers", "vendors", "products",
    "purchase_invoices", "expenses", "inventory", "godowns",
    "stock_transfers", "purchase_orders",
    # stock_ledger rows were duplicated by the pre-v1.1.1 sync bug; without
    # dedup its uid unique index fails (WARN) on every boot, leaving the table
    # unguarded against future duplicates. Same keep-newest (MAX id) rule.
    "stock_ledger",
]


def _ensure_uid_unique_indexes(conn):
    """For every UID-tracked table:

    1. If the partial unique index does NOT yet exist → run dedup first (once,
       this boot only), then create the index.
    2. If the index already exists → skip entirely (zero table scans).

    The partial index (`WHERE uid IS NOT NULL`) means NULL uids produced during
    backfill never conflict with each other.  Works on SQLite and PostgreSQL.
    """
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(conn)
    existing  = set(inspector.get_table_names())
    is_pg     = conn.dialect.name == "postgresql"

    for table in _UID_TABLES:
        if table not in existing:
            continue
        try:
            cols = {c["name"] for c in inspector.get_columns(table)}
            if "uid" not in cols:
                continue

            idx_name = f"uix_{table}_uid_notnull"

            # ── Check whether the index already exists ──────────────────────
            if is_pg:
                already = conn.execute(text(
                    "SELECT 1 FROM pg_indexes WHERE indexname = :n"
                ), {"n": idx_name}).fetchone()
            else:
                already = conn.execute(text(
                    "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"
                ), {"n": idx_name}).fetchone()

            if already:
                continue  # Index present — DB already enforces uniqueness, nothing to do

            # ── Index absent: dedup first (once), then create index ─────────
            if table in _DEDUP_TABLES and "business_id" in cols:
                try:
                    if is_pg:
                        result = conn.execute(text(f"""
                            WITH ranked AS (
                                SELECT id,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY uid, business_id
                                           ORDER BY id DESC
                                       ) AS rn
                                FROM   \"{table}\"
                                WHERE  uid IS NOT NULL
                            )
                            DELETE FROM \"{table}\"
                            WHERE  id IN (SELECT id FROM ranked WHERE rn > 1)
                        """))
                        removed = result.rowcount
                    else:
                        dup_ids = conn.execute(text(f"""
                            SELECT id FROM {table}
                            WHERE uid IS NOT NULL
                              AND id NOT IN (
                                  SELECT MAX(id) FROM {table}
                                  WHERE uid IS NOT NULL
                                  GROUP BY uid, business_id
                              )
                        """)).fetchall()
                        removed = len(dup_ids)
                        for (dup_id,) in dup_ids:
                            conn.execute(
                                text(f"DELETE FROM {table} WHERE id = :i"),
                                {"i": dup_id},
                            )
                    if removed:
                        logger.info(
                            "[Migration] Dedup uid: removed %s duplicate rows from %s",
                            removed, table,
                        )
                    conn.commit()
                except Exception as dedup_err:
                    logger.error("[Migration] Dedup uid %s: %s", table, dedup_err)

            # ── Create the partial unique index ─────────────────────────────
            try:
                if is_pg:
                    conn.execute(text(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS {idx_name}
                        ON \"{table}\" (uid)
                        WHERE uid IS NOT NULL
                    """))
                else:
                    conn.execute(text(f"""
                        CREATE UNIQUE INDEX {idx_name}
                        ON {table} (uid)
                        WHERE uid IS NOT NULL
                    """))
                logger.info("[Migration] Created partial uid unique index on %s", table)
                conn.commit()
            except Exception as idx_err:
                logger.warning("[Migration] uid unique index for %s: %s", table, idx_err)

        except Exception as e:
            logger.error("[Migration] _ensure_uid_unique_indexes %s: %s", table, e)


def _migrate_session_nulls(conn):
    try:
        conn.execute(text(
            "UPDATE chat_messages "
            "SET session_id = 'default', session_title = 'Previous Chat' "
            "WHERE session_id IS NULL"
        ))
        conn.commit()
    except Exception as e:
        logger.warning(f"[Migration] Session backfill skipped: {e}")


def _backfill_biz_ids(db):
    from database.models import User
    from core.connection.utils import generate_bizid
    users_missing = db.query(User).filter(User.public_id == None).all()
    if users_missing:
        for u in users_missing:
            u.public_id = generate_bizid(db)
            db.add(u)
        db.commit()
        logger.info(f"[Migration] Backfilled BizID for {len(users_missing)} legacy users.")


def _seed_users(db):
    is_test = "test" in os.environ.get("DATABASE_URL", "") or os.environ.get("BIZASSIST_TESTING") == "1"
    _admin_pw = os.environ.get("ADMIN_SEED_PASSWORD", "admin123")

    if is_test:
        default_users = [
            {"id": 1, "username": "admin",       "password": _admin_pw,        "business_name": "Admin Central",          "role": "admin"},
            {"id": 2, "username": "pharmacy",    "password": "pharmacy123",    "business_name": "MediCare Pharmacy",       "role": "enterprise"},
            {"id": 3, "username": "supermarket", "password": "supermarket123", "business_name": "Daily Needs Supermarket", "role": "enterprise"},
            {"id": 4, "username": "store",       "password": "store123",       "business_name": "Apna Bazaar Store",       "role": "enterprise"},
        ]
    else:
        default_users = [
            {"id": 1, "username": "admin", "password": _admin_pw,
             "business_name": "Admin Central", "role": "admin"}
        ]
        from services.admin_service import wipe_user_data
        demo_usernames = ["pharmacy", "supermarket", "store"]
        demo_users = db.query(User).filter(User.username.in_(demo_usernames)).all()
        for du in demo_users:
            logger.info(f"[Seed] Removing demo user '{du.username}'...")
            try:
                wipe_user_data(du.id, db)
            except Exception as e:
                logger.error(f"[Seed] Failed to wipe user data for {du.username}: {e}")
                db.delete(du)
                db.commit()

    for u in default_users:
        existing = db.query(User).filter(User.username == u["username"]).first()
        if not existing:
            db.add(User(
                id=u["id"], username=u["username"],
                password=hash_password(u["password"]),
                business_name=u["business_name"], role=u["role"],
            ))
        elif u["username"] == "admin" and (is_test or os.environ.get("ADMIN_SEED_PASSWORD")):
            existing.password = hash_password(u["password"])
    db.commit()

    for user in db.query(User).all():
        if user.password and not user.password.startswith(("$2b$", "$2a$", "$2y$", "$2x$", "$2$")):
            user.password = hash_password(user.password)
    db.commit()


def _resync_postgres_sequences(conn):
    """Resync Postgres auto-increment sequences after explicit PK inserts."""
    if conn.dialect.name != "postgresql":
        return
    tables = [
        "users", "customers", "vendors", "products", "invoices", "inventory",
        "payments", "purchase_orders", "purchase_invoices", "expenses",
        "godowns", "stock_transfers", "journal_entries", "invoice_payments",
        "b2b_ledgers", "register_shifts", "shift_cash_movements"
    ]
    for tbl in tables:
        try:
            conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), COALESCE((SELECT MAX(id) FROM {tbl}), 0) + 1, false);"))
        except Exception:
            pass


def run_migrations_and_seed():
    """Called on app startup. Idempotent — safe to run on every boot."""
    logger.info("[Migration] Starting...")

    # 1. Create new tables (customers, vendors, products, line items, purchase orders)
    Base.metadata.create_all(bind=engine)
    logger.info("[Migration] create_all done.")

    # 2. Add missing columns to existing tables
    with engine.connect() as conn:
        _run_column_migrations(conn)
        _check_schema_integrity(conn)

    # 3. Backfills & sequence resync
    with engine.connect() as conn:
        _backfill_null_business_ids(conn)
        _backfill_null_uids(conn)
        _ensure_uid_unique_indexes(conn)  # dedup once + create partial unique index (no-op after first boot)
        _backfill_staff_login_name(conn)
        _backfill_b2b_connection_consent(conn)
        # M-7: re-derive any invoice whose paid state drifted from its ledger
        # (pull-side reconciliation was missing until Jul-2026).
        _repair_invoice_paid_state(conn)
        # M-3: DB-level backstop for the invoice-number allocator.
        _ensure_invoice_number_unique_index(conn)
        # M-11: one OPEN shift per operator. Keyed on user_id, which sync can
        # populate wrongly — so it needs a DB guard, not just the service check.
        _ensure_single_open_shift_index(conn)
        # N4: the remaining money invariants, pushed down to the DB so paths that
        # bypass the command layer (imports, sync applies, repair scripts) cannot
        # write a row the books cannot represent. Runs AFTER the backfills above,
        # because a guard installed before its column exists would be skipped and
        # then have to wait a whole boot cycle. Never raises; it reports which
        # rules it could not install and why.
        # M-16/M-17: make appending a line to a completed invoice impossible.
        # Installed AFTER _ensure_money_invariants so the simple row-level guards
        # are in place first; this one needs a subquery and therefore its own
        # trigger on both dialects.
        _ensure_line_item_overfill_guard(conn)
        _ensure_money_invariants(conn)
        _migrate_session_nulls(conn)
        _resync_postgres_sequences(conn)

    # 4. Seed users
    db = SessionLocal()
    try:
        _backfill_biz_ids(db)
        _seed_users(db)
    except Exception as e:
        logger.error(f"[Migration] Seed error: {e}", exc_info=True)
    finally:
        db.close()

    logger.info("[Migration] Done.")
