import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

# Check stock_ledger for sale movements referencing LCL-* invoices
cur.execute("""
SELECT sl.reference_id, sl.product_name, sl.product_id, 
       sl.qty_delta, sl.movement_type, sl.note,
       i.invoice_id, i.total_amount
FROM stock_ledger sl
JOIN invoices i ON i.id = sl.reference_id
WHERE sl.movement_type = 'sale'
  AND i.invoice_id LIKE 'LCL-%'
ORDER BY sl.reference_id, sl.id
""")
print("Stock ledger entries for LCL-* invoices (sale movements):")
rows = cur.fetchall()
if rows:
    for r in rows: print(' ', r)
else:
    print("  (none found)")

print()

# Check all sale movements
cur.execute("SELECT COUNT(*) FROM stock_ledger WHERE movement_type='sale'")
print("Total sale movements in stock_ledger:", cur.fetchone()[0])

cur.execute("SELECT movement_type, COUNT(*) FROM stock_ledger GROUP BY movement_type")
print("All movement types:", cur.fetchall())

conn.close()
