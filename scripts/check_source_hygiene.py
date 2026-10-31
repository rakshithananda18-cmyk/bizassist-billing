"""Fail when private operational exports are included in versioned source.

Only paths are inspected or printed; financial contents never enter CI logs.
"""
from pathlib import PurePosixPath
import re
import subprocess
import sys

FORBIDDEN = re.compile(r"^(?:voided_payment_|fk_orphans_export_|quarantined_payments_|phantom_line_items_export_).+\.json$", re.I)


def prohibited(path):
    name = PurePosixPath(path).name
    return bool(FORBIDDEN.match(name) or name.endswith((".db", ".sqlite", ".sqlite3", ".dump", ".p12", ".pfx", ".pem"))
                or name in {".env", ".env.local", ".env.production"}
                or path.startswith((".private/", "scratch/repair-evidence/", "logs/"))
                or re.search(r"\.log(?:\.[0-9]+)?$", name))


def main():
    files = subprocess.check_output(["git", "-c", "core.fsmonitor=false", "ls-files", "-z"]).decode("utf-8").split("\0")
    bad = sorted(p for p in files if p and prohibited(p))
    if bad:
        print("Private operational files are tracked; preserve evidence privately and remove from source:")
        print("\n".join(bad))
        return 1
    print("Source hygiene: no tracked private operational exports or database files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
