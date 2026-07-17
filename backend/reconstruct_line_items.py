"""
reconstruct_line_items.py
=========================
Rebuilds missing invoice_line_items from stock_ledger sale movements.

The stock_ledger records every sale as: product_name, product_id, qty_delta (negative),
reference_id (= invoice.id), note (= 'sale INVOICE_NO').

For each LCL-* invoice that has 0 line items but has stock ledger entries,
this script:
  1. Finds matching stock movements
  2. Looks up the product's unit_price and tax rates from the products table
  3. Computes line_total = qty * unit_price  (approximate; does not re-derive tax splits)
  4. Inserts an InvoiceLineItem row for each movement

Run from the backend/ directory:
    python reconstruct_line_items.py
"""
import sqlite3, datetime, uuid

conn = sqlite3.connect('bizassist.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ── Find all LCL-* invoices with 0 line items but stock ledger entries ───────
cur.execute("""
SELECT i.id, i.invoice_id, i.business_id, i.total_amount,
       i.subtotal, i.cgst_total, i.sgst_total, i.igst_total,
       i.discount_total, i.round_off, i.is_tax_inclusive
FROM invoices i
WHERE i.invoice_id LIKE 'LCL-%'
  AND (SELECT COUNT(*) FROM invoice_line_items li WHERE li.invoice_id = i.id) = 0
  AND (SELECT COUNT(*) FROM stock_ledger sl WHERE sl.reference_id = i.id AND sl.movement_type = 'sale') > 0
ORDER BY i.id
""")
orphans = cur.fetchall()
print(f"Found {len(orphans)} LCL-* invoices to reconstruct from stock ledger\n")

reconstructed = 0
skipped = 0
now = datetime.datetime.utcnow().isoformat()

for inv in orphans:
    inv_id    = inv['id']
    inv_no    = inv['invoice_id']
    biz_id    = inv['business_id']
    inv_total = inv['total_amount'] or 0

    # Fetch stock ledger movements for this invoice
    cur.execute("""
        SELECT product_id, product_name, qty_delta
        FROM stock_ledger
        WHERE reference_id = ? AND movement_type = 'sale'
        ORDER BY id
    """, (inv_id,))
    movements = cur.fetchall()

    if not movements:
        print(f"  SKIP {inv_no}: no sale movements found (shouldn't happen)")
        skipped += 1
        continue

    # Look up product details for pricing
    line_items = []
    for mv in movements:
        pid   = mv['product_id']
        pname = mv['product_name']
        qty   = abs(mv['qty_delta'])

        # Get product unit_price and tax rates
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

        # Compute line amounts (simple: no discount, tax-exclusive)
        taxable    = round(qty * unit_price, 2)
        cgst_amt   = round(taxable * cgst_rate / 100, 2)
        sgst_amt   = round(taxable * sgst_rate / 100, 2)
        igst_amt   = round(taxable * igst_rate / 100, 2)
        line_total = round(taxable + cgst_amt + sgst_amt + igst_amt, 2)

        line_items.append({
            'invoice_id':     inv_id,
            'product_id':     pid,
            'product_name':   pname,
            'hsn_sac':        hsn_sac,
            'unit':           unit,
            'quantity':       qty,
            'unit_price':     unit_price,
            'discount':       0,
            'taxable_value':  taxable,
            'cgst_rate':      cgst_rate,
            'cgst_amount':    cgst_amt,
            'sgst_rate':      sgst_rate,
            'sgst_amount':    sgst_amt,
            'igst_rate':      igst_rate,
            'igst_amount':    igst_amt,
            'cess_rate':      0,
            'cess_amount':    0,
            'line_total':     line_total,
            'uid':            str(uuid.uuid4()),
            'created_at':     now,
            'updated_at':     now,
        })

    # Insert all line items
    inserted = 0
    for li in line_items:
        cols = ', '.join(f'"{k}"' for k in li)
        phs  = ', '.join(f':{k}' for k in li)
        try:
            cur.execute(f'INSERT INTO invoice_line_items ({cols}) VALUES ({phs})', li)
            inserted += 1
        except Exception as e:
            print(f"    ERROR inserting line for {inv_no}/{li['product_name']}: {e}")

    computed_total = sum(li['line_total'] for li in line_items)
    print(f"  OK  {inv_no}: inserted {inserted} lines, computed~Rs.{computed_total:.2f}, recorded=Rs.{inv_total:.2f}")
    reconstructed += 1

conn.commit()
conn.close()
print(f"\nDone. Reconstructed={reconstructed}  Skipped={skipped}")
print("NOTE: line totals are approximate (current product prices used; discounts not restored).")
print("The invoice header totals (which ARE correct) take precedence for display.")
