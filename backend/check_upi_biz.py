import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

# Get business_id for the user 'Varshini'
cur.execute("SELECT id, username, parent_business_id FROM users WHERE username = 'Varshini'")
print("Varshini user info:", cur.fetchone())

# Dump invoice_payments with business_id
cur.execute("""
SELECT p.id, p.payment_mode, p.invoice_id, p.business_id, i.invoice_id, i.business_id
FROM invoice_payments p
LEFT JOIN invoices i ON i.id = p.invoice_id
WHERE p.payment_mode = 'upi'
""")
print("\nUPI payments in invoice_payments table:")
for r in cur.fetchall():
    print("  ", r)

conn.close()
