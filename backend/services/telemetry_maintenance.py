"""
services/telemetry_maintenance.py
=================================
Retention + archival for the PERSISTENT telemetry store (telemetry_events
table — Supabase Postgres on the cloud, SQLite locally).

Why: the JSONL files under logs/ are ephemeral on the HF Space (container FS
is wiped on every restart/redeploy). The table is durable, but must not grow
unbounded on Supabase. Two mechanisms keep it in check:

1. run_telemetry_db_maintenance  (scheduler: weekly)
   • purges rows older than TELEMETRY_DB_RETENTION_DAYS (default 30)
   • size guard: if the table still exceeds TELEMETRY_MAX_MB (default 200),
     force-trims the OLDEST rows down to ~80% of the cap and logs loudly —
     the admin should have downloaded an archive before this point.

2. build_archive / purge_archived  (GET /admin/telemetry/archive?purge=1)
   • streams every row as gzip-compressed JSONL (telemetry-<ts>.jsonl.gz)
     for download to the admin's machine, then (optionally) deletes exactly
     the rows that were archived (max-id watermark — new rows are safe).

Env:
  TELEMETRY_DB_RETENTION_DAYS=30   weekly purge window
  TELEMETRY_MAX_MB=200             size cap that triggers the force-trim
"""

import gzip
import io
import json
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger("bizassist.telemetry_maintenance")

RETENTION_DAYS = int(os.getenv("TELEMETRY_DB_RETENTION_DAYS", "30"))
MAX_MB = int(os.getenv("TELEMETRY_MAX_MB", "200"))


# ── Size measurement ──────────────────────────────────────────────────────────

def table_size_bytes(db) -> int:
    """Best-effort physical size of telemetry_events (exact on Postgres)."""
    from sqlalchemy import text
    try:
        if db.bind.dialect.name == "postgresql":
            row = db.execute(text("SELECT pg_total_relation_size('telemetry_events')")).scalar()
            return int(row or 0)
        # SQLite: estimate — average row footprint × row count.
        row = db.execute(text(
            "SELECT COUNT(*), COALESCE(AVG(LENGTH(COALESCE(payload,'')) + 160), 200) "
            "FROM telemetry_events"
        )).first()
        return int((row[0] or 0) * (row[1] or 200))
    except Exception as e:
        logger.warning("[TELEMETRY-MAINT] size check failed: %s", e)
        return 0


def stats(db) -> dict:
    """Row count, bounds, and size for the Admin Console health panel."""
    from core.models import TelemetryEvent
    from sqlalchemy import func
    total = db.query(func.count(TelemetryEvent.id)).scalar() or 0
    oldest = db.query(func.min(TelemetryEvent.received_at)).scalar()
    newest = db.query(func.max(TelemetryEvent.received_at)).scalar()
    size = table_size_bytes(db)
    return {
        "rows": int(total),
        "oldest": oldest.isoformat() if oldest else None,
        "newest": newest.isoformat() if newest else None,
        "size_bytes": size,
        "size_mb": round(size / (1024 * 1024), 2),
        "max_mb": MAX_MB,
        "retention_days": RETENTION_DAYS,
        "over_cap": size > MAX_MB * 1024 * 1024,
    }


# ── Archive (download) + purge ───────────────────────────────────────────────

def build_archive(db, batch: int = 5000):
    """
    Dump ALL telemetry rows as gzip JSONL. Returns (bytes, filename, max_id).
    max_id is the purge watermark — rows ingested during the download survive.
    """
    from core.models import TelemetryEvent

    buf = io.BytesIO()
    max_id = 0
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    with gzip.GzipFile(fileobj=buf, mode="wb", filename=f"telemetry-{stamp}.jsonl") as gz:
        last_id = 0
        while True:
            rows = (db.query(TelemetryEvent)
                      .filter(TelemetryEvent.id > last_id)
                      .order_by(TelemetryEvent.id.asc())
                      .limit(batch).all())
            if not rows:
                break
            for r in rows:
                rec = {
                    "id": r.id,
                    "received_at": r.received_at.isoformat() if r.received_at else None,
                    "at": r.at, "source": r.source, "device_id": r.device_id,
                    "app_version": r.app_version, "platform": r.platform,
                    "bizid": r.bizid, "level": r.level, "event": r.event,
                    "relay_device": r.relay_device, "relayed_at": r.relayed_at,
                }
                if r.payload:
                    try:
                        rec["payload"] = json.loads(r.payload)
                    except Exception:
                        rec["payload"] = r.payload
                gz.write((json.dumps(rec, default=str) + "\n").encode("utf-8"))
                last_id = r.id
            max_id = last_id
    return buf.getvalue(), f"telemetry-archive-{stamp}.jsonl.gz", max_id


def purge_archived(db, max_id: int) -> int:
    """Delete rows with id <= max_id (i.e. exactly what the archive contains)."""
    from core.models import TelemetryEvent
    if not max_id:
        return 0
    n = (db.query(TelemetryEvent)
           .filter(TelemetryEvent.id <= max_id)
           .delete(synchronize_session=False))
    db.commit()
    logger.info("[TELEMETRY-MAINT] purged %s archived rows (id <= %s)", n, max_id)
    return n


# ── Optional object-storage archive (hands-off) ──────────────────────────────
# When the size guard trips, we can push the gzip archive to S3-compatible
# object storage (AWS S3, Cloudflare R2, Supabase Storage) BEFORE trimming, so
# nothing is ever lost without a human downloading it. Opt-in via env; if boto3
# isn't installed or the bucket isn't set, we silently fall back to force-trim.
#
#   TELEMETRY_ARCHIVE_S3_BUCKET     bucket name (enables the feature)
#   TELEMETRY_ARCHIVE_S3_PREFIX     key prefix (default "telemetry/")
#   TELEMETRY_ARCHIVE_S3_ENDPOINT   custom endpoint (R2/Supabase); omit for AWS
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION  standard creds

def _archive_bucket() -> str:
    return os.getenv("TELEMETRY_ARCHIVE_S3_BUCKET", "").strip()


def upload_archive_to_object_storage(data: bytes, filename: str) -> bool:
    """Best-effort upload of the gzip archive. Returns True only on confirmed
    success. Never raises — telemetry maintenance must not break on this."""
    bucket = _archive_bucket()
    if not bucket:
        return False
    try:
        import boto3  # optional dependency; only needed if the feature is on
    except Exception:
        logger.warning("[TELEMETRY-MAINT] object-storage archive requested but boto3 is not installed")
        return False
    try:
        prefix = os.getenv("TELEMETRY_ARCHIVE_S3_PREFIX", "telemetry/")
        endpoint = os.getenv("TELEMETRY_ARCHIVE_S3_ENDPOINT") or None
        key = f"{prefix.rstrip('/')}/{filename}"
        client = boto3.client("s3", endpoint_url=endpoint)
        client.put_object(Bucket=bucket, Key=key, Body=data,
                          ContentType="application/gzip")
        logger.info("[TELEMETRY-MAINT] archived %s bytes to s3://%s/%s", len(data), bucket, key)
        return True
    except Exception as e:
        logger.error("[TELEMETRY-MAINT] object-storage archive failed: %s", e)
        return False


# ── Scheduled maintenance ────────────────────────────────────────────────────

def run_telemetry_db_maintenance():
    """Weekly: retention purge + size guard. Safe to run anywhere."""
    try:
        from database.db import SessionLocal
        from core.models import TelemetryEvent
    except Exception as e:  # pragma: no cover
        logger.warning("[TELEMETRY-MAINT] skipped (%s)", e)
        return

    db = SessionLocal()
    try:
        # 1. Retention purge
        cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
        n = (db.query(TelemetryEvent)
               .filter(TelemetryEvent.received_at < cutoff)
               .delete(synchronize_session=False))
        db.commit()
        if n:
            logger.info("[TELEMETRY-MAINT] retention purge: %s rows older than %s days", n, RETENTION_DAYS)

        # 2. Size guard (force-trim oldest → ~80% of cap)
        size = table_size_bytes(db)
        cap = MAX_MB * 1024 * 1024
        if size > cap:
            logger.warning(
                "[TELEMETRY-MAINT] telemetry_events is %.1f MB (> %s MB cap). "
                "Download an archive from Admin → Telemetry → 'Archive & purge' — "
                "force-trimming oldest rows now to protect the database.",
                size / 1048576, MAX_MB,
            )
            # Hands-off path: if object storage is configured, archive EVERYTHING
            # to the bucket and purge exactly what we archived — no data lost.
            if _archive_bucket():
                data, fname, max_id = build_archive(db)
                if upload_archive_to_object_storage(data, fname):
                    purged = purge_archived(db, max_id)
                    logger.warning("[TELEMETRY-MAINT] over-cap: archived to object storage and purged %s rows", purged)
                    return
                logger.error("[TELEMETRY-MAINT] object-storage archive failed — falling back to force-trim (data will be lost)")
            from sqlalchemy import func
            total = db.query(func.count(TelemetryEvent.id)).scalar() or 0
            # Estimate rows to drop proportionally to the overshoot (keep ~80% cap).
            keep_fraction = (cap * 0.8) / size
            to_drop = max(0, int(total * (1 - keep_fraction)))
            if to_drop:
                subq = (db.query(TelemetryEvent.id)
                          .order_by(TelemetryEvent.received_at.asc())
                          .limit(to_drop).subquery())
                dropped = (db.query(TelemetryEvent)
                             .filter(TelemetryEvent.id.in_(subq))
                             .delete(synchronize_session=False))
                db.commit()
                logger.warning("[TELEMETRY-MAINT] force-trimmed %s oldest rows", dropped)
    except Exception as e:
        db.rollback()
        logger.error("[TELEMETRY-MAINT] failed: %s", e, exc_info=True)
    finally:
        db.close()
