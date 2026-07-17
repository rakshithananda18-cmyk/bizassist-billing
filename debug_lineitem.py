"""
Simulate a cloud->local remap import for invoice_line_items to find why they fail.
Checks id_maps building, FK rewriting, uid lookup, and insert.
"""
import sys, sqlite3
sys.path.insert(0, 'backend')
from database.db import engine, get_db
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

db = next(get_db())

# Step 1: Check how many invoices exist with UIDs
result = db.execute(text('SELECT id, invoice_id, uid FROM invoices WHERE invoice_id LIKE :p ORDER BY id DESC LIMIT 5'), {'p': 'LCL-%'})
rows = result.fetchall()
print("Sample LCL invoices (local id, invoice_id, uid):")
for r in rows: print(" ", r)

# Step 2: Check line items count per invoice
result = db.execute(text('SELECT invoice_id, COUNT(*) FROM invoice_line_items GROUP BY invoice_id ORDER BY invoice_id DESC LIMIT 10'))
print("\nLine items per invoice_id (top 10):")
for r in result.fetchall(): print(" ", r)

# Step 3: Check if there are any line items without business_id
result = db.execute(text('SELECT COUNT(*) FROM invoice_line_items'))
total = result.scalar()
print(f"\nTotal line items in DB: {total}")

# Step 4: Simulate what happens if we import a line item for LCL-OW-0019 (id=816)
inv = db.execute(text("SELECT id, invoice_id, uid FROM invoices WHERE invoice_id='LCL-OW-0019'")).fetchone()
if inv:
    print(f"\nLCL-OW-0019: local id={inv[0]}, uid={inv[2]}")
    # If cloud_pk was e.g. 19, id_maps["invoices"][19] = 816
    # A line item with invoice_id=19 would be remapped to 816
    # Try inserting a test line item
    try:
        db.execute(text("""
            INSERT INTO invoice_line_items 
            (invoice_id, product_name, quantity, unit_price, line_total, unit, created_at, updated_at)
            VALUES (:iid, 'TEST ITEM', 1, 100, 100, 'Nos', datetime('now'), datetime('now'))
        """), {'iid': inv[0]})
        db.rollback()
        print("  -> Test insert succeeded (then rolled back)")
    except Exception as e:
        db.rollback()
        print(f"  -> Test insert FAILED: {e}")
else:
    print("LCL-OW-0019 not found in local DB")

db.close()
