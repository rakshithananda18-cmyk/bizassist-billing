#!/usr/bin/env python
"""
queue_never_queued_rows.py — enqueue rows the heal scan is designed to skip.

WHY THIS IS SEPARATE FROM THE HEAL SCAN
---------------------------------------
`find_unqueued_syncable_rows` only considers rows NEWER than the oldest outbox
entry for the business, and that bound is correct: older rows legitimately have
no outbox row (they predate hybrid mode, or their entries were pruned), and
queueing them automatically would re-push years of history on every cycle.

But the bound has a consequence. A row older than the floor that is REFERENCED
by something newer can never be sent, so the newer row defers against a parent
the cloud will never receive. Business 126 had 25 customers and exactly 2 had
ever been queued; three invoices referenced customer 51, which predated the
floor, so they deferred indefinitely — and the line items and payments behind
them deferred on those.

So the floor stays automatic, and crossing it is a deliberate, per-entity,
operator-run decision. That is this script.

SAFETY
------
· Dry run by default; `--apply` writes.
· Goes through `queue_row_if_absent`, the only sanctioned way into `sync_queue`,
  so it cannot stack a duplicate against `uix_sync_queue_pending_target`.
· Payloads are built by `_serialize_orm_obj` WITH a live connection, so every
  parent uid is present — an unenriched payload is what strands a row.
· Refuses append-only entities outright. Re-pushing an invoice is not a repair.

    python scripts/queue_never_queued_rows.py --business 126 --entity customers
    python scripts/queue_never_queued_rows.py --business 126 --entity customers --apply
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
        description="Queue syncable rows that have never been in the outbox.")
    ap.add_argument("--business", type=int, required=True)
    ap.add_argument("--entity", required=True,
                    help="one syncable entity, e.g. customers")
    ap.add_argument("--apply", action="store_true",
                    help="actually queue them (default is a dry run)")
    args = ap.parse_args()

    from sqlalchemy import text
    from database.db import SessionLocal
    from database.models import _serialize_orm_obj, queue_row_if_absent
    from database.sync_map import MODEL_MAP, APPEND_ONLY_DELETE_BLOCKLIST

    entity = args.entity
    model = MODEL_MAP.get(entity)
    if model is None:
        sys.exit(f"\n  '{entity}' is not a syncable entity.\n")

    # An append-only document is history, not state. Back-filling one is not a
    # repair — if the cloud is missing invoices, that is a reconciliation
    # question with money in it, not a queueing one.
    if entity in APPEND_ONLY_DELETE_BLOCKLIST:
        sys.exit(
            f"\n  Refusing to back-fill '{entity}' — it is an append-only "
            "financial document.\n  Re-pushing history is not a repair; "
            "reconcile it deliberately instead.\n")

    db = SessionLocal()
    mode = "APPLYING" if args.apply else "DRY RUN"
    out(f"\n  queue_never_queued_rows — {mode} · biz {args.business} · {entity}\n")

    try:
        rows = db.execute(text(
            f'SELECT t.id FROM "{entity}" t '
            f'WHERE t.business_id = :b AND NOT EXISTS ('
            f'  SELECT 1 FROM sync_queue q WHERE q.entity = :e AND q.entity_id = t.id) '
            f'ORDER BY t.id'
        ), {"b": args.business, "e": entity}).fetchall()

        if not rows:
            out("  Every row is already accounted for in the outbox. Nothing to do.\n")
            return 0

        out(f"  {len(rows)} {entity} row(s) have NEVER been queued:\n")
        conn = db.connection()
        queued = 0
        for r in rows:
            obj = db.query(model).filter(model.id == r[0]).first()
            if obj is None:
                continue
            label = getattr(obj, "name", None) or getattr(obj, "uid", "") or obj.id
            out(f"    {entity}#{obj.id}  {label}")
            if args.apply:
                payload = json.dumps(_serialize_orm_obj(obj, conn), default=str)
                queue_row_if_absent(conn, business_id=args.business, entity=entity,
                                    entity_id=obj.id, operation="INSERT",
                                    payload=payload)
                queued += 1

        if args.apply:
            db.commit()
            out(f"\n  Queued {queued} row(s). The next push cycle sends them.")
        else:
            out(f"\n  Would queue {len(rows)} row(s). Re-run with --apply.")
        out("")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
