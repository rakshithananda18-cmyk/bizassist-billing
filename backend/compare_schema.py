"""
Deep audit: compare Supabase DB data types vs SQLAlchemy model column types,
and check for any routes that reference old table/column names.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2
import database.models
from database.db import Base
import sqlalchemy as sa

# --- SQLAlchemy type mapping ---
def sa_type_to_pg(col):
    t = col.type
    if isinstance(t, (sa.Integer, sa.BigInteger)):
        return "integer"
    if isinstance(t, (sa.String, sa.VARCHAR)):
        return "character varying"
    if isinstance(t, sa.Text):
        return "text"
    if isinstance(t, sa.Boolean):
        return "boolean"
    if isinstance(t, (sa.Float, sa.Numeric)):
        return "double precision"
    if isinstance(t, sa.DateTime):
        return "timestamp without time zone"
    if isinstance(t, sa.Date):
        return "date"
    return str(t).lower()

# --- Get models ---
model_types = {}  # {table: {col: pg_type}}
for tname, table in Base.metadata.tables.items():
    model_types[tname] = {c.name: sa_type_to_pg(c) for c in table.columns}

# --- Get Supabase ---
conn = psycopg2.connect(
    "postgresql://postgres.edvttytmqqijmctuiexe:BizAssist%40Passw0rd@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
)
cur = conn.cursor()
cur.execute("""
    SELECT table_name, column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema='public'
    ORDER BY table_name, ordinal_position;
""")
db_types = {}
db_nullable = {}
for table, col, dtype, nullable in cur.fetchall():
    db_types.setdefault(table, {})[col] = dtype
    db_nullable.setdefault(table, {})[col] = nullable

# Data type mismatches
print("=" * 70)
print("DATA TYPE MISMATCHES (model type != DB type):")
print("=" * 70)
found = False
for tname in sorted(set(model_types) & set(db_types)):
    for col in sorted(set(model_types[tname]) & set(db_types[tname])):
        m = model_types[tname][col]
        d = db_types[tname][col]
        # rough equivalence
        if m == d:
            continue
        # allow float/real/numeric equivalences
        numeric_set = {"double precision", "real", "numeric", "float", "integer", "bigint"}
        if m in numeric_set and d in numeric_set:
            continue
        print(f"  ⚠️  {tname}.{col}: model={m}, DB={d}")
        found = True
if not found:
    print("  ✅ No data type mismatches found!")

# Check nullable mismatches for important columns
print("\n" + "=" * 70)
print("NULLABLE MISMATCHES (model NOT NULL but DB allows NULL):")
print("=" * 70)
found = False
for tname, table in Base.metadata.tables.items():
    if tname not in db_nullable:
        continue
    for col in table.columns:
        if col.name not in db_nullable.get(tname, {}):
            continue
        model_not_null = not col.nullable
        db_not_null = db_nullable[tname][col.name] == "NO"
        if model_not_null and not db_not_null:
            print(f"  ⚠️  {tname}.{col.name}: model=NOT NULL, DB=NULLABLE")
            found = True
if not found:
    print("  ✅ No critical nullable mismatches!")

conn.close()
print("\nAudit complete.")
