#!/usr/bin/env python
"""
repair_b2b_invoice_lines.py — rebuild a B2B sale invoice's missing line items
from the order lines still held in `sync_inbox`.

WHY
---
`create_sale_invoice` used to treat ANY existing invoice with a matching number
as an idempotent hit and return it unchanged (core/billing/commands.py). When
the row it found was a HEADER that had synced ahead of its lines, completing the
B2B order handed that empty header straight back: the caller's lines were
discarded and the seller's stock deduction was skipped with it. The buyer,
posted by a later step, got a complete purchase bill. That guard now refuses —
this script repairs the documents it already produced.

MEASURED CASE (business 126, invoice B2B-ORD-20260805-0001)
-----------------------------------------------------------
Header present with subtotal 1545.11 and a 1731.00 payment; ZERO line items;
no `b2b_orders` row locally (its inbox row is rejected on the pre-740b11e
payload format and the cloud does not re-offer it). The six real order lines
are sitting in `sync_inbox` as held `b2b_order_line_items`, and they sum to
exactly 1545.11 — which is what makes this reconstruction safe rather than a
guess. They also match, item for item, the buyer's purchase bill.

WHERE TO RUN IT
---------------
On the database that ORIGINATED the invoice. For the measured case that is the
local SQLite: invoice 10830 sits in `sync_queue` (an outbox INSERT) with no
inbox row, so this machine is where it was created and the cloud's copy came
from here.

⚠ UNLIKE EVERY OTHER SCRIPT HERE, THIS ONE **DOES** PROPAGATE
--------------------------------------------------------------
The others write over a raw DB-API connection precisely so that nothing syncs.
This one writes through the ORM session on purpose: `invoice_line_items` is a
synced entity, the business is `hybrid`, and lines that never leave this device
would rebuild the document locally while the cloud copy stayed broken. The rows
are queued by the normal mapper events and push like any other edit.

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required to write anything.
* REFUSES unless the reconstructed taxable total matches the invoice's stored
  `subtotal` to the paisa. A mismatch means the held lines are not this
  invoice's lines, and inventing the difference would be fabricating money.
* REFUSES if the invoice already has line items. It only ever fills a gap; it
  never edits, replaces or de-duplicates an existing line.
* Line math is `core.billing.commands._compute_line` — the same function the
  real sale path uses, not a re-implementation that could drift from it.
* Intra/inter is taken from the STORED rates, not recomputed from today's state
  configuration, because the job is to reproduce the document as issued.
* DOES NOT POST STOCK. The skipped sale movements are reported and left alone:
  back-dating stock silently changes today's on-hand figure, and whether to do
  that is the owner's call, not a repair script's.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _dbcompat import out, use_utf8_stdout  # noqa: E402

PAISA = 0.01


def _held_order_lines(db, order_number: str) -> list[dict]:
    """The order's line payloads still parked in the inbox, de-duplicated.

    The cloud re-offers a held row rather than adding a second one, but a row
    parked under two different business_ids (buyer AND seller both hold a copy)
    appears twice. Key on the row's own uid so each real line counts once.
    """
    from database.models import SyncInbox

    orders = [
        json.loads(r.payload) for r in
        db.query(SyncInbox).filter(SyncInbox.entity == "b2b_orders").all()
    ]
    order_ids = {o["id"] for o in orders if o.get("order_number") == order_number}
    if not order_ids:
        return []

    by_uid: dict[str, dict] = {}
    for r in db.query(SyncInbox).filter(SyncInbox.entity == "b2b_order_line_items").all():
        d = json.loads(r.payload)
        if d.get("order_id") in order_ids:
            by_uid[d.get("uid") or f"id:{d.get('id')}"] = d
    return list(by_uid.values())


def _post_stock(db, inv, args) -> int:
    """Second pass: the SALE movements the dropped lines took with them.

    Separate and opt-in because it is a different kind of write. Rebuilding the
    lines restores a DOCUMENT to what it always said it was; posting stock moves
    TODAY's on-hand figure. Same reference (`invoice` / invoice.id) and the same
    `record_movement` the real sale path uses, so the resulting ledger rows are
    indistinguishable from ones posted at the time.
    """
    from database.models import InvoiceLineItem, Product
    from core.models import StockLedger
    from core.stock import ledger as SL

    lines = db.query(InvoiceLineItem).filter(
        InvoiceLineItem.invoice_id == inv.id).all()
    if not lines:
        out("\nRefusing — no line items on this invoice. Rebuild the lines first "
            "(run without --post-stock); stock must follow the document, not "
            "precede it.")
        return 1

    existing_moves = db.query(StockLedger).filter(
        StockLedger.business_id == args.business,
        StockLedger.reference_type == "invoice",
        StockLedger.reference_id == inv.id).count()
    if existing_moves:
        out(f"\nRefusing — {existing_moves} stock movement(s) already reference this "
            "invoice. Posting again would deduct the same sale twice.")
        return 1

    out(f"\n{'PRODUCT':26} {'ON HAND':>9} {'QTY':>6} {'AFTER':>9}")
    planned = []
    for ln in lines:
        product = (db.query(Product)
                   .filter(Product.id == ln.product_id,
                           Product.business_id == args.business).first())
        tracked = True if product is None else (product.track_inventory is not False)
        if not tracked or not ln.quantity:
            out(f"  {str(ln.product_name)[:24]:24} {'—':>9} {'—':>6} "
                f"{'(not stock-tracked)':>9}")
            continue
        cur = SL.current_stock(db, args.business, product_id=ln.product_id)
        after = cur - float(ln.quantity)
        flag = "  <-- would go NEGATIVE" if after < 0 else ""
        out(f"  {str(ln.product_name)[:24]:24} {cur:>9} {ln.quantity:>6} {after:>9}{flag}")
        planned.append(ln)

    if not planned:
        out("\nNothing to post — no stock-tracked line on this invoice.")
        return 0

    if not args.apply:
        out(f"\nDRY RUN — nothing written. Re-run with --apply --post-stock to post "
            f"{len(planned)} movement(s).")
        return 0

    for ln in planned:
        SL.record_movement(
            db, business_id=args.business, movement_type=SL.SALE,
            qty_delta=-float(ln.quantity),
            product_id=ln.product_id, product_name=ln.product_name,
            reference_type="invoice", reference_id=inv.id,
            note=f"sale {inv.invoice_id} (repaired)",
            batch_no=ln.batch_no, expiry_date=ln.expiry_date,
        )
    db.commit()
    out(f"\nAPPLIED. {len(planned)} SALE movement(s) posted against invoice {inv.id}.")
    return 0


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--invoice-no", required=True,
                    help="the sale invoice number, e.g. B2B-ORD-20260805-0001")
    ap.add_argument("--business", type=int, required=True,
                    help="business_id that owns the invoice (LOCAL id)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    ap.add_argument("--post-stock", action="store_true", dest="post_stock",
                    help="second pass: post the SALE movements the dropped lines "
                         "took with them. Requires the lines to be back already, "
                         "and refuses if any movement for this invoice exists.")
    args = ap.parse_args()

    from core.billing.commands import _compute_line, _round2
    from database.db import SessionLocal
    from database.models import Invoice, InvoiceLineItem, Product
    from core.models import StockLedger

    db = SessionLocal()
    mode = "APPLYING" if args.apply else "DRY RUN"
    out("=" * 78)
    out(f"REPAIR B2B INVOICE LINES  [{mode}]")
    out(f"  invoice: {args.invoice_no}   business_id: {args.business}")
    out("=" * 78)

    try:
        inv = (db.query(Invoice)
               .filter(Invoice.business_id == args.business,
                       Invoice.invoice_id == args.invoice_no).first())
        if inv is None:
            out(f"\nNo invoice {args.invoice_no} for business {args.business}.")
            return 1

        existing = db.query(InvoiceLineItem).filter(
            InvoiceLineItem.invoice_id == inv.id).count()
        out(f"\nInvoice row id : {inv.id}")
        out(f"Stored subtotal: {inv.subtotal}")
        out(f"Stored total   : {inv.total_amount}")
        out(f"Existing lines : {existing}")

        if args.post_stock:
            return _post_stock(db, inv, args)

        if existing:
            out("\nRefusing — this invoice already has line items. This script only "
                "fills a gap; it never edits or replaces what is there.")
            return 1

        order_number = args.invoice_no[4:] if args.invoice_no.startswith("B2B-") else args.invoice_no
        held = _held_order_lines(db, order_number)
        out(f"\nHeld order lines recoverable from sync_inbox: {len(held)}  "
            f"(order {order_number})")
        if not held:
            out("\nNothing to rebuild from — no held b2b_order_line_items match "
                "this order. Stopping rather than inventing lines.")
            return 1

        # Reproduce the document as ISSUED: if any line carried IGST it was an
        # inter-state sale, whatever the current state configuration would say.
        intra = not any(float(h.get("igst_rate") or 0) > 0 for h in held)

        computed = []
        for h in held:
            product = (db.query(Product)
                       .filter(Product.id == h.get("product_id"),
                               Product.business_id == args.business).first())
            computed.append(_compute_line(h, product, intra=intra, tax_inclusive=False))

        rebuilt = _round2(sum(c["taxable_value"] for c in computed))
        stored = _round2(float(inv.subtotal or 0.0))

        out(f"\n{'ITEM':26} {'QTY':>6} {'RATE':>10} {'TAXABLE':>10}")
        for c in computed:
            out(f"  {str(c['product_name'])[:24]:24} {c['quantity']:>6} "
                f"{c['unit_price']:>10} {c['taxable_value']:>10}")
        out(f"\n  rebuilt taxable total : {rebuilt}")
        out(f"  invoice stored subtotal: {stored}")

        if abs(rebuilt - stored) > PAISA:
            out(f"\nREFUSING — the rebuilt total differs by {abs(rebuilt - stored):.2f}. "
                "These are not this invoice's lines, and making up the difference "
                "would be fabricating money.")
            return 1
        out("  MATCH ✓  (within one paisa)")

        moves = db.query(StockLedger).filter(
            StockLedger.business_id == args.business,
            StockLedger.reference_type == "invoice",
            StockLedger.reference_id == inv.id).count()
        out(f"\nStock movements already posted for this invoice: {moves}")
        if not moves:
            out("  ⚠ The sale was never deducted from stock — the same guard that")
            out("    dropped these lines skipped the movements with them. This script")
            out("    does NOT post them: back-dating stock changes today's on-hand")
            out("    figure, and that is the owner's decision. Adjust stock explicitly")
            out("    once these lines are back.")

        if not args.apply:
            out(f"\nDRY RUN — nothing written. Re-run with --apply to insert "
                f"{len(computed)} line(s).")
            return 0

        for c in computed:
            db.add(InvoiceLineItem(invoice_id=inv.id, **c))
        db.commit()
        out(f"\nAPPLIED. {len(computed)} line(s) written to invoice {inv.id}.")
        out("They are queued by the normal mapper events and will push to the cloud "
            "with the next sync cycle.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
