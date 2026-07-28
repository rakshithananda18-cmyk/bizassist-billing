import psycopg2, json

CLOUD_DB = "postgresql://postgres.edvttytmqqijmctuiexe:BizAssist%40Passw0rd@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"

TARGET_INV_UID = "63a9cb21-e5e5-4575-b7e6-aae318e0ab53"
LI_UID_SUNFLOWER  = "8a6f1797-01ef-4b33-ad62-721e69962d6f"
LI_UID_DETERGENT  = "4dc2d6d3-af29-445b-9dbd-26c45212ddfa"
PAY_UID           = "1f64dfd6-85ca-45ef-92bc-c6742c9629d4"

conn = psycopg2.connect(CLOUD_DB)
cur  = conn.cursor()

# 1. Find the cloud invoice for LCL-OW-0021 by UID
cur.execute("SELECT id, invoice_id, uid, total_amount, status FROM invoices WHERE uid = %s", (TARGET_INV_UID,))
inv = cur.fetchone()
if not inv:
    print("LCL-OW-0021 NOT FOUND on cloud by uid"); cur.close(); conn.close(); exit()

cloud_id, inv_num, uid, total, status = inv
print(f"=== CLOUD invoice ===")
print(f"  cloud_id={cloud_id}  invoice_id={inv_num}  uid={uid}  total={total}  status={status}")

# 2. Line items currently attached to this cloud invoice (by FK)
cur.execute(
    "SELECT li.id, li.uid, li.product_name, li.quantity, li.line_total, li.invoice_id "
    "FROM invoice_line_items li WHERE li.invoice_id = %s ORDER BY li.id",
    (cloud_id,)
)
items = cur.fetchall()
print(f"\n  Cloud line items for cloud_invoice#{cloud_id} ({len(items)} rows):")
for r in items:
    print(f"    cloud_li#{r[0]}  uid={r[1]!r}  {r[2]}  qty={r[3]}  total={r[4]}  invoice_id={r[5]}")

# 3. Where are the CORRECT items (Sunflower Oil + Detergent) right now?
print(f"\n  Sunflower Oil li uid={LI_UID_SUNFLOWER}:")
cur.execute(
    "SELECT li.id, li.uid, li.product_name, li.invoice_id, i.invoice_id as inv_num, i.uid as inv_uid "
    "FROM invoice_line_items li LEFT JOIN invoices i ON i.id=li.invoice_id "
    "WHERE li.uid = %s", (LI_UID_SUNFLOWER,)
)
r = cur.fetchone()
if r:
    match = "CORRECT" if r[5] == TARGET_INV_UID else f"WRONG — on invoice {r[4]} (uid={r[5]})"
    print(f"    cloud_li#{r[0]}  product={r[2]}  invoice_id={r[3]}  -> {r[4]}  [{match}]")
else:
    print("    NOT FOUND on cloud")

print(f"\n  Detergent Powder li uid={LI_UID_DETERGENT}:")
cur.execute(
    "SELECT li.id, li.uid, li.product_name, li.invoice_id, i.invoice_id as inv_num, i.uid as inv_uid "
    "FROM invoice_line_items li LEFT JOIN invoices i ON i.id=li.invoice_id "
    "WHERE li.uid = %s", (LI_UID_DETERGENT,)
)
r = cur.fetchone()
if r:
    match = "CORRECT" if r[5] == TARGET_INV_UID else f"WRONG — on invoice {r[4]} (uid={r[5]})"
    print(f"    cloud_li#{r[0]}  product={r[2]}  invoice_id={r[3]}  -> {r[4]}  [{match}]")
else:
    print("    NOT FOUND on cloud")

# 4. Where is the 824 payment right now?
print(f"\n  Payment uid={PAY_UID}:")
cur.execute(
    "SELECT p.id, p.uid, p.amount_paid, p.invoice_id, i.invoice_id as inv_num, i.uid as inv_uid "
    "FROM invoice_payments p LEFT JOIN invoices i ON i.id=p.invoice_id "
    "WHERE p.uid = %s", (PAY_UID,)
)
r = cur.fetchone()
if r:
    match = "CORRECT" if r[5] == TARGET_INV_UID else f"WRONG — on invoice {r[4]} (uid={r[5]})"
    print(f"    cloud_pay#{r[0]}  amount={r[2]}  invoice_id={r[3]}  -> {r[4]}  [{match}]")
else:
    print("    NOT FOUND on cloud")

# 5. What invoice is cloud integer id=817 ?
cur.execute("SELECT id, invoice_id, uid, total_amount FROM invoices WHERE id = 817")
r817 = cur.fetchone()
print(f"\n  Cloud invoice#817 (the wrong target): {r817}")

# 6. What payments does cloud LCL-OW-0021 (cloud_id) actually have?
cur.execute(
    "SELECT id, uid, amount_paid, note FROM invoice_payments WHERE invoice_id = %s ORDER BY id",
    (cloud_id,)
)
pays = cur.fetchall()
print(f"\n  Payments currently on cloud_invoice#{cloud_id} ({len(pays)} rows):")
for r in pays:
    print(f"    cloud_pay#{r[0]}  uid={r[1]!r}  amount={r[2]}  note={r[3]!r}")

cur.close(); conn.close()
