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
from typing import Any, Dict, List, Optional, Type, TypeVar

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from services.auth import get_active_user
from services.dates import utc_now

router = APIRouter()
logger = logging.getLogger("bizassist.telemetry")

TELEMETRY_ENABLED = os.getenv("TELEMETRY_ENABLED", "1") != "0"
_MAX_EVENTS_PER_BATCH = 50
_MAX_PAYLOAD_CHARS = 4000  # keep log lines sane
_MAX_LOG_REQUEST_BYTES = 256 * 1024
_MAX_IMPORT_REQUEST_BYTES = 2 * 1024 * 1024


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
    events: List[TelemetryEvent] = Field(..., min_length=1, max_length=_MAX_EVENTS_PER_BATCH)


TModel = TypeVar("TModel", bound=BaseModel)


def _is_cloud_backend() -> bool:
    """The shared Postgres deployment must not accept anonymous writes."""
    from database.db import engine
    return engine.dialect.name == "postgresql"


def _bound_cloud_bizid(authorization: Optional[str]) -> Optional[str]:
    """Authenticate cloud telemetry and derive its tenant from the JWT."""
    if not _is_cloud_backend():
        return None
    current_user = get_active_user(authorization=authorization)
    bizid = _safe_bizid(current_user.get("public_id"))
    if not bizid:
        raise HTTPException(status_code=403, detail="Authenticated telemetry requires a business identity.")
    return bizid


async def _parse_bounded_json(request: Request, model: Type[TModel], maximum: int) -> TModel:
    """Enforce a byte ceiling while reading, before JSON/Pydantic processing."""
    declared = request.headers.get("content-length")
    try:
        if declared and int(declared) > maximum:
            raise HTTPException(status_code=413, detail="Telemetry request exceeds the allowed size.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")

    chunks: List[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > maximum:
            raise HTTPException(status_code=413, detail="Telemetry request exceeds the allowed size.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        if hasattr(model, "model_validate_json"):
            return model.model_validate_json(raw)  # Pydantic v2
        return model.parse_raw(raw)                # Pydantic v1
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid telemetry payload.") from exc


def _payload_text(payload: object) -> Optional[str]:
    """Serialize once, preventing free-form nested values from reaching storage."""
    if payload is None:
        return None
    try:
        return json.dumps(payload, default=str, ensure_ascii=False)[:_MAX_PAYLOAD_CHARS]
    except Exception:
        return str(payload)[:_MAX_PAYLOAD_CHARS]


def _request_bizid(claimed: object, bound: Optional[str]) -> Optional[str]:
    supplied = _safe_bizid(claimed)
    if bound:
        if supplied and supplied != bound:
            raise HTTPException(status_code=403, detail="Telemetry BizID does not match the authenticated business.")
        return bound
    return supplied


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
                return utc_now()
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return utc_now()

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
async def ingest_telemetry(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Record a bounded telemetry batch; cloud persistence requires a JWT."""
    if not TELEMETRY_ENABLED:
        return {"status": "disabled"}

    bound_bizid = _bound_cloud_bizid(authorization)
    batch = await _parse_bounded_json(request, TelemetryBatch, _MAX_LOG_REQUEST_BYTES)
    bizid = _request_bizid(batch.bizid, bound_bizid)
    received_at = datetime.now(timezone.utc).isoformat()
    db_records = []

    for ev in batch.events:
        payload_str = _payload_text(ev.payload)
        record = {
            "received_at": received_at,
            "source": batch.source,
            "device_id": batch.device_id,
            "level": ev.level,
            "event": ev.event,
        }
        if ev.at:
            record["at"] = ev.at
        if batch.app_version:
            record["app_version"] = batch.app_version
        if batch.platform:
            record["platform"] = batch.platform
        if bizid:
            record["bizid"] = bizid
        if payload_str:
            record["payload"] = payload_str
        # Client-reported errors should not masquerade as server failures.
        log_fn = {"error": logger.warning, "warn": logger.info}.get(ev.level, logger.info)
        log_fn("[TELEMETRY][CLIENT:%s] %s: %s", ev.level, ev.event, payload_str or "")
        db_records.append(record)
        try:
            data = json.dumps(record, default=str, ensure_ascii=False) + "\n"
            with _jsonl_path().open("a", encoding="utf-8") as f:
                f.write(data)
            if bizid:
                with _business_jsonl_path(bizid).open("a", encoding="utf-8") as f:
                    f.write(data)
        except Exception:
            pass  # read-only FS (HF) — DB persistence below remains best-effort

    _persist_records_to_db(db_records)
    return {"status": "ok", "accepted": len(db_records)}


class TelemetryImport(BaseModel):
    """Relay payload: raw JSONL records exported from a LOCAL backend's
    logs/telemetry.jsonl by the telemetry-relay scheduler job."""
    records: List[Dict[str, Any]] = Field(..., max_length=500)
    relay_device: Optional[str] = Field(None, max_length=64)   # which install relayed


_MAX_IMPORT_RECORDS = 500


@router.post("/api/telemetry/import")
async def import_telemetry(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Import local telemetry, binding all cloud records to the bearer BizID."""
    if not TELEMETRY_ENABLED:
        return {"status": "disabled"}

    bound_bizid = _bound_cloud_bizid(authorization)
    body = await _parse_bounded_json(request, TelemetryImport, _MAX_IMPORT_REQUEST_BYTES)
    relayed_at = datetime.now(timezone.utc).isoformat()
    accepted = 0
    db_records = []
    for incoming in body.records:
        if not isinstance(incoming, dict) or not incoming.get("event") or not incoming.get("device_id"):
            continue
        bizid = _request_bizid(incoming.get("bizid"), bound_bizid)
        rec = {
            "received_at": incoming.get("received_at") or relayed_at,
            "source": str(incoming.get("source") or "unknown")[:40],
            "device_id": str(incoming.get("device_id") or "unknown")[:64],
            "level": str(incoming.get("level") or "info")[:10],
            "event": str(incoming.get("event") or "unknown")[:80],
            "relayed_at": relayed_at,
        }
        if incoming.get("at"):
            rec["at"] = str(incoming["at"])[:64]
        if incoming.get("app_version"):
            rec["app_version"] = str(incoming["app_version"])[:20]
        if incoming.get("platform"):
            rec["platform"] = str(incoming["platform"])[:20]
        payload = _payload_text(incoming.get("payload"))
        if payload:
            rec["payload"] = payload
        if body.relay_device:
            rec["relay_device"] = body.relay_device
        if bizid:
            rec["bizid"] = bizid
        db_records.append(rec)
        try:
            data = json.dumps(rec, default=str, ensure_ascii=False) + "\n"
            with _jsonl_path().open("a", encoding="utf-8") as f:
                f.write(data)
            if bizid:
                with _business_jsonl_path(bizid).open("a", encoding="utf-8") as f:
                    f.write(data)
            accepted += 1
        except Exception:
            pass

    persisted = _persist_records_to_db(db_records)
    accepted = max(accepted, persisted)
    logger.info("[TELEMETRY] Imported %s relayed records", accepted)
    return {"status": "ok", "accepted": accepted}
