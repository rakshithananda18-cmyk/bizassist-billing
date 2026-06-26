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
    # action_log — created_at already existed, add updated_at for TimestampMixin
    {"table": "action_log", "column": "created_at", "ddl": "ALTER TABLE action_log ADD COLUMN created_at DATETIME"},
    {"table": "action_log", "column": "updated_at", "ddl": "ALTER TABLE action_log ADD COLUMN updated_at DATETIME"},
    # token_usage — gained TimestampMixin
    {"table": "token_usage", "column": "created_at", "ddl": "ALTER TABLE token_usage ADD COLUMN created_at DATETIME"},
    {"table": "token_usage", "column": "updated_at", "ddl": "ALTER TABLE token_usage ADD COLUMN updated_at DATETIME"},
    # users — app settings JSON blob
    {"table": "users", "column": "settings", "ddl": "ALTER TABLE users ADD COLUMN settings TEXT"},
    {"table": "users", "column": "logo",     "ddl": "ALTER TABLE users ADD COLUMN logo TEXT"},
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
    # b2b_orders additions
    {"table": "b2b_orders", "column": "seller_invoice_id", "ddl": "ALTER TABLE b2b_orders ADD COLUMN seller_invoice_id INTEGER"},
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
]


# Tables that carry a durable `uid` (BusinessOwnedMixin). Used by the uid backfill.
_UID_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks",
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


def _seed_users(db):
    is_test = "test" in os.environ.get("DATABASE_URL", "")

    if is_test:
        default_users = [
            {"id": 1, "username": "admin",       "password": "admin123",       "business_name": "Admin Central",          "role": "admin"},
            {"id": 2, "username": "pharmacy",    "password": "pharmacy123",    "business_name": "MediCare Pharmacy",       "role": "enterprise"},
            {"id": 3, "username": "supermarket", "password": "supermarket123", "business_name": "Daily Needs Supermarket", "role": "enterprise"},
            {"id": 4, "username": "store",       "password": "store123",       "business_name": "Apna Bazaar Store",       "role": "enterprise"},
        ]
    else:
        _admin_pw = os.environ.get("ADMIN_SEED_PASSWORD", "admin123")
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
        if not db.query(User).filter(User.username == u["username"]).first():
            db.add(User(
                id=u["id"], username=u["username"],
                password=hash_password(u["password"]),
                business_name=u["business_name"], role=u["role"],
            ))
    db.commit()

    for user in db.query(User).all():
        if not user.password.startswith("$2b$") and not user.password.startswith("$2a$"):
            user.password = hash_password(user.password)
    db.commit()


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

    # 3. Backfills
    with engine.connect() as conn:
        _backfill_null_business_ids(conn)
        _backfill_null_uids(conn)
        _migrate_session_nulls(conn)

    # 4. Seed users
    db = SessionLocal()
    try:
        _seed_users(db)
    except Exception as e:
        logger.error(f"[Migration] Seed error: {e}", exc_info=True)
    finally:
        db.close()

    logger.info("[Migration] Done.")
