"""
repair_pass2.py
===============
Second-pass repair for invoices STILL missing line items after reconstruct_line_items.py.
Falls back to matching stock_ledger entries by the `note` field ("sale INVOICE_NO")
when reference_id doesn't directly match the invoice PK (happens when the sync
remapped stock_ledger reference_ids incorrectly).

Run from backend/ directory:
    python repair_pass2.py
"""
import sqlite3, datetime, uuid

conn = sqlite3.connect('bizassist.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

now = datetime.datetime.now(datetime.timezone.utc).isoformat()

# Find invoices STILL with 0 line items
cur.execute("""
SELECT i.id, i.invoice_id, i.total_amount, i.business_id
FROM invoices i
WHERE (SELECT COUNT(*) FROM invoice_line_items li WHERE li.invoice_id = i.id) = 0
  AND i.invoice_id NOT LIKE 'OPEN-%'
  AND i.invoice_id NOT LIKE 'B2B-%'
ORDER BY i.id
""")
still_missing = cur.fetchall()
print(f"Invoices still missing line items: {len(still_missing)}")
for row in still_missing:
    print(f"  id={row['id']}  {row['invoice_id']}  total={row['total_amount']}")

print()
repaired = 0
skipped  = 0

for inv in still_missing:
    inv_id  = inv['id']
    inv_no  = inv['invoice_id']
    inv_tot = inv['total_amount']

    # Try to find stock ledger entries whose note references this invoice number
    cur.execute("""
        SELECT product_id, product_name, qty_delta
        FROM stock_ledger
        WHERE movement_type = 'sale'
          AND (note = ? OR note LIKE ?)
        ORDER BY id
    """, (f'sale {inv_no}', f'%{inv_no}%'))
    movements = cur.fetchall()

    if not movements:
        print(f"  SKIP  {inv_no}: no stock ledger match by note either")
        skipped += 1
        continue

    # Check for duplicates – skip if line items already added by another pass
    cur.execute("SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id=?", (inv_id,))
    if cur.fetchone()[0] > 0:
        print(f"  SKIP  {inv_no}: already has line items now")
        skipped += 1
        continue

    line_items = []
    for mv in movements:
        pid  = mv['product_id']
        pname = mv['product_name']
        qty  = abs(mv['qty_delta'])

        prod = None
        if pid:
            cur.execute("""
                SELECT selling_price, cgst_rate, sgst_rate, igst_rate, unit, hsn_sac
                FROM products WHERE id = ?
            """, (pid,))
            prod = cur.fetchone()

        unit_price = (prod['selling_price'] if prod else 0) or 0
        cgst_rate  = (prod['cgst_rate']     if prod else 0) or 0
        sgst_rate  = (prod['sgst_rate']     if prod else 0) or 0
        igst_rate  = (prod['igst_rate']     if prod else 0) or 0
        unit       = (prod['unit']          if prod else 'Nos') or 'Nos'
        hsn_sac    = (prod['hsn_sac']       if prod else None)

        taxable   = round(qty * unit_price, 2)
        cgst_amt  = round(taxable * cgst_rate / 100, 2)
        sgst_amt  = round(taxable * sgst_rate / 100, 2)
        igst_amt  = round(taxable * igst_rate / 100, 2)
        line_total = round(taxable + cgst_amt + sgst_amt + igst_amt, 2)

        line_items.append({
            'invoice_id':    inv_id,
            'product_id':    pid,
            'product_name':  pname,
            'hsn_sac':       hsn_sac,
            'unit':          unit,
            'quantity':      qty,
            'unit_price':    unit_price,
            'discount':      0,
            'taxable_value': taxable,
            'cgst_rate':     cgst_rate,
            'cgst_amount':   cgst_amt,
            'sgst_rate':     sgst_rate,
            'sgst_amount':   sgst_amt,
            'igst_rate':     igst_rate,
            'igst_amount':   igst_amt,
            'cess_rate':     0,
            'cess_amount':   0,
            'line_total':    line_total,
            'uid':           str(uuid.uuid4()),
            'created_at':    now,
            'updated_at':    now,
        })

    inserted = 0
    for li in line_items:
        cols = ', '.join(f'"{k}"' for k in li)
        phs  = ', '.join(f':{k}' for k in li)
        try:
            cur.execute(f'INSERT INTO invoice_line_items ({cols}) VALUES ({phs})', li)
            inserted += 1
        except Exception as e:
            print(f"    ERROR {inv_no}/{li['product_name']}: {e}")

    computed = sum(li['line_total'] for li in line_items)
    print(f"  OK    {inv_no}: {inserted} lines inserted  "
          f"(computed~{computed:.2f}, recorded={inv_tot:.2f})")
    repaired += 1

conn.commit()

# Final summary
cur.execute("SELECT COUNT(*) FROM invoice_line_items")
total_li = cur.fetchone()[0]
conn.close()

print(f"\nPass-2 done. Repaired={repaired} Skipped={skipped}")
print(f"Total line items now: {total_li}")
