"""
repair_duplicate_line_items.py  v2
====================================
Removes ALL invoice_line_items rows created on 2026-07-17 that are spurious.

CLASSIFICATION (from audit):
- TRUE DUPLICATES (24 rows): Jul 17 row has exact match (same product/price/qty)
  among pre-Jul-17 rows on the same invoice. Safe to delete.
- "NO ORIGINAL" rows (39 rows): Jul 17 row has no pre-Jul-17 counterpart,
  but the invoice header (total_amount) was set at creation time BEFORE Jul 17.
  If header total = sum(pre-Jul-17 lines), these extra lines are also spurious.

VERIFICATION LOGIC:
  For each affected invoice, check:
    pre_lines_sum ≈ invoice.total_amount  →  all Jul 17 rows on that invoice are spurious
    pre_lines_sum ≠ invoice.total_amount  →  flag for manual review, do not auto-delete

SAFETY: dry-run by default. --apply to execute. Full rollback on error.
"""

import sqlite3, sys

DRY_RUN = "--apply" not in sys.argv
DB = "backend/bizassist.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

# All rows inserted Jul 17
jul17 = c.execute("""
    SELECT li.id, li.product_name, li.unit_price, li.quantity, li.line_total,
           li.created_at, i.id AS inv_db_id, i.invoice_id AS inv_no,
           i.business_id, i.total_amount, i.created_at AS inv_created
    FROM invoice_line_items li
    JOIN invoices i ON i.id=li.invoice_id
    WHERE li.created_at >= '2026-07-17' AND li.created_at < '2026-07-18'
    ORDER BY i.business_id, i.invoice_id, li.id
""").fetchall()

# Group by invoice
from collections import defaultdict
by_inv = defaultdict(list)
for r in jul17:
    by_inv[r['inv_db_id']].append(dict(r))

to_delete = []
to_review = []

for inv_db_id, bad_rows in by_inv.items():
    inv_no = bad_rows[0]['inv_no']
    bid = bad_rows[0]['business_id']
    header_total = bad_rows[0]['total_amount']
    inv_created = bad_rows[0]['inv_created']

    # Sum of lines created BEFORE Jul 17 for this invoice
    pre = c.execute("""
        SELECT SUM(line_total) FROM invoice_line_items
        WHERE invoice_id=? AND created_at < '2026-07-17'
    """, (inv_db_id,)).fetchone()[0] or 0.0

    # Does pre-Jul-17 sum match header total?
    pre_matches_header = abs(pre - header_total) <= 0.60  # GST round-off tolerance (max observed: ₹0.50)

    bad_ids = [r['id'] for r in bad_rows]
    bad_sum = sum(r['line_total'] for r in bad_rows)

    print(f"  {inv_no} (biz {bid}): header={header_total:.2f}  "
          f"pre_lines_sum={pre:.2f}  match={pre_matches_header}  "
          f"bad_rows={len(bad_rows)}  bad_sum={bad_sum:.2f}")

    if pre_matches_header:
        to_delete.extend(bad_ids)
    else:
        # Pre-Jul-17 lines don't account for the header — maybe the script
        # added legitimate missing lines. Flag for review.
        to_review.extend(bad_rows)
        print(f"    ⚠ FLAGGED — pre-lines ({pre:.2f}) ≠ header ({header_total:.2f})")
        for r in bad_rows:
            print(f"      id={r['id']}  {r['product_name']}  "
                  f"price={r['unit_price']}  qty={r['quantity']}")

print()
print(f"Safe to delete: {len(to_delete)} rows")
print(f"Flagged for review: {len(to_review)} rows")

print()
print("=== PRE-DELETION P&L ===")
def pnl(conn, bid):
    rev = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE business_id=? AND coalesce(invoice_type,'')!='credit_note'", (bid,)).fetchone()[0] or 0
    cogs = conn.execute("""SELECT SUM(p.cost_price*li.quantity) FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id LEFT JOIN products p ON p.id=li.product_id WHERE i.business_id=? AND coalesce(i.invoice_type,'')!='credit_note' AND p.cost_price>0""", (bid,)).fetchone()[0] or 0
    lc = conn.execute("SELECT COUNT(*) FROM invoice_line_items li JOIN invoices i ON i.id=li.invoice_id WHERE i.business_id=?", (bid,)).fetchone()[0]
    return rev, cogs, lc

for bid in [6, 7]:
    rev, cogs, lc = pnl(c, bid)
    print(f"  biz {bid}: revenue={rev:.2f}  cogs={cogs:.2f}  "
          f"gross_profit={rev-cogs:.2f}  lines={lc}")

if DRY_RUN:
    print()
    print("DRY RUN — no changes made. Re-run with --apply to execute.")
    sys.exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
print()
print("=== APPLYING DELETION ===")
if not to_delete:
    print("Nothing to delete.")
    sys.exit(0)

try:
    ph = ','.join('?' * len(to_delete))
    c.execute(f"DELETE FROM invoice_line_items WHERE id IN ({ph})", to_delete)
    deleted = c.total_changes
    c.commit()
    print(f"  Deleted {deleted} rows. Committed.")
except Exception as e:
    c.rollback()
    print(f"  ERROR: {e} — rolled back.")
    sys.exit(1)

print()
print("=== POST-DELETION P&L ===")
for bid in [6, 7]:
    rev, cogs, lc = pnl(c, bid)
    print(f"  biz {bid}: revenue={rev:.2f}  cogs={cogs:.2f}  "
          f"gross_profit={rev-cogs:.2f}  lines={lc}")

if to_review:
    print()
    print(f"=== {len(to_review)} ROWS STILL NEED MANUAL REVIEW ===")
    print("  These rows were created Jul 17 but pre-Jul-17 lines don't match")
    print("  the invoice header total — meaning they may be legitimate additions.")
    for r in to_review:
        print(f"  id={r['id']}  biz={r['business_id']}  inv={r['inv_no']}  "
              f"{r['product_name']}  price={r['unit_price']}  qty={r['quantity']}")
