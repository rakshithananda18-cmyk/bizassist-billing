"""
repair_line_items.py — One-time repair for orphaned LCL-* invoices.

The cloud→local sync (before the remap_ids fix) imported invoices with new local
PKs (803–816) but the line items still carried the cloud's FK values (e.g. 1, 2, 3...)
which never matched the new local PKs. This script:

  1. Finds all invoices that have 0 line items but a non-zero total (orphaned).
  2. Looks for the matching OLD-style invoice (same invoice_id without the LCL- prefix,
     or by invoice_id from the cloud via the subtotal match) — if found, copies the
     line items over to the new invoice PK.
  3. Reports what was done.

Run from the project root:
    python repair_line_items.py
"""
import sqlite3, sys, re

DB = "backend/bizassist.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ── 1. Find orphaned LCL invoices ───────────────────────────────────────────
cur.execute("""
SELECT i.id, i.invoice_id, i.total_amount, i.subtotal, i.business_id
FROM   invoices i
LEFT JOIN invoice_line_items li ON li.invoice_id = i.id
WHERE  i.invoice_id LIKE 'LCL-%'
GROUP  BY i.id
HAVING COUNT(li.id) = 0
ORDER  BY i.id
""")
orphans = cur.fetchall()
print(f"Found {len(orphans)} orphaned LCL-* invoices (0 line items)")

repaired = 0
skipped  = 0

for inv in orphans:
    lcl_id       = inv["id"]
    lcl_inv_no   = inv["invoice_id"]          # e.g. LCL-C1-0004
    total        = inv["total_amount"]
    business_id  = inv["business_id"]

    # Strip the LCL- prefix to get the bare invoice number (e.g. C1-0004)
    bare_no = re.sub(r'^LCL-', '', lcl_inv_no)   # C1-0004

    # Look for an old invoice with the same bare number and same business
    cur.execute(
        "SELECT id, invoice_id FROM invoices WHERE invoice_id = ? AND business_id = ? AND id != ?",
        (bare_no, business_id, lcl_id)
    )
    donor = cur.fetchone()

    if not donor:
        # Also try matching by total + business where the old row has line items
        cur.execute("""
            SELECT i.id, i.invoice_id
            FROM   invoices i
            JOIN   invoice_line_items li ON li.invoice_id = i.id
            WHERE  i.business_id = ? AND ABS(i.total_amount - ?) < 0.05
            GROUP  BY i.id
            HAVING COUNT(li.id) > 0
            LIMIT  1
        """, (business_id, total))
        donor = cur.fetchone()

    if not donor:
        print(f"  SKIP  {lcl_inv_no}: no donor invoice found")
        skipped += 1
        continue

    donor_id     = donor["id"]
    donor_inv_no = donor["invoice_id"]

    # Count existing lines on the donor
    cur.execute("SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id = ?", (donor_id,))
    n_lines = cur.fetchone()[0]
    if n_lines == 0:
        print(f"  SKIP  {lcl_inv_no}: donor {donor_inv_no} also has 0 line items")
        skipped += 1
        continue

    # Copy line items from donor → orphan (with new auto-increment ids)
    cur.execute("""
        SELECT product_name, description, hsn_sac, batch_no, serial_no,
               quantity, unit, unit_price, discount, taxable_value,
               cgst_rate, cgst_amount, sgst_rate, sgst_amount,
               igst_rate, igst_amount, cess_amount, line_total,
               created_at, updated_at, business_id
        FROM   invoice_line_items
        WHERE  invoice_id = ?
    """, (donor_id,))
    lines = cur.fetchall()

    inserted = 0
    for line in lines:
        cur.execute("""
            INSERT INTO invoice_line_items
              (invoice_id, product_name, description, hsn_sac, batch_no, serial_no,
               quantity, unit, unit_price, discount, taxable_value,
               cgst_rate, cgst_amount, sgst_rate, sgst_amount,
               igst_rate, igst_amount, cess_amount, line_total,
               created_at, updated_at, business_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (lcl_id,) + tuple(line))
        inserted += 1

    print(f"  OK    {lcl_inv_no} ← {donor_inv_no}: copied {inserted} line items")
    repaired += 1

conn.commit()
conn.close()
print(f"\nDone. Repaired={repaired}  Skipped={skipped}")
