import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

# Get unique payment modes from payments table
cur.execute("SELECT DISTINCT payment_mode FROM payments")
p_modes = [r[0] for r in cur.fetchall() if r[0]]
print("Distinct modes in payments table:", p_modes)

# Get unique payment modes from invoice_payments table
cur.execute("SELECT DISTINCT payment_mode FROM invoice_payments")
ip_modes = [r[0] for r in cur.fetchall() if r[0]]
print("Distinct modes in invoice_payments table:", ip_modes)

conn.close()
