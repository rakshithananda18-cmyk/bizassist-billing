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


def _backfill_null_business_ids(conn):
    for table in ("invoices", "inventory", "payments", "uploaded_files"):
        try:
            conn.execute(text(f"UPDATE {table} SET business_id = 2 WHERE business_id IS NULL"))
        except Exception as e:
            logger.error(f"[Migration] Backfill business_id {table}: {e}")
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
        from database.models import Invoice, Inventory, Payment, UploadedFile, DocumentEmbedding, ChatMessage
        demo_usernames = ["pharmacy", "supermarket", "store"]
        demo_users = db.query(User).filter(User.username.in_(demo_usernames)).all()
        for du in demo_users:
            logger.info(f"[Seed] Removing demo user '{du.username}'...")
            for model in (Invoice, Inventory, Payment, UploadedFile, DocumentEmbedding, ChatMessage):
                db.query(model).filter(model.business_id == du.id).delete()
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

    # 3. Backfills
    with engine.connect() as conn:
        _backfill_null_business_ids(conn)
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
