"""
scripts/reconcile_local_vs_cloud.py — which local rows never reached the cloud?
==============================================================================
Opens BOTH databases and compares them by `uid`, the durable cross-database key.
Read-only by default. `--requeue` reopens outbox rows so the sync worker sends
the missing ones again; it touches `sync_queue` ONLY and never business data.

    python scripts/reconcile_local_vs_cloud.py
    python scripts/reconcile_local_vs_cloud.py --biz BA-Y0DAFT
    python scripts/reconcile_local_vs_cloud.py --requeue --i-have-a-restorable-backup

WHY THIS EXISTS
---------------
M-20 (see docs/STRATEGIC_REVIEW_JUL2026.md §66): the cloud DEFERRED a row whose
parent FK it could not resolve and expected the device to send it again; the
device acked it and dropped its only copy. A real Rs641 sale (`LCL-OW-0028`) was
deleted this way on 2026-07-27, with both sides reporting success.

That defect is fixed. Two things it does NOT do:

  * it cannot un-ack a row that was already acked — `synced_at` is set, the
    worker only looks at `synced_at IS NULL`, and nothing re-sends it;
  * it says nothing about how long this was happening before it was noticed.

Both need the same answer: **compare the two databases and see what is missing.**

WHY `uid` AND NOT `id`
----------------------
Integer ids are allocated per database. Local business 7 is cloud business 42;
the same B2B order reads seller 6 -> buyer 87 locally and 7 -> 19 on the cloud.
Comparing by id would produce confident nonsense. `uid` is the durable key the
sync map matches on, and businesses are matched by `users.public_id` (BizID),
which is the only identifier that means the same thing in both places.

WHAT A DIFFERENCE MEANS — stated, not assumed
---------------------------------------------
A row present locally and absent on the cloud is NOT automatically a lost write:

  * it may be legitimately queued right now (`synced_at IS NULL`) — that is the
    M-20 fix working, and the row is safe;
  * it may belong to a PULL_ONLY family the device is not allowed to push;
  * it may never have been queued at all (M-20a), in which case the outbox has
    no record and requeuing here is the only way it will ever go.

The report separates those cases rather than totalling them, because they need
different responses and only one of them is an emergency.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dbcompat import (connect, is_postgres_target, out,  # noqa: E402
                       use_utf8_stdout)

# Tables worth comparing: they carry money or the parents money depends on, and
# every one of them has a `uid`. Ordered parents-first so the output reads the
# way the sync applies them — a missing parent explains its missing children.
ENTITIES = [
    ("register_shifts", "the register a sale was rung on. A missing shift "
                        "strands EVERY invoice on it (M-20)"),
    ("customers", "the buyer on an invoice"),
    ("products", "referenced by line items and stock"),
    ("invoices", "the sale itself"),
    ("invoice_payments", "receipts against a sale"),
    ("shift_cash_movements", "paid in/out against a drawer"),
    ("expenses", "money out"),
]

# PULL-ONLY families are mirrored cloud->local and must never be pushed up, so
# "missing from the cloud" is meaningless for them. Listed to be skipped rather
# than silently absent from the report.
PULL_ONLY = {"b2b_connections", "b2b_orders", "b2b_order_line_items"}


def _hosting_mode(settings_json):
    """'hybrid' | 'cloud' | 'local' | None — what this business is set up to do.

    A business in `local` mode, or with no settings at all, DOES NOT SYNC. It is
    supposed to be absent from the cloud, and reporting that as a finding is
    crying wolf — the failure mode this review keeps warning about, in the tool
    written to police it. Only a business that is CONFIGURED to sync and is
    nevertheless missing is worth an alarm.
    """
    if not settings_json:
        return None
    try:
        import json
        return (json.loads(settings_json).get("general", {})
                .get("hosting_mode") or None)
    except Exception:
        return None


SYNCING_MODES = {"hybrid", "cloud"}


def _biz_map(local, cloud):
    """-> (mapped, unmapped, not_syncing)

    Matched on `users.public_id`, the only identifier meaning the same thing in
    both databases. Businesses that are not configured to sync are separated
    out: their absence from the cloud is correct, not a finding.
    """
    lrows = local.execute(
        "SELECT id, public_id, business_name, settings FROM users "
        "WHERE parent_business_id IS NULL").fetchall()
    crows = {r["public_id"]: int(r["id"]) for r in cloud.execute(
        "SELECT id, public_id FROM users WHERE public_id IS NOT NULL")}
    mapped, unmapped, not_syncing = {}, [], []
    for r in lrows:
        pub = (r["public_id"] or "").strip()
        mode = _hosting_mode(r["settings"])
        if pub and pub in crows:
            mapped[int(r["id"])] = (pub, crows[pub])
            continue
        row = (int(r["id"]), pub or None, r["business_name"], mode)
        if mode not in SYNCING_MODES:
            not_syncing.append(row)          # correctly absent
        else:
            unmapped.append(row)             # configured to sync, and is NOT there
    return mapped, unmapped, not_syncing


def _cloud_uids(cloud, entity, cloud_bid):
    if not cloud.table_exists(entity):
        return None
    scope = ""
    cols = _columns(cloud, entity)
    if "business_id" in cols:
        scope = f" WHERE business_id = {int(cloud_bid)}"
    return {r["uid"] for r in cloud.execute(
        f"SELECT uid FROM {entity}{scope}") if r["uid"]}


def _columns(c, table):
    if c.dialect == "sqlite":
        return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    return {r["column_name"] for r in c.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ?", (table,))}


def compare(local, cloud, only_biz=None):
    mapped, unmapped, not_syncing = _biz_map(local, cloud)
    if unmapped:
        out("\n  CONFIGURED TO SYNC BUT ABSENT FROM THE CLOUD:")
        for lid, pub, name, mode in unmapped:
            out(f"    local biz {lid:<6} {str(pub or '(no BizID)'):<12} "
                f"{str(name)[:24]:<26} hosting_mode={mode}")
        out("    ^ these SHOULD be on the cloud and are not. Nothing they own")
        out("      can be compared, which is a larger finding than any single row.")
    if not_syncing:
        out("\n  [info] not configured to sync, so correctly absent from the cloud:")
        for lid, pub, name, mode in not_syncing:
            out(f"    local biz {lid:<6} {str(pub or '(no BizID)'):<12} "
                f"{str(name)[:24]:<26} hosting_mode={mode or '(none)'}")
        out("    ^ NOT a finding. Listed so the report cannot be read as having")
        out("      checked them (rule 33), but a business in local mode is")
        out("      supposed to be absent.")

    findings = []
    for lbid, (pub, cbid) in sorted(mapped.items()):
        if only_biz and only_biz not in (pub, str(lbid)):
            continue
        header_done = False
        for entity, why in ENTITIES:
            if entity in PULL_ONLY or not local.table_exists(entity):
                continue
            cols = _columns(local, entity)
            if "uid" not in cols:
                continue
            scope = f" WHERE business_id = {int(lbid)}" if "business_id" in cols else ""
            lrows = local.execute(
                f"SELECT id, uid FROM {entity}{scope}").fetchall()
            lmap = {r["uid"]: int(r["id"]) for r in lrows if r["uid"]}
            cuids = _cloud_uids(cloud, entity, cbid)
            if cuids is None:
                continue
            missing = {u: i for u, i in lmap.items() if u not in cuids}
            if not missing:
                continue

            # Split by what the outbox says, because the three cases need
            # different responses and only one of them is an emergency.
            queued, acked, never = [], [], []
            for uid, rid in missing.items():
                q = local.execute(
                    "SELECT synced_at FROM sync_queue WHERE entity = ? "
                    "AND entity_id = ? ORDER BY id DESC LIMIT 1",
                    (entity, rid)).fetchone()
                if q is None:
                    never.append((uid, rid))
                elif q["synced_at"] is None:
                    queued.append((uid, rid))
                else:
                    acked.append((uid, rid))

            if not header_done:
                out(f"\n  {pub}  (local biz {lbid} -> cloud biz {cbid})")
                header_done = True
            out(f"    {entity}: {len(missing)} row(s) missing from the cloud"
                f"  [{why}]")
            if queued:
                out(f"       {len(queued):>4} still QUEUED - safe, the worker "
                    f"will re-send (M-20 fix working)")
            if acked:
                out(f"       {len(acked):>4} ACKED BUT ABSENT - the outbox thinks "
                    f"they synced. They will NEVER be re-sent.")
                for uid, rid in acked[:10]:
                    out(f"            id={rid} uid={uid}")
            if never:
                out(f"       {len(never):>4} NEVER QUEUED - no outbox row ever "
                    f"existed (M-20a). Nothing will ever send them.")
                for uid, rid in never[:10]:
                    out(f"            id={rid} uid={uid}")
            findings.append({"biz": pub, "local_bid": lbid, "entity": entity,
                             "acked": acked, "never": never, "queued": queued})
    return findings


def requeue(local, findings):
    """Reopen the outbox for rows the cloud does not have.

    Writes to `sync_queue` ONLY — never to a business table. Two cases:

      * ACKED BUT ABSENT: clear `synced_at` on the existing row so the worker
        picks it up again.
      * NEVER QUEUED: insert a fresh outbox row WITH A PAYLOAD built from the
        live row.

    MY MISTAKE, RECORDED BECAUSE IT WAS LIVE FOR A FEW MINUTES.
    The first version of this inserted `payload = NULL` and this docstring
    claimed "the payload is rebuilt by the worker from the live row". It is not.
    `services/sync_worker.py` reads `if item.payload:` and, when it is NULL,
    pushes `payload: None` — the cloud then applies `data = change.payload or {}`,
    an empty dict. For `register_shifts` that is a row with no user, no status
    and no start time, which fails its NOT NULL constraints and comes back as a
    rejection.

    I asserted a behaviour instead of reading it, in a tool written for a
    session about exactly that habit. The payload is now built here, from the
    row that exists, at the moment of requeue.

    Rows still legitimately queued are left alone — they are already going.
    """
    reopened = inserted = skipped_no_row = 0
    for f in findings:
        for uid, rid in f["acked"]:
            # REFRESH THE PAYLOAD, do not just clear synced_at.
            #
            # The first version only did `SET synced_at = NULL`, assuming the
            # existing outbox row was usable. It is not always: a row that was
            # dead-lettered for having NO payload is ACKED (synced_at set), so
            # it lands in this branch — and reopening it without a payload just
            # puts the same unusable row back, to be dead-lettered again next
            # cycle. Reopen, dead-letter, reopen: a loop I created within
            # minutes of adding the dead-letter guard.
            #
            # Refreshing is also more correct in general: the outbox payload is
            # a snapshot from write time, and a re-push should carry what the
            # row says NOW. The cloud resolves LWW on updated_at either way.
            payload = _row_payload(local, f["entity"], rid)
            if payload is None:
                out(f"    SKIPPED {f['entity']}#{rid}: the row no longer exists "
                    f"locally, so there is nothing to re-send.")
                skipped_no_row += 1
                continue
            local.execute(
                "UPDATE sync_queue SET synced_at = NULL, payload = ?, "
                "error = 'requeued: absent from cloud (M-20)' "
                "WHERE entity = ? AND entity_id = ?", (payload, f["entity"], rid))
            reopened += 1
        for uid, rid in f["never"]:
            payload = _row_payload(local, f["entity"], rid)
            if payload is None:
                out(f"    SKIPPED {f['entity']}#{rid}: the row could not be read, "
                    f"so no payload can be built. NOT queued - an empty payload "
                    f"would be rejected by the cloud.")
                continue
            local.execute(
                "INSERT INTO sync_queue (business_id, entity, entity_id, "
                "operation, payload, created_at) "
                "VALUES (?, ?, ?, 'INSERT', ?, CURRENT_TIMESTAMP)",
                (f["local_bid"], f["entity"], rid, payload))
            inserted += 1
    return reopened, inserted


def _row_payload(local, entity, row_id):
    """JSON for one live row, in the shape the sync push expects.

    Built from the row's own columns so it can never carry stale data: it is
    whatever the row says right now. Returns None if the row is gone, so the
    caller can decline rather than queue an empty write.
    """
    import json
    r = local.execute(f"SELECT * FROM {entity} WHERE id = ?", (row_id,)).fetchone()
    if r is None:
        return None
    d = {}
    for k in r.keys():
        v = r[k]
        d[k] = v if (v is None or isinstance(v, (int, float, str, bool))) else str(v)
    return json.dumps(d, default=str)


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local", default=None, help="local SQLite path")
    ap.add_argument("--cloud", default=None,
                    help="cloud URL; defaults to $BIZASSIST_AUDIT_DATABASE_URL")
    ap.add_argument("--biz", default=None, help="one BizID, e.g. BA-Y0DAFT")
    ap.add_argument("--requeue", action="store_true",
                    help="reopen outbox rows for what the cloud lacks. Writes to "
                         "sync_queue only, never to business data.")
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    local_path = args.local or os.path.join(os.path.dirname(here), "bizassist.db")
    cloud_url = args.cloud or os.getenv("BIZASSIST_AUDIT_DATABASE_URL")
    if not cloud_url:
        sys.exit("\n  No cloud database given. Set BIZASSIST_AUDIT_DATABASE_URL "
                 "or pass --cloud.\n")
    if not is_postgres_target(cloud_url):
        out("  NOTE: --cloud is not a postgresql:// URL. Comparing two SQLite "
            "files is valid but is probably not what you meant.")
    if args.requeue and not args.backup_ack:
        sys.exit(
            "\n  REFUSING to --requeue without --i-have-a-restorable-backup.\n"
            "  This edits sync_queue on the LOCAL database. It touches no\n"
            "  business data and is far less dangerous than the row repair, but\n"
            "  it does cause rows to be re-pushed to the cloud.\n\n"
            "  Run it read-only first and read the list.\n")

    local = connect(local_path, readonly=not args.requeue)
    cloud = connect(cloud_url, readonly=True)
    out("=" * 78)
    out("LOCAL vs CLOUD RECONCILIATION   (matched on uid, businesses on BizID)")
    out(f"  local: {local.label}")
    out(f"  cloud: {cloud.label}")
    out(f"  mode : {'REQUEUE' if args.requeue else 'read-only'}   "
        f"cloud is ALWAYS read-only")
    out("=" * 78)

    findings = compare(local, cloud, args.biz)

    tot_acked = sum(len(f["acked"]) for f in findings)
    tot_never = sum(len(f["never"]) for f in findings)
    tot_queued = sum(len(f["queued"]) for f in findings)
    out("\n" + "-" * 78)
    if not findings:
        out("  Every compared row is present on the cloud.")
    else:
        out(f"  still queued (safe)      : {tot_queued}")
        out(f"  ACKED BUT ABSENT (lost)  : {tot_acked}")
        out(f"  NEVER QUEUED (lost)      : {tot_never}")
        out(f"  needing a requeue        : {tot_acked + tot_never}")
    out("-" * 78)

    if args.requeue and (tot_acked or tot_never):
        reopened, inserted = requeue(local, findings)
        local.commit()
        out(f"\n  REQUEUED: {reopened} outbox row(s) reopened, "
            f"{inserted} inserted.")
        out("  The sync worker will re-send them on its next cycle. A row whose")
        out("  PARENT is still missing will be DEFERRED and kept, not lost -")
        out("  that is the M-20 fix. Resolve the parent to let it land.")
    elif args.requeue:
        out("\n  Nothing to requeue.")

    local.close()
    cloud.close()
    return 1 if (tot_acked or tot_never) else 0


if __name__ == "__main__":
    raise SystemExit(main())
