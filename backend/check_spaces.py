import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

cur.execute("SELECT id, payment_mode FROM invoice_payments")
for r in cur.fetchall():
    print(r[0], repr(r[1]))

conn.close()
