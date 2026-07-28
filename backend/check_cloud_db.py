"""
Connect directly to the cloud Supabase Postgres and check the actual
state of LCL-OW-0021 line items and payments.
"""
import sys, json
sys.path.insert(0, ".")

# Cloud Supabase connection (from .env comment)
CLOUD_DB = "postgresql://postgres.edvttytmqqijmctuiexe:BizAssist%40Passw0rd@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

try:
    import psycopg2
    conn = psycopg2.connect(CLOUD_DB)
except ImportError:
    # Try via SQLAlchemy which may have psycopg2 bundled
    from sqlalchemy import create_engine, text as sa_text
    engine = create_engine(CLOUD_DB)
    conn = None

if conn:
    cur = conn.cursor()

    # 1. Find the cloud invoice for LCL-OW-0021 by UID
    TARGET_UID = "63a9cb21-e5e5-4575-b7e6-aae318e0ab53"
    cur.execute(
        "SELECT id, invoice_id, uid, total_amount, status FROM invoices WHERE uid = %s",
        (TARGET_UID,)
    )
    inv = cur.fetchone()
    if not inv:
        print("ERROR: LCL-OW-0021 (uid=63a9cb21...) NOT FOUND on cloud")
        sys.exit(1)
    cloud_id, inv_num, uid, total, status = inv
    print(f"=== CLOUD invoice LCL-OW-0021 ===")
    print(f"  cloud_id={cloud_id}  uid={uid!r}  total={total}  status={status}")

    # 2. Cloud line items for this invoice (by cloud FK)
    cur.execute(
        "SELECT li.id, li.uid, p.name, li.quantity, li.line_total "
        "FROM invoice_line_items li LEFT JOIN products p ON p.id=li.product_id "
        "WHERE li.invoice_id = %s ORDER BY li.id",
        (cloud_id,)
    )
    items = cur.fetchall()
    print(f"\n  CLOUD line items for cloud_invoice#{cloud_id} (LCL-OW-0021):")
    for r in items:
        print(f"    li#{r[0]}  uid={r[1]!r}  {r[2]}  qty={r[3]}  total={r[4]}")

    # 3. Cloud line items linked by UID (our corrective UPDATE used invoice_id_uid=63a9cb21)
    # Check if the correct UIDs (Sunflower Oil li#152, Detergent li#153) are on the right invoice
    for li_uid in ("8a6f1797-01ef-4b33-ad62-721e69962d6f", "4dc2d6d3-af29-445b-9dbd-26c45212ddfa"):
        cur.execute(
            "SELECT li.id, li.invoice_id, li.uid, p.name, i.invoice_id as inv_num, i.uid as inv_uid "
            "FROM invoice_line_items li LEFT JOIN products p ON p.id=li.product_id "
            "LEFT JOIN invoices i ON i.id=li.invoice_id "
            "WHERE li.uid = %s",
            (li_uid,)
        )
        r = cur.fetchone()
        if r:
            match = "(CORRECT)" if r[2] == li_uid and r[5] == TARGET_UID else "(WRONG INVOICE)"
            print(f"\n  li uid={li_uid!r}: {match}")
            print(f"    cloud li#{r[0]}  attached to cloud_invoice#{r[1]} ({r[4]})  inv_uid={r[5]!r}")
            print(f"    product={r[3]}")
        else:
            print(f"\n  li uid={li_uid!r}: NOT FOUND on cloud")

    # 4. Cloud payment for LCL-OW-0021
    cur.execute(
        "SELECT id, uid, amount_paid, note, invoice_id FROM invoice_payments "
        "WHERE uid = %s",
        ("1f64dfd6-85ca-45ef-92bc-c6742c9629d4",)
    )
    pay = cur.fetchone()
    if pay:
        correct = "(CORRECT)" if pay[4] == cloud_id else f"(WRONG: attached to cloud_invoice#{pay[4]})"
        print(f"\n  Payment uid=1f64dfd6-...: {correct}")
        print(f"    cloud pay#{pay[0]}  amount={pay[2]}  invoice_id={pay[4]}  note={pay[3]!r}")
    else:
        print("\n  Payment uid=1f64dfd6-...: NOT FOUND on cloud")

    # 5. What invoice does cloud integer id=817 correspond to?
    cur.execute("SELECT id, invoice_id, uid, total_amount FROM invoices WHERE id = 817")
    wrong_inv = cur.fetchone()
    if wrong_inv:
        print(f"\n  Cloud invoice#817 (the wrong target): {wrong_inv[1]}  uid={wrong_inv[2]!r}  total={wrong_inv[3]}")
    else:
        print("\n  Cloud invoice#817: does not exist")

    cur.close()
    conn.close()
