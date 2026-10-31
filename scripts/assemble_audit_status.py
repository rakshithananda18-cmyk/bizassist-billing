"""Assemble the original forty findings without replacing historical evidence."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/audit/2026-10-31"
OUT = REPORT / "implementation"


def main():
    with (ROOT / "docs/audit/2026-10-30/issues.csv").open(encoding="utf-8", newline="") as stream:
        original = list(csv.DictReader(stream))
    updates = {}
    for name in ("backend-domain", "trust-sync", "web-apps", "root"):
        for row in json.loads((OUT / f"{name}-status.json").read_text(encoding="utf-8")):
            if row["id"] in updates:
                raise ValueError("Duplicate original issue: " + row["id"])
            updates[row["id"]] = {**row, "status_source": f"{name}-status.json"}
    if len(original) != 40 or set(updates) != {row["id"] for row in original}:
        raise ValueError("The ledger must cover exactly the original forty IDs")
    ledger = []
    for issue in original:
        row = updates[issue["id"]]
        status = "implemented" if row["status"] == "fixed" else row["status"]
        if status not in {"implemented", "contained"}:
            raise ValueError("Unexpected implementation status: " + status)
        remaining = row.get("remaining", [])
        if isinstance(remaining, str):
            remaining = [remaining] if remaining else []
        ledger.append({
            "id": issue["id"], "original_date": issue["date"], "review_date": "2026-10-31",
            "priority": issue["priority"], "title": issue["title"], "status": status,
            "evidence": row["evidence"], "remaining": remaining,
            "original_report": issue["report"], "status_source": row["status_source"],
        })
    counts = dict(Counter(row["status"] for row in ledger))
    (OUT / "issues.json").write_text(json.dumps({
        "date": "2026-10-31", "timezone": "Asia/Calcutta", "counts": counts,
        "scope": "Original 40 findings; implementation status, not deployment or historical data repair",
        "issues": ledger,
    }, indent=2) + "\n", encoding="utf-8")
    with (OUT / "issues.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "id", "original_date", "review_date", "priority", "title", "status",
            "evidence", "remaining", "original_report", "status_source",
        ])
        writer.writeheader()
        for row in ledger:
            writer.writerow({**row, "evidence": " | ".join(row["evidence"]),
                             "remaining": " | ".join(row["remaining"])})
    lines = [
        "# Original 40 findings — implementation ledger, 31 October 2026", "",
        f"**{counts.get('implemented', 0)} implemented; {counts.get('contained', 0)} safely contained.**",
        "The two contained workflows are unavailable; they are not completed features.",
        "These counts describe code behavior. External credential rotation, deployment",
        "configuration, existing financial discrepancies and device acceptance remain separate.", "",
        "| ID | Priority | Status | Original finding |", "| --- | --- | --- | --- |",
    ]
    lines += [f"| {row['id']} | {row['priority']} | {row['status']} | {row['title'].replace('|', '/')} |" for row in ledger]
    lines += ["", "## Evidence and limitations", "",
              "[Machine-readable ledger](issues.json) preserves the implementation evidence",
              "and remaining limits for every ID. [CSV copy](issues.csv) has identical rows.", "",
              "Domain, trust, web and root results are recorded separately; overlapping",
              "test runs must not be added together as a unique-test count.", "",
              "- [Backend domain](backend-domain.md)", "- [Trust, sync and operations](trust-sync-ops.md)",
              "- [Latest Field changes: keep with corrections](web-latest-changes.md)",
              "- [Root acceptance results](root-results.json)",
              "- [New pasted-log findings](../LOG-REVIEW.md)",
              "- [External credential response](../SECURITY-RESPONSE.md)",
              "- [Execution and release plan](../PLAN.md)", ""]
    (OUT / "STATUS.md").write_text("\n".join(lines), encoding="utf-8")

    paths = subprocess.check_output([
        "git", "-c", "core.fsmonitor=false", "ls-files", "--cached", "--others", "--exclude-standard", "-z",
    ], cwd=ROOT).decode("utf-8").split("\0")
    manifest = {}
    for path in sorted(set(paths)):
        # Exclude this generated report tree so final acceptance text can be
        # updated without recursively changing its own source fingerprint.
        if not path or path.startswith("docs/audit/2026-10-31/"):
            continue
        file = ROOT / path
        if file.is_file():
            manifest[path] = hashlib.sha256(file.read_bytes()).hexdigest()
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (OUT / "source-manifest.json").write_text(json.dumps({
        "date": "2026-10-31", "head": head, "includes_uncommitted_work": True,
        "excludes": ["ignored/private files", "docs/audit/2026-10-31/"],
        "file_count": len(manifest), "sha256": hashlib.sha256(canonical).hexdigest(),
        # Separate path and digest fields: a filename containing "auth" or
        # "token" is not an API-key name, and its SHA256 is not a credential.
        "files": [{"path": path, "sha256": digest} for path, digest in manifest.items()],
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Original findings: {len(ledger)}; statuses: {counts}; source files fingerprinted: {len(manifest)}")


if __name__ == "__main__":
    main()
