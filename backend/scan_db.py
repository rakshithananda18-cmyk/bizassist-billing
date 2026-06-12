"""One-off DB scan — table row counts + how much of the relational layer is populated."""
import sqlite3, os

DB = "bizassist.db"
print("DB:", os.path.abspath(DB), "exists:", os.path.exists(DB))
con = sqlite3.connect(DB)
c = con.cursor()

print("\n=== TABLE ROW COUNTS ===")
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
for t in tabs:
    try:
        n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except Exception as e:
        n = f"err: {e}"
    print(f"  {t:24} {n}")


def count(sql):
    try:
        return c.execute(sql).fetchone()[0]
    except Exception as e:
        return f"err: {e}"


print("\n=== HOW POPULATED IS THE RELATIONAL LAYER? ===")
print("  invoices total                :", count("SELECT COUNT(*) FROM invoices"))
print("  invoices linked (customer_id) :", count("SELECT COUNT(*) FROM invoices WHERE customer_id IS NOT NULL"))
print("  distinct invoice customers    :", count("SELECT COUNT(DISTINCT customer) FROM invoices"))
print("  customers (master) total      :", count("SELECT COUNT(*) FROM customers"))
print("  customers w/ email            :", count("SELECT COUNT(*) FROM customers WHERE email IS NOT NULL AND email!=''"))
print("  customers w/ phone            :", count("SELECT COUNT(*) FROM customers WHERE phone IS NOT NULL AND phone!=''"))
print("  inventory total               :", count("SELECT COUNT(*) FROM inventory"))
print("  inventory w/ cost_price>0     :", count("SELECT COUNT(*) FROM inventory WHERE cost_price > 0"))
print("  inventory w/ selling_price>0  :", count("SELECT COUNT(*) FROM inventory WHERE selling_price > 0"))
print("  inventory w/ supplier         :", count("SELECT COUNT(*) FROM inventory WHERE supplier IS NOT NULL AND supplier!=''"))
print("  payments total                :", count("SELECT COUNT(*) FROM payments"))
print("  vendors / products / POs      :",
      count("SELECT COUNT(*) FROM vendors"),
      count("SELECT COUNT(*) FROM products"),
      count("SELECT COUNT(*) FROM purchase_orders"))

print("\n=== INVOICE STATUS BREAKDOWN ===")
for row in c.execute("SELECT status, COUNT(*), ROUND(SUM(amount)) FROM invoices GROUP BY status"):
    print(" ", row)

print("\n=== SAMPLE INVOICE ROW ===")
cols = [d[1] for d in c.execute("PRAGMA table_info('invoices')")]
row = c.execute("SELECT * FROM invoices LIMIT 1").fetchone()
if row:
    for k, v in zip(cols, row):
        print(f"  {k:16} = {v}")
con.close()
