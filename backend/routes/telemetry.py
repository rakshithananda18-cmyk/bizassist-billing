"""
routes/telemetry.py
===================
Testing-phase telemetry sink. The desktop shell (and optionally the frontend)
POSTs small event batches here — to the LOCAL backend (lands in the local log
file) and to the CLOUD backend (lands in the HF Space console + logs/ dir),
so installs in the field can be debugged without asking users for files.

No database writes → no alembic migration → nothing to apply on Supabase.

Batches may carry an optional `bizid` (the business's stable public_id — the
cross-DB identity spine). When present, events are ALSO mirrored to a
per-business folder (logs/businesses/<bizid>/telemetry.jsonl) so one
business's diagnostics can be pulled without grepping the global stream.

Disable anytime with env TELEMETRY_ENABLED=0 (e.g. after the testing phase).
"""

import json
import logging
import os
import re
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
    bizid: Optional[str] = Field(None, max_length=64)   # business public_id (stable across cloud/local)
    events: List[TelemetryEvent]


def _jsonl_path() -> Path:
    """logs/telemetry.jsonl next to the CWD (desktop: user data dir; dev: backend/)."""
    p = Path("logs")
    p.mkdir(parents=True, exist_ok=True)
    return p / "telemetry.jsonl"


def _safe_bizid(bizid: str) -> Optional[str]:
    """Sanitize the client-supplied bizid before it becomes a folder name."""
    token = re.sub(r"[^A-Za-z0-9_\-]", "", (bizid or ""))[:64]
    return token or None


def _business_jsonl_path(bizid: str) -> Path:
    """Per-business mirror: logs/businesses/<bizid>/telemetry.jsonl."""
    p = Path("logs") / "businesses" / bizid
    p.mkdir(parents=True, exist_ok=True)
    return p / "telemetry.jsonl"


def _persist_records_to_db(records: List[Dict[str, Any]]) -> int:
    """
    Durable copy → telemetry_events table (Supabase Postgres on the cloud;
    SQLite locally). The JSONL files above are EPHEMERAL on the HF Space, so
    the DB is what the Admin Console actually reads. Best-effort: telemetry
    must never break the app, so all failures are swallowed (logged once).
    """
    if not records:
        return 0
    try:
        from database.db import SessionLocal
        from core.models import TelemetryEvent

        def _parse_dt(value):
            if not value:
                return datetime.utcnow()
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return datetime.utcnow()

        db = SessionLocal()
        try:
            for rec in records:
                payload = rec.get("payload")
                if payload is not None and not isinstance(payload, str):
                    try:
                        payload = json.dumps(payload, default=str)[:_MAX_PAYLOAD_CHARS]
                    except Exception:
                        payload = str(payload)[:_MAX_PAYLOAD_CHARS]
                db.add(TelemetryEvent(
                    received_at=_parse_dt(rec.get("received_at")),
                    at=(str(rec.get("at"))[:64] if rec.get("at") else None),
                    source=(rec.get("source") or "unknown")[:40],
                    device_id=(rec.get("device_id") or "unknown")[:64],
                    app_version=(rec.get("app_version") or None),
                    platform=(rec.get("platform") or None),
                    bizid=rec.get("bizid"),
                    level=(rec.get("level") or "info")[:10],
                    event=(rec.get("event") or "unknown")[:80],
                    payload=payload,
                    relay_device=rec.get("relay_device"),
                    relayed_at=(str(rec.get("relayed_at"))[:64] if rec.get("relayed_at") else None),
                ))
            db.commit()
            return len(records)
        finally:
            db.close()
    except Exception as e:
        logger.warning("[TELEMETRY] DB persist skipped (%s) — JSONL/console copy still made", e)
        return 0


@router.post("/api/telemetry/log")
def ingest_telemetry(batch: TelemetryBatch):
    """
    Unauthenticated by design: boot failures happen BEFORE login, and events
    carry no business data — only app/install diagnostics. Batch size is capped.
    The optional bizid is advisory (diagnostics grouping only) — it grants
    nothing and is sanitized before touching the filesystem.
    """
    if not TELEMETRY_ENABLED:
        return {"status": "disabled"}

    received_at = datetime.now(timezone.utc).isoformat()
    events = batch.events[:_MAX_EVENTS_PER_BATCH]
    bizid = _safe_bizid(batch.bizid) if batch.bizid else None
    db_records = []

    for ev in events:
        payload_str = ""
        if ev.payload is not None:
            try:
                payload_str = json.dumps(ev.payload, default=str)[:_MAX_PAYLOAD_CHARS]
            except Exception:
                payload_str = str(ev.payload)[:_MAX_PAYLOAD_CHARS]

        line = (
            f"[TELEMETRY][CLIENT:{ev.level}] {batch.source} v{batch.app_version or '?'} "
            f"({batch.platform or '?'}, device {batch.device_id[:12]}"
            f"{', biz ' + bizid if bizid else ''}) "
            f"{ev.event}: {payload_str}"
        )
        # A CLIENT-reported error (expired token, flaky network, SSE drop) is a
        # client condition, NOT a backend fault — it must not masquerade as a
        # server ERROR and trip error dashboards/alerts. Mirror it to the server
        # log at a CAPPED, clearly client-attributed level (client error → WARN,
        # client warn → INFO). The original client level is preserved verbatim in
        # the persisted telemetry record and in the [CLIENT:<level>] tag above.
        log_fn = {"error": logger.warning, "warn": logger.info}.get(ev.level, logger.info)
        log_fn(line)

        # Clean record: only meaningful fields, no None-padding.
        record = {
            "received_at": received_at,
            "source": batch.source,
            "device_id": batch.device_id,
            "level": ev.level,
            "event": ev.event,
        }
        if ev.at:              record["at"] = ev.at
        if batch.app_version:  record["app_version"] = batch.app_version
        if batch.platform:     record["platform"] = batch.platform
        if bizid:              record["bizid"] = bizid
        if ev.payload:         record["payload"] = ev.payload
        db_records.append(record)

        # Append JSONL for grep-able post-mortems (best-effort) — global stream
        # plus the per-business mirror when the batch carries a bizid.
        try:
            data = json.dumps(record, default=str) + "\n"
            with _jsonl_path().open("a", encoding="utf-8") as f:
                f.write(data)
            if bizid:
                with _business_jsonl_path(bizid).open("a", encoding="utf-8") as f:
                    f.write(data)
        except Exception:
            pass  # read-only FS (HF) — logger output above still lands

    # Durable copy (survives HF Space restarts) — best-effort.
    _persist_records_to_db(db_records)

    return {"status": "ok", "accepted": len(events)}


class TelemetryImport(BaseModel):
    """Relay payload: raw JSONL records exported from a LOCAL backend's
    logs/telemetry.jsonl by the telemetry-relay scheduler job."""
    records: List[Dict[str, Any]] = Field(..., max_length=500)
    relay_device: Optional[str] = Field(None, max_length=64)   # which install relayed


_MAX_IMPORT_RECORDS = 500


@router.post("/api/telemetry/import")
def import_telemetry(body: TelemetryImport):
    """
    Bulk-import relayed records (local install → cloud). Same trust model as
    /api/telemetry/log (unauthenticated, capped, diagnostics only). Records are
    stamped `relayed_at` and mirrored into per-business folders by bizid.
    """
    if not TELEMETRY_ENABLED:
        return {"status": "disabled"}

    relayed_at = datetime.now(timezone.utc).isoformat()
    accepted = 0
    db_records = []
    for rec in body.records[:_MAX_IMPORT_RECORDS]:
        if not isinstance(rec, dict) or not rec.get("event") or not rec.get("device_id"):
            continue                              # skip malformed lines silently
        rec = dict(rec)
        rec["relayed_at"] = relayed_at
        if body.relay_device:
            rec["relay_device"] = body.relay_device
        bizid = _safe_bizid(rec.get("bizid")) if rec.get("bizid") else None
        if bizid:
            rec["bizid"] = bizid
        else:
            rec.pop("bizid", None)
        db_records.append(rec)
        try:
            data = json.dumps(rec, default=str)[:_MAX_PAYLOAD_CHARS * 2] + "\n"
            with _jsonl_path().open("a", encoding="utf-8") as f:
                f.write(data)
            if bizid:
                with _business_jsonl_path(bizid).open("a", encoding="utf-8") as f:
                    f.write(data)
            accepted += 1
        except Exception:
            pass  # read-only FS — nothing to do

    # Durable copy (survives HF Space restarts) — best-effort. Counts as
    # accepted even when the FS copy failed (read-only container FS).
    persisted = _persist_records_to_db(db_records)
    accepted = max(accepted, persisted)

    logger.info(f"[TELEMETRY] Imported {accepted} relayed records"
                f"{' from ' + body.relay_device if body.relay_device else ''}")
    return {"status": "ok", "accepted": accepted}
