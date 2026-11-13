"""Reject billing/backend/desktop release drift before building or publishing.

backend/release.json identifies the shipped code. Installer availability is
separate: download links may target the latest published release instead.
"""
import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def read_metadata(root, relative):
    try:
        return json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read release metadata: {relative}") from exc


def check_versions(root=ROOT, expected=None):
    """Return the canonical version and actionable errors, without changing files."""
    root = Path(root)
    try:
        version = read_metadata(root, "backend/release.json").get("version")
    except (ValueError, AttributeError):
        return None, ["Cannot read release version from backend/release.json"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        return None, ["backend/release.json must contain a valid release version"]

    errors = []
    if expected is not None and expected.removeprefix("v") != version:
        errors.append(f"Release tag must match backend/release.json ({version})")

    for directory in ("frontend-billing", "desktop"):
        for filename in ("package.json", "package-lock.json"):
            relative = f"{directory}/{filename}"
            try:
                data = read_metadata(root, relative)
                if data.get("version") != version:
                    errors.append(f"{relative}: version must be {version}")
                if filename == "package-lock.json" and data.get("packages", {}).get("", {}).get("version") != version:
                    errors.append(f"{relative}: packages[''].version must be {version}")
            except (ValueError, AttributeError):
                errors.append(f"Cannot read release metadata: {relative}")
    return version, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", help="Release tag, e.g. v1.2.7; it must match all packaged versions")
    args = parser.parse_args(argv)
    version, errors = check_versions(expected=args.expected)
    if errors:
        print("Release version validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Release versions aligned: {version} (backend, billing UI, desktop and lockfiles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
