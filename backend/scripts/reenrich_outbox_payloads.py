#!/usr/bin/env python
"""
reenrich_outbox_payloads.py — put the missing parent `*_uid` back in the outbox.

WHY
---
A payload only carries a portable `<fk>_uid` if it was built by
`_serialize_orm_obj` WITH a connection. Rows queued another way — a raw-SQL
repair script, an older heal scan using `_row_to_dict` — carry the bare local
integer FK instead. The receiver then has nothing to resolve against:

  · NOT NULL parent  → the row is deferred for ever.
  · NULLABLE parent  → the link is DROPPED (M-9 set_null) and a ConflictLog is
                       written. Until 8d5b5f4 that log itself violated a NOT
                       NULL constraint and aborted the whole push transaction
                       (rule 58), so one such row froze a business's sync
                       entirely, retrying every 15 s.

Observed on business 126 → cloud 7: three B2B invoices carrying
`customer_id = 67874273` with no `customer_uid`, from
`link_b2b_invoice_customers.py` writing over raw DB-API (no mapper events, so
no enrichment).

`_repair_stuck_child_payloads` already does this for CHILD tables
(invoice_line_items, invoice_payments …). It does not cover a parent row's own
foreign keys, such as `invoices.customer_id` — which is the case that bit.

WHY THIS IS THE BETTER FIX
--------------------------
Fixing only the receiver makes the push succeed with the link set to NULL. That
is safe but lossy: it silently discards the customer linkage. Re-enriching here
sends the uid, so the receiver resolves the RIGHT customer and the link
survives. Run this first; the receiver fix is the backstop.

    python scripts/reenrich_outbox_payloads.py
    python scripts/reenrich_outbox_payloads.py --apply

Local only — the outbox is per-device. Run it wherever the rows are stuck.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

os.environ.setdefault("GROQ_API_KEY", "mock")

from _dbcompat import out, use_utf8_stdout           # noqa: E402


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Re-enrich pending outbox payloads with parent uids.")
    ap.add_argument("--apply", action="store_true",
                    help="actually rewrite the payloads (default is a dry run)")
    ap.add_argument("--business", type=int, default=None,
                    help="limit to one business id")
    args = ap.parse_args()

    from database.db import SessionLocal, engine
    from database.models import _serialize_orm_obj
    from database.sync_map import MODEL_MAP
    from sqlalchemy import text

    db = SessionLocal()
    mode = "APPLYING" if args.apply else "DRY RUN"
    out(f"\n  reenrich_outbox_payloads — {mode}\n")

    try:
        q = ("SELECT id, business_id, entity, entity_id, payload FROM sync_queue "
             "WHERE synced_at IS NULL")
        params = {}
        if args.business is not None:
            q += " AND business_id = :b"
            params["b"] = args.business
        rows = db.execute(text(q + " ORDER BY id"), params).fetchall()

        if not rows:
            out("  Outbox is empty. Nothing to do.\n")
            return 0

        patched = 0
        skipped = 0
        with engine.connect() as conn:
            for r in rows:
                qid, bid, entity, entity_id, payload = r[0], r[1], r[2], r[3], r[4]
                model = MODEL_MAP.get(entity)
                if model is None or not payload:
                    continue

                obj = db.query(model).filter(model.id == entity_id).first()
                if obj is None:
                    # The row is gone locally — a DELETE, or already purged.
                    skipped += 1
                    continue

                try:
                    old = json.loads(payload)
                except Exception:
                    old = {}

                fresh = _serialize_orm_obj(obj, conn)
                added = [k for k in fresh if k.endswith("_uid") and k not in old]
                if not added:
                    continue

                out(f"  queue #{qid} biz={bid} {entity}#{entity_id}: + {', '.join(sorted(added))}")
                patched += 1
                if args.apply:
                    db.execute(
                        text("UPDATE sync_queue SET payload = :p WHERE id = :i"),
                        {"p": json.dumps(fresh, default=str), "i": qid},
                    )

        if args.apply:
            db.commit()
            out(f"\n  Re-enriched {patched} payload(s). The next push carries the uids.")
        else:
            out(f"\n  Would re-enrich {patched} payload(s). Re-run with --apply.")
        if skipped:
            out(f"  {skipped} row(s) skipped — the source row no longer exists locally.")
        out("")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
