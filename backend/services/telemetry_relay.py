"""
services/telemetry_relay.py
===========================
Local → cloud telemetry export + retention (Admin Console plan follow-up).

Two scheduler jobs (wired in services/scheduler.py):

1. run_telemetry_relay — LOCAL installs only. Every few hours, ship any new
   lines from logs/telemetry.jsonl to the cloud backend's
   POST /api/telemetry/import, so field issues are visible in the Admin
   Console even when the desktop app never crashes "loudly". A byte-offset
   marker (logs/.telemetry_relay_offset) makes the export incremental and
   idempotent; on failure the offset is not advanced (retried next tick).

2. run_telemetry_retention — trims logs/telemetry.jsonl and every
   logs/businesses/<bizid>/telemetry.jsonl to the last
   TELEMETRY_RETENTION_DAYS days (default 7), so relayed logs are kept
   "for a few days" without growing forever. Runs everywhere (cloud + local).

Env:
  TELEMETRY_RELAY=0            — disable the relay job (default on for local)
  BIZASSIST_CLOUD_URL          — relay target (default: the HF Space)
  TELEMETRY_RETENTION_DAYS=7   — retention window
No new dependencies — stdlib urllib only (PyInstaller-friendly).
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("bizassist.telemetry_relay")

CLOUD_URL = os.getenv("BIZASSIST_CLOUD_URL", "https://rakshit-dev-bizassist.hf.space")
_OFFSET_FILE = Path("logs") / ".telemetry_relay_offset"
_TELEMETRY_FILE = Path("logs") / "telemetry.jsonl"
_BUSINESS_DIR = Path("logs") / "businesses"
_BATCH = 400   # records per POST (endpoint cap is 500)


def _is_local_backend() -> bool:
    """The relay only makes sense on local installs — the cloud IS the target."""
    db_url = os.getenv("DATABASE_URL", "")
    return "postgres" not in db_url and "postgresql" not in db_url


def _relay_enabled() -> bool:
    return os.getenv("TELEMETRY_RELAY", "1") != "0" and _is_local_backend()


def _read_offset() -> int:
    try:
        return int(_OFFSET_FILE.read_text().strip() or 0)
    except Exception:
        return 0


def _write_offset(offset: int):
    try:
        _OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OFFSET_FILE.write_text(str(offset))
    except Exception as e:
        logger.warning(f"[RELAY] Could not persist offset: {e}")


def _device_marker() -> str:
    """Best-effort identity of this install for the relay stamp."""
    try:
        import platform
        return f"local-{platform.node()[:32]}"
    except Exception:
        return "local-unknown"


def _post_import(records: list) -> bool:
    body = json.dumps({"records": records, "relay_device": _device_marker()}).encode()
    req = urllib.request.Request(
        f"{CLOUD_URL}/api/telemetry/import",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return 200 <= res.status < 300
    except Exception as e:
        logger.warning(f"[RELAY] Cloud unreachable ({e.__class__.__name__}) — will retry next tick")
        return False


def run_telemetry_relay():
    """Incrementally ship new local telemetry lines to the cloud."""
    if not _relay_enabled():
        return
    if not _TELEMETRY_FILE.exists():
        return

    size = _TELEMETRY_FILE.stat().st_size
    offset = _read_offset()
    if offset > size:
        offset = 0   # file was rotated/trimmed — start over
    if offset >= size:
        return       # nothing new

    try:
        with _TELEMETRY_FILE.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            chunk = f.read()
            new_offset = f.tell()
    except Exception as e:
        logger.warning(f"[RELAY] Read failed: {e}")
        return

    # Only ship complete lines; leave a trailing partial line for next tick.
    if not chunk.endswith("\n"):
        last_nl = chunk.rfind("\n")
        if last_nl < 0:
            return
        new_offset = offset + len(chunk[:last_nl + 1].encode("utf-8"))
        chunk = chunk[:last_nl + 1]

    records = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("relayed_at"):
            continue   # never re-relay an imported record (loop guard)
        records.append(rec)

    if not records:
        _write_offset(new_offset)
        return

    shipped = 0
    for i in range(0, len(records), _BATCH):
        if not _post_import(records[i:i + _BATCH]):
            # Partial failure: advance the offset only past what was shipped.
            return
        shipped += len(records[i:i + _BATCH])

    _write_offset(new_offset)
    logger.info(f"[RELAY] Shipped {shipped} telemetry records to cloud")


def _trim_jsonl(path: Path, cutoff_iso: str) -> int:
    """Rewrite a JSONL file keeping records newer than the cutoff. Returns dropped count."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return 0
    keep, dropped = [], 0
    for line in lines:
        try:
            ts = json.loads(line).get("received_at") or ""
        except Exception:
            ts = ""
        if ts >= cutoff_iso:
            keep.append(line)
        else:
            dropped += 1
    if dropped:
        try:
            tmp = path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                f.writelines(keep)
            tmp.replace(path)
        except Exception as e:
            logger.warning(f"[RELAY] Trim failed for {path}: {e}")
            return 0
    return dropped


def run_telemetry_retention():
    """Keep telemetry logs to the last TELEMETRY_RETENTION_DAYS days."""
    try:
        days = int(os.getenv("TELEMETRY_RETENTION_DAYS", "7"))
    except ValueError:
        days = 7
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    dropped = 0
    if _TELEMETRY_FILE.exists():
        dropped_main = _trim_jsonl(_TELEMETRY_FILE, cutoff)
        dropped += dropped_main
        if dropped_main:
            # Byte offsets are invalid after a rewrite. The relay runs far more
            # often than retention, so everything still in the file has already
            # been shipped — point the marker at EOF instead of re-relaying.
            try:
                _write_offset(_TELEMETRY_FILE.stat().st_size)
            except OSError:
                _write_offset(0)
    if _BUSINESS_DIR.is_dir():
        for sub in _BUSINESS_DIR.iterdir():
            f = sub / "telemetry.jsonl"
            if f.is_file():
                dropped += _trim_jsonl(f, cutoff)

    if dropped:
        logger.info(f"[RELAY] Retention trim: dropped {dropped} records older than {days}d")
