import sqlite3
conn = sqlite3.connect('backend/bizassist.db')
cur = conn.cursor()

cur.execute("""
SELECT i.invoice_id, i.total_amount, COUNT(li.id) as items
FROM invoices i 
LEFT JOIN invoice_line_items li ON li.invoice_id = i.id 
WHERE i.invoice_id LIKE 'LCL-%'
GROUP BY i.id 
ORDER BY i.id DESC 
LIMIT 10
""")
print("LCL invoices and item counts:")
for r in cur.fetchall():
    print(r)

cur.execute("SELECT COUNT(*) FROM invoice_line_items")
print("Total line items:", cur.fetchone())

cur.execute("SELECT DISTINCT invoice_id FROM invoice_line_items")
ids = [r[0] for r in cur.fetchall()]
print("invoice_ids with line items:", ids)

cur.execute("SELECT id, invoice_id FROM invoices WHERE id IN ({})".format(",".join("?" * len(ids))), ids)
print("Those invoices:", cur.fetchall())

conn.close()
