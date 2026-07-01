"""
migrate_sqlite_to_postgres.py
Copies all data from the local bizassist.db (SQLite) → Supabase (PostgreSQL).

Safe to re-run: uses INSERT ON CONFLICT DO NOTHING for idempotency.
Run from the backend/ directory with the venv active.
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect, MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

load_dotenv()

SQLITE_URL = "sqlite:///./bizassist.db"
PG_URL = os.environ.get("DATABASE_URL")

if not PG_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

print("Connecting to SQLite...")
sqlite_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})

print("Connecting to PostgreSQL (DATABASE_URL)...")
pg_engine = create_engine(PG_URL)

# Reflect both schemas
sqlite_meta = MetaData()
sqlite_meta.reflect(bind=sqlite_engine)

pg_meta = MetaData()
pg_meta.reflect(bind=pg_engine)

# Tables to migrate in dependency order (parents before children)
TABLE_ORDER = [
    "users",
    "customers",
    "vendors",
    "products",
    "invoices",
    "invoice_line_items",
    "payments",
    "purchase_orders",
    "purchase_order_line_items",
    "purchase_invoices",
    "purchase_invoice_line_items",
    "inventory",
    "uploaded_files",
    "document_embeddings",
    "chat_messages",
    "action_logs",
    "ai_feedback",
    "alert_configs",
    "ai_query_overrides",
    "rate_limit_configs",
    "token_usage",
    "business_facts",
    "stock_ledger",
    "product_barcodes",
    "business_settings",
    "invoice_payments",
    "b2b_connections",
    "b2b_invite_codes",
    "b2b_orders",
    "b2b_order_line_items",
    "b2b_ledgers",
    "expenses",
    "godowns",
    "stock_transfers",
    "stock_transfer_line_items",
    "journal_entries",
    "journal_lines",
    "period_locks",
]

total_rows = 0

with sqlite_engine.connect() as src, pg_engine.connect() as dst:
    for table_name in TABLE_ORDER:
        if table_name not in sqlite_meta.tables:
            print(f"  SKIP  {table_name} (not in SQLite)")
            continue
        if table_name not in pg_meta.tables:
            print(f"  SKIP  {table_name} (not in Postgres)")
            continue

        src_table = sqlite_meta.tables[table_name]
        rows = src.execute(src_table.select()).fetchall()

        if not rows:
            print(f"  EMPTY {table_name}")
            continue

        pg_table = pg_meta.tables[table_name]
        src_cols = set(c.key for c in src_table.columns)
        dst_cols = set(c.key for c in pg_table.columns)
        common_cols = src_cols.intersection(dst_cols)

        dicts = []
        for row in rows:
            row_dict = dict(row._mapping)
            filtered_dict = {k: v for k, v in row_dict.items() if k in common_cols}
            dicts.append(filtered_dict)

        # pg_insert with ON CONFLICT DO NOTHING for idempotency
        stmt = pg_insert(pg_table).values(dicts).on_conflict_do_nothing()
        dst.execute(stmt)
        dst.commit()

        print(f"  OK    {table_name}: {len(rows)} rows")
        total_rows += len(rows)

    # Reset every sequence so future INSERTs don't collide on id=1.
    # We copied rows WITH explicit primary keys, leaving Postgres sequences at 1.
    print("\nResetting Postgres sequences...")
    for table_name in TABLE_ORDER:
        if table_name not in pg_meta.tables:
            continue
        try:
            dst.execute(text(
                "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                "COALESCE((SELECT MAX(id) FROM " + table_name + "), 1), true)"
            ), {"t": table_name})
            dst.commit()
            print(f"  SEQ   {table_name}")
        except Exception as e:
            dst.rollback()
            print(f"  SKIP  {table_name} (no id sequence)")

print(f"\nDone! Migrated {total_rows} rows total.")
print("Verify in your Supabase dashboard -> Table editor.")
