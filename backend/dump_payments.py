import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

# Get some payments with their invoice and payment modes
cur.execute("""
SELECT p.id, p.payment_date, p.amount_paid, p.payment_mode, p.invoice_id
FROM invoice_payments p
""")
rows = cur.fetchall()
print("All rows in invoice_payments table:")
for r in rows:
    print("  ", r)

conn.close()
