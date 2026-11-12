"""Identify the code shipped in both the container and frozen desktop backend."""
import json
import logging
import os
from pathlib import Path
import re

_VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
_MANIFEST = Path(__file__).resolve().parent.parent / "release.json"


def release_version(manifest=_MANIFEST):
    """Use packaged metadata; stale APP_VERSION settings cannot mislabel code."""
    try:
        version = json.loads(Path(manifest).read_text(encoding="utf-8"))["version"]
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise ValueError("Invalid release version")
    except (OSError, ValueError, TypeError, KeyError):
        return "unknown"
    configured = os.environ.get("APP_VERSION", "").strip()
    if configured and configured != version:
        logging.getLogger("bizassist.release").warning(
            "APP_VERSION differs from the packaged release; reporting the packaged code version")
    return version


APP_VERSION = release_version()
