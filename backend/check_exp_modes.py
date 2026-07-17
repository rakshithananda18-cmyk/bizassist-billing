import sqlite3
conn = sqlite3.connect('bizassist.db')
cur = conn.cursor()

# Get distinct payment modes from expenses table
cur.execute("SELECT DISTINCT payment_mode FROM expenses")
print("Distinct modes in expenses table:", [r[0] for r in cur.fetchall()])

conn.close()
