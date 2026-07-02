import psycopg2

conn = psycopg2.connect(
    "postgresql://postgres.edvttytmqqijmctuiexe:BizAssist%40Passw0rd@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
)
cur = conn.cursor()

# Get all tables
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;")
tables = [r[0] for r in cur.fetchall()]

print("=== SUPABASE TABLES ===")
for t in tables:
    print(f"  {t}")

print("\n=== COLUMNS PER TABLE ===")
for t in tables:
    if t == "alembic_version":
        continue
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position;",
        (t,)
    )
    cols = [(r[0], r[1]) for r in cur.fetchall()]
    print(f"\n{t}:")
    for col, dtype in cols:
        print(f"  {col} ({dtype})")

conn.close()
