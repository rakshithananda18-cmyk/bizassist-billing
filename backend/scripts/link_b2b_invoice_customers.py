#!/usr/bin/env python
"""
link_b2b_invoice_customers.py — give existing B2B sale invoices their customer FK.

WHY
---
A B2B counterparty is a customer to the seller exactly as it is a vendor to the
buyer. The buyer half has always said so: `_ensure_buyer_purchase_invoice`
resolves a `Vendor` and stores `purchase_invoices.supplier_id`.

The seller half did not. `core/order/service.py` created the sale invoice with

    customer=buyer.business_name          # a NAME
                                          # and no customer_id

so every B2B sale carried a customer name against a NULL `invoices.customer_id`.
Consequences, both visible in the UI:

  · The invoice falls into Contacts & Payments → "Other Invoices", which filters
    on `NOT customer_id`, and is stamped UNLINKED.
  · It never appears in that buyer's ledger, because the ledger joins on the FK.
    A connected business could have bought from you repeatedly and shown a zero
    balance.

Accepting a B2B connection creates no `customers` row either — nothing in
`core/connection/` writes one — so there was usually no row to point at.

The service now resolves-or-creates the customer at order-sync time
(`_seller_customer_for_order`). This script is the other half: the invoices that
were already written before that landed.

WHAT IT MATCHES ON
------------------
The invoice's OWN `customer` name string, scoped to the invoice's business —
not the buyer's `users` row. Deliberate: on a LOCAL database the counterparty
business does not exist in `users` at all (it lives in the other side's DB), so
a users-driven lookup would find nothing and skip every row on the one database
the owner actually looks at. The name is on the invoice, on both sides.

Where the buyer's `users` row IS present, a newly created customer is enriched
with its gstin / phone / email / address / state_code / pan. Where it is not,
the customer is created with the name alone, which is exactly what the invoice
knows.

⚠ THIS CHANGE DOES NOT PROPAGATE
--------------------------------
Like every script in this directory it writes over a raw DB-API connection, so
SQLAlchemy's mapper events never fire and nothing is queued into `sync_queue`.
**Run it on each database you want changed.**

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required to write anything.
* `--apply` against Postgres additionally requires
  `--i-have-a-restorable-backup`.
* Only ever fills a NULL. A row whose `customer_id` is already set is skipped
  and counted — an existing link is never repointed.
* Never touches an amount, a status, a date or a line item.
* Idempotent: a second run finds the FKs set and reports nothing to do.
* Prints every row it would change, before changing it.

USAGE
-----
    python scripts/link_b2b_invoice_customers.py                    # dry run, local
    python scripts/link_b2b_invoice_customers.py --db "$CLOUD_URL"  # dry run, cloud
    python scripts/link_b2b_invoice_customers.py --db "$CLOUD_URL" --apply \
        --i-have-a-restorable-backup
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from _dbcompat import (connect, is_postgres_target, out,      # noqa: E402
                       resolve_target, use_utf8_stdout)

# Enrichment columns copied onto a NEWLY created customer when the counterparty
# business is present in `users` on this database. Never used to UPDATE an
# existing customer row — that is the owner's data, not ours to overwrite.
_ENRICH = ("gstin", "phone", "email", "address", "state_code", "pan")


def _orm_defaults() -> dict:
    """Columns the ORM fills in PYTHON, which a raw INSERT therefore must supply.

    `uid` is declared `nullable=True` on the model but the live table is NOT
    NULL — the first --apply run died on exactly that. It is also the key
    cross-database sync matches on (integer ids differ per database), so a
    customer created without one would be unmatchable on the other side, which
    is worse than the crash.

    Timestamps are stored by SQLAlchemy as naive ISO-8601 with microseconds
    ('2026-06-21T20:14:55.864254'); written as a string in the same shape so
    SQLite keeps one format across the table and Postgres casts it cleanly.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    return {"uid": str(uuid.uuid4()), "created_at": now, "updated_at": now}


def _unlinked_b2b_invoices(con):
    """B2B sale invoices with a customer name but no customer FK."""
    return con.execute(
        """
        SELECT i.id, i.business_id, i.invoice_id, i.customer, i.total_amount
          FROM invoices i
         WHERE i.customer_id IS NULL
           AND i.customer IS NOT NULL
           AND TRIM(i.customer) <> ''
           AND (i.invoice_type = 'B2B' OR i.invoice_id LIKE 'B2B-%')
         ORDER BY i.business_id, i.id
        """
    ).fetchall()


def _find_customer(con, business_id, name):
    row = con.execute(
        "SELECT id FROM customers WHERE business_id = ? AND name = ? LIMIT 1",
        (business_id, name),
    ).fetchone()
    return row["id"] if row else None


def _buyer_profile(con, business_id, name):
    """The counterparty's `users` row, if this database happens to hold it."""
    if not con.table_exists("users"):
        return {}
    cols = ", ".join(_ENRICH)
    row = con.execute(
        f"SELECT {cols} FROM users WHERE business_name = ? "
        f"AND parent_business_id IS NULL AND id <> ? LIMIT 1",
        (name, business_id),
    ).fetchone()
    return {c: row[c] for c in _ENRICH} if row else {}


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Link existing B2B sale invoices to a customer record.")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default is a dry run)")
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack",
                    help="required with --apply against a Postgres database")
    args = ap.parse_args()

    target = resolve_target(args.db)
    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  Refusing to --apply against Postgres without "
            "--i-have-a-restorable-backup.\n"
            "  This writes an FK onto live financial documents with no .bak "
            "beside them.\n\n"
            "  Take a backup first, then re-run with "
            "--i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    out(f"\n  link_b2b_invoice_customers — {mode} against {con.label}\n")

    for table in ("invoices", "customers"):
        if not con.table_exists(table):
            out(f"  No `{table}` table on this database. Nothing to do.")
            return 0

    rows = _unlinked_b2b_invoices(con)
    if not rows:
        out("  No unlinked B2B invoices. Nothing to do.\n")
        return 0

    out(f"  {len(rows)} unlinked B2B invoice(s):\n")

    # (business_id, name) -> customer id, so N invoices for one buyer resolve
    # once and cannot create N duplicate customer rows in a single run.
    resolved: dict[tuple, int] = {}
    created = 0
    linked = 0

    for r in rows:
        bid, name = r["business_id"], (r["customer"] or "").strip()
        key = (bid, name)

        if key in resolved:
            # Cached even when the lookup found nothing, so a buyer with N
            # invoices counts as ONE new customer. Without this the dry run
            # promised 3 customers for 2 buyers, and a dry run that does not
            # predict --apply is worse than no dry run.
            cid = resolved[key]
            note = "existing customer" if cid else "NEW customer (same as above)"
        else:
            cid = _find_customer(con, bid, name)
            note = "existing customer"
            if cid is None:
                note = "NEW customer"
                created += 1
                if args.apply:
                    profile = _buyer_profile(con, bid, name)
                    cols = ["business_id", "name", "is_active"]
                    vals = [bid, name, 1]
                    for col, val in _orm_defaults().items():
                        cols.append(col)
                        vals.append(val)
                    for c in _ENRICH:
                        if profile.get(c) is not None:
                            cols.append(c)
                            vals.append(profile[c])
                    placeholders = ",".join("?" for _ in vals)
                    con.execute(
                        f'INSERT INTO customers ({",".join(cols)}) '
                        f'VALUES ({placeholders})',
                        tuple(vals),
                    )
                    cid = _find_customer(con, bid, name)
            resolved[key] = cid

        out(f"    biz {bid:>5}  {str(r['invoice_id']):<28} "
            f"{name:<24} -> {note}")

        if args.apply and cid is not None:
            con.execute(
                "UPDATE invoices SET customer_id = ? "
                "WHERE id = ? AND business_id = ? AND customer_id IS NULL",
                (cid, r["id"], bid),
            )
            linked += 1

    out("")
    if not args.apply:
        out(f"  DRY RUN — would link {len(rows)} invoice(s), "
            f"creating {created} customer(s).")
        out("  Re-run with --apply to write.\n")
        return 0

    # Verify before commit: nothing in the set we just handled may still be NULL.
    remaining = con.scalar(
        """
        SELECT COUNT(*) FROM invoices
         WHERE customer_id IS NULL
           AND customer IS NOT NULL AND TRIM(customer) <> ''
           AND (invoice_type = 'B2B' OR invoice_id LIKE 'B2B-%')
        """, default=0)
    if remaining:
        con.rollback()
        out(f"  ROLLED BACK — {remaining} invoice(s) still unlinked after the "
            f"pass. Nothing was written.\n")
        return 1

    con.commit()
    out(f"  Linked {linked} invoice(s); created {created} customer(s).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
