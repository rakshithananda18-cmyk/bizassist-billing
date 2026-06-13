"""
reset_supabase.py
DANGER: Drops ALL tables in the Supabase public schema, then you re-run
`alembic upgrade head`. Use ONLY to recover from a partial/corrupt migration.

Guarded: requires the env var I_UNDERSTAND_THIS_DROPS_EVERYTHING=yes AND an
interactive "RESET" confirmation, so it can never run by accident or in CI.
Run from the backend/ directory with the venv active.
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

if "postgres" not in DATABASE_URL:
    print("Refusing to run: DATABASE_URL is not a PostgreSQL database.")
    sys.exit(1)

# ── Safety gate ───────────────────────────────────────────────────────────────
if os.environ.get("I_UNDERSTAND_THIS_DROPS_EVERYTHING") != "yes":
    print("Refusing to run. This DROPS EVERY TABLE in the public schema.")
    print("If you really mean it, set I_UNDERSTAND_THIS_DROPS_EVERYTHING=yes and re-run.")
    sys.exit(1)

print(f"Target DB host: {DATABASE_URL.split('@')[-1].split('/')[0]}")
if input('Type "RESET" to drop ALL tables: ').strip() != "RESET":
    print("Aborted.")
    sys.exit(0)

engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename;
    """))
    tables = [row[0] for row in result]

    if not tables:
        print("No tables found — schema is already clean.")
    else:
        print(f"Found {len(tables)} tables to drop: {tables}")
        drop_sql = f"DROP TABLE IF EXISTS {', '.join(tables)} CASCADE;"
        conn.execute(text(drop_sql))
        conn.commit()
        print("All tables dropped.")

print("\nNow run:  alembic upgrade head")
