"""
routes/telemetry.py
===================
Testing-phase telemetry sink. The desktop shell (and optionally the frontend)
POSTs small event batches here — to the LOCAL backend (lands in the local log
file) and to the CLOUD backend (lands in the HF Space console + logs/ dir),
so installs in the field can be debugged without asking users for files.

No database writes → no alembic migration → nothing to apply on Supabase.

Disable anytime with env TELEMETRY_ENABLED=0 (e.g. after the testing phase).
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger("bizassist.telemetry")

TELEMETRY_ENABLED = os.getenv("TELEMETRY_ENABLED", "1") != "0"
_MAX_EVENTS_PER_BATCH = 50
_MAX_PAYLOAD_CHARS = 4000  # keep log lines sane


class TelemetryEvent(BaseModel):
    event: str = Field(..., max_length=80)          # e.g. "boot_ok", "backend_start_failed"
    level: str = Field("info", max_length=10)       # info | warn | error
    payload: Optional[Dict[str, Any]] = None        # free-form context
    at: Optional[str] = None                        # client ISO timestamp


class TelemetryBatch(BaseModel):
    source: str = Field(..., max_length=40)         # "desktop-shell" | "frontend" | ...
    device_id: str = Field(..., max_length=64)      # anonymous install id
    app_version: Optional[str] = Field(None, max_length=20)
    platform: Optional[str] = Field(None, max_length=20)
    events: List[TelemetryEvent]


def _jsonl_path() -> Path:
    """logs/telemetry.jsonl next to the CWD (desktop: user data dir; dev: backend/)."""
    p = Path("logs")
    p.mkdir(parents=True, exist_ok=True)
    return p / "telemetry.jsonl"


@router.post("/api/telemetry/log")
def ingest_telemetry(batch: TelemetryBatch):
    """
    Unauthenticated by design: boot failures happen BEFORE login, and events
    carry no business data — only app/install diagnostics. Batch size is capped.
    """
    if not TELEMETRY_ENABLED:
        return {"status": "disabled"}

    received_at = datetime.now(timezone.utc).isoformat()
    events = batch.events[:_MAX_EVENTS_PER_BATCH]

    for ev in events:
        payload_str = ""
        if ev.payload is not None:
            try:
                payload_str = json.dumps(ev.payload, default=str)[:_MAX_PAYLOAD_CHARS]
            except Exception:
                payload_str = str(ev.payload)[:_MAX_PAYLOAD_CHARS]

        line = (
            f"[TELEMETRY] {batch.source} v{batch.app_version or '?'} "
            f"({batch.platform or '?'}, device {batch.device_id[:12]}) "
            f"{ev.event}: {payload_str}"
        )
        log_fn = {"error": logger.error, "warn": logger.warning}.get(ev.level, logger.info)
        log_fn(line)

        # Also append JSONL for grep-able post-mortems (best-effort).
        try:
            with _jsonl_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "received_at": received_at,
                    "at": ev.at,
                    "source": batch.source,
                    "device_id": batch.device_id,
                    "app_version": batch.app_version,
                    "platform": batch.platform,
                    "level": ev.level,
                    "event": ev.event,
                    "payload": ev.payload,
                }, default=str) + "\n")
        except Exception:
            pass  # read-only FS (HF) — logger output above still lands

    return {"status": "ok", "accepted": len(events)}
