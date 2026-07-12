#!/usr/bin/env python3
"""
cloud_cleanup_counters.py
=========================
Check (and optionally clean) leaked auto-generated cashier logins on the CLOUD
backend — the "c_XXXXXXXX" / "cash_XXXXXXXX" rows produced only by the test
suite. The cloud Postgres isn't reachable directly, so this talks to the cloud
over its own HTTP API using YOUR owner credentials:

    login  ->  GET /staff  ->  flag junk cashiers  ->  (optional) DELETE /staff/{id}

A "junk" cashier is defined conservatively: name matches ^(c|cash)_[0-9a-f]{8}$
AND it has no counter_prefix. Real counters (counter_1 with prefix "C1", etc.)
are never touched.

DEFAULT IS READ-ONLY. Pass --purge to delete, --yes to skip the prompt.

Usage:
    python scripts/cloud_cleanup_counters.py --username Varshini --password '****'
    python scripts/cloud_cleanup_counters.py --username Varshini --password '****' --purge
    # override the cloud URL if needed:
    python scripts/cloud_cleanup_counters.py ... --cloud-url https://your-space.hf.space
"""
import os
import re
import sys
import json
import argparse
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    sys.exit("This script needs httpx:  pip install httpx")

DEFAULT_CLOUD = (os.environ.get("CLOUD_API_URL")
                 or os.environ.get("VITE_API_URL")
                 or "https://rakshit-dev-bizassist.hf.space")

JUNK_RE = re.compile(r"^(c|cash)_[0-9a-f]{8}$")


def is_junk(staff: dict) -> bool:
    name = (staff.get("username") or "").strip()
    return bool(JUNK_RE.match(name)) and not (staff.get("counter_prefix") or "").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--username", required=True, help="Cloud OWNER username.")
    ap.add_argument("--password", required=True, help="Cloud owner password.")
    ap.add_argument("--cloud-url", default=DEFAULT_CLOUD)
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--report-json", metavar="PATH",
                    help="Write a JSON snapshot (before, and after if purging) to PATH.")
    args = ap.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cloud_url": None, "owner": args.username, "purged": bool(args.purge),
        "before": None, "after": None, "deleted": None, "delete_failures": [],
    }

    def _snapshot(staff, junk, real):
        return {
            "total": len(staff), "real_count": len(real), "junk_count": len(junk),
            "real": [{"id": s.get("id"), "username": s.get("username"),
                      "counter_prefix": s.get("counter_prefix")} for s in real],
            "junk": [{"id": s.get("id"), "username": s.get("username")} for s in junk],
        }

    def _write_report():
        if not args.report_json:
            return
        try:
            with open(args.report_json, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"Report written to {args.report_json}")
        except Exception as e:
            print(f"! could not write report: {e}")

    base = args.cloud_url.rstrip("/")
    report["cloud_url"] = base
    print(f"Cloud: {base}")

    with httpx.Client(timeout=15.0) as c:
        r = c.post(f"{base}/login", json={"username": args.username, "password": args.password})
        if r.status_code != 200:
            sys.exit(f"Login failed ({r.status_code}): {r.text[:200]}")
        token = r.json().get("token") or r.json().get("access_token")
        if not token:
            sys.exit("Login OK but no token in response.")
        h = {"Authorization": f"Bearer {token}"}

        r = c.get(f"{base}/staff", headers=h)
        if r.status_code != 200:
            sys.exit(f"GET /staff failed ({r.status_code}): {r.text[:200]}")
        staff = r.json()
        staff = staff if isinstance(staff, list) else staff.get("items", [])

        junk = [s for s in staff if is_junk(s)]
        real = [s for s in staff if not is_junk(s)]
        report["before"] = _snapshot(staff, junk, real)
        print(f"Total staff on cloud: {len(staff)}   real: {len(real)}   junk: {len(junk)}")
        print("Real (kept):", [(s.get("username"), s.get("counter_prefix")) for s in real])
        print("Junk (leaked):", [s.get("username") for s in junk])

        if not junk:
            print("\nNo leaked cashiers on the cloud. Nothing to do.")
            _write_report()
            return 0
        if not args.purge:
            print("\nREAD-ONLY. Re-run with --purge to delete the junk cashiers.")
            _write_report()
            return 0
        if not args.yes:
            if input(f"\nDelete {len(junk)} junk cashier(s) from the cloud? Type 'yes': ").strip().lower() != "yes":
                print("Aborted.")
                _write_report()
                return 1

        deleted = 0
        for s in junk:
            sid = s.get("id")
            dr = c.delete(f"{base}/staff/{sid}", headers=h)
            if dr.status_code in (200, 204):
                deleted += 1
            else:
                report["delete_failures"].append({"id": sid, "status": dr.status_code})
                print(f"  ! failed to delete id={sid} ({dr.status_code}): {dr.text[:120]}")
        report["deleted"] = deleted
        print(f"\nDeleted {deleted}/{len(junk)} junk cashier(s) from the cloud.")

        # Re-fetch for an after-snapshot so the report captures the resulting state.
        try:
            r = c.get(f"{base}/staff", headers=h)
            if r.status_code == 200:
                staff2 = r.json()
                staff2 = staff2 if isinstance(staff2, list) else staff2.get("items", [])
                junk2 = [s for s in staff2 if is_junk(s)]
                real2 = [s for s in staff2 if not is_junk(s)]
                report["after"] = _snapshot(staff2, junk2, real2)
                print(f"After: total={len(staff2)} real={len(real2)} junk={len(junk2)}")
        except Exception as e:
            print(f"! after-snapshot fetch failed: {e}")

        _write_report()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
