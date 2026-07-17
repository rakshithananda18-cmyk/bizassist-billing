import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

# All non-LCL invoices with their line item counts
cur.execute("""
SELECT i.id, i.invoice_id, i.total_amount, COUNT(li.id) as items
FROM invoices i
LEFT JOIN invoice_line_items li ON li.invoice_id = i.id
WHERE i.invoice_id NOT LIKE 'LCL-%'
GROUP BY i.id ORDER BY i.id DESC LIMIT 15
""")
print("Non-LCL invoices and item counts:")
for r in cur.fetchall(): print(' ', r)

print()

# All LCL-* invoices with their line item counts
cur.execute("""
SELECT i.id, i.invoice_id, i.total_amount, COUNT(li.id) as items
FROM invoices i
LEFT JOIN invoice_line_items li ON li.invoice_id = i.id
WHERE i.invoice_id LIKE 'LCL-%'
GROUP BY i.id ORDER BY i.id DESC LIMIT 15
""")
print("LCL-* invoices and item counts:")
for r in cur.fetchall(): print(' ', r)

print()

# Look for any line items that do exist and what invoices they match
cur.execute("""
SELECT li.invoice_id, i.invoice_id as inv_no, li.product_name, li.line_total
FROM invoice_line_items li 
JOIN invoices i ON i.id = li.invoice_id
ORDER BY li.invoice_id
""")
print("All existing line items with their invoice:")
for r in cur.fetchall(): print(' ', r)

conn.close()
