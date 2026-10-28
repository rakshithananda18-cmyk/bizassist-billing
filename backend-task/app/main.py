"""
app/main.py — BizAssist Task API (field team: attendance, routes, deliveries,
tasks, points, live location) + the built PWA at "/".

Run:  uvicorn app.main:app --port 8002            (dev)
HF :  see Dockerfile in this folder (API only, one process, port 7860)

ONE PROCESS ONLY. Login throttling and the purge loop are in-memory, like
billing's (WEB_CONCURRENCY=1). Do not add --workers without moving them out.
"""
from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app import config
from app.logging_config import TAG, configure_logging, current_bizid_var, get_logger

configure_logging(config.LOG_LEVEL)

from app.billing_models import BillingBase  # noqa: E402
from app.db import SessionLocal, engine, utc_now  # noqa: E402
from app.routers import attendance, auth, dashboard, requests, runs, shops, staff, tasks, tracking  # noqa: E402
from app.security import bizid_from_authorization  # noqa: E402

logger = get_logger("task")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _unknown_revisions(conn, script) -> list:
    """Revisions the database is at that this build has no migration file for:
    a newer build migrated it (a rollback, or a dev folder switched to an older
    branch)."""
    from alembic.migration import MigrationContext
    from alembic.util import CommandError

    from app.migration_scope import VERSION_TABLE

    heads = MigrationContext.configure(conn, opts={"version_table": VERSION_TABLE}).get_current_heads()
    unknown = []
    for rev in heads:
        try:
            script.get_revision(rev)
        except CommandError:
            unknown.append(rev)
    return unknown


def run_migrations(bind=None) -> bool:
    """Upgrade the ft_* tables to this build's head. Returns False, and leaves
    the database alone, when it is already past what this build knows — the
    ft_* migrations only add tables and columns, so an older build still runs
    on the newer schema, and failing here would block every rollback."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["configure_logger"] = False
    script = ScriptDirectory.from_config(cfg)
    with (bind or engine).begin() as conn:
        ahead = _unknown_revisions(conn, script)
        if ahead:
            logger.warning(
                "%s database is at migration %s, newer than this build's head %s — skipping migrations. "
                "Expected after a rollback; deploy the newer build to migrate again.",
                TAG.BOOT, ", ".join(ahead), script.get_current_head(),
            )
            return False
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    return True


def add_missing_mirror_columns(bind=None) -> list:
    """Standalone dev databases only (TASK_CREATE_BILLING_MIRROR). `create_all`
    creates a missing mirror table but never adds a column to one that exists,
    so a local database made before the mirror gained a column (users.settings,
    for the Pro gate) failed every query on that table. Add those columns —
    nullable ones, which is all the mirror ever adds. Billing's real tables are
    never touched: the mirror is off wherever billing owns the database."""
    bind = bind or engine
    insp = inspect(bind)
    added = []
    with bind.begin() as conn:
        for table in BillingBase.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable and col.server_default is None:
                    logger.warning("%s local %s has no %s and it cannot be added (NOT NULL) — recreate the dev database",
                                   TAG.BOOT, table.name, col.name)
                    continue
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=bind.dialect)}"))
                added.append(f"{table.name}.{col.name}")
    if added:
        logger.info("%s added %s to the local billing mirror", TAG.BOOT, ", ".join(added))
    return added


def prepare_database() -> None:
    if config.CREATE_BILLING_MIRROR:
        BillingBase.metadata.create_all(bind=engine)
        add_missing_mirror_columns()
    tables = set(inspect(engine).get_table_names())
    if "users" not in tables:
        raise RuntimeError(
            "Table 'users' not found. Point DATABASE_URL at the BizAssist billing database "
            "(same Supabase URL as the billing Space), or set TASK_CREATE_BILLING_MIRROR=1 for a standalone dev DB."
        )
    if config.AUTO_MIGRATE:
        run_migrations()


async def _purge_loop() -> None:
    from app.routers.tracking import purge_old_pings
    while True:
        await asyncio.sleep(6 * 3600)
        try:
            db = SessionLocal()
            try:
                n = purge_old_pings(db, config.PING_RETENTION_DAYS)
            finally:
                db.close()
            if n:
                logger.info("[TRACK] purged %s ping(s) older than %s days", n, config.PING_RETENTION_DAYS)
        except Exception:
            logger.exception("[TRACK] ping purge failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    prepare_database()
    task = asyncio.create_task(_purge_loop()) if config.PURGE_LOOP else None
    logger.info("[BOOT] BizAssist Task ready db=%s tz=%s purge=%s", engine.dialect.name, config.BIZ_TIMEZONE,
                "loop" if task else ("scheduled" if config.CRON_SECRET else "off"))
    yield
    if task:
        task.cancel()


app = FastAPI(title="BizAssist Task API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def _bizid_log_context(request: Request, call_next):
    """[BizId=…] on every log line of this request (app/logging_config.py).
    Set here, in async middleware, for the same reason as billing's main_groq.py:
    a contextvar set in a sync dependency never reaches the route's log lines."""
    token = current_bizid_var.set(bizid_from_authorization(request.headers.get("Authorization")) or "-")
    try:
        return await call_next(request)
    finally:
        current_bizid_var.reset(token)


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Log every unhandled error with its route, so no crash goes silent."""
    logger.error("%s unhandled %s %s", TAG.HTTP, request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


for r in (auth, staff, attendance, shops, runs, tasks, requests, tracking, dashboard):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    from app.timeutil import biz_today, iso_utc
    # A dialect name alone does not prove that the configured database is
    # reachable. Probe without touching business rows, and expose only safe
    # operational flags; never return driver errors or connection strings.
    result = {"ok": True, "server_time": iso_utc(utc_now()), "business_date": biz_today(),
              "tz": config.BIZ_TIMEZONE, "db": engine.dialect.name,
              "pro_required": config.REQUIRE_PRO, "billing_mirror": config.CREATE_BILLING_MIRROR,
              "cloud_only": True}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("%s database health probe failed", TAG.BOOT)
        return JSONResponse({**result, "ok": False, "reason": "database_unavailable"}, status_code=503)
    return result


@app.post("/api/internal/purge-pings", include_in_schema=False)
def purge_pings_now(x_cron_secret: Optional[str] = Header(None)):
    """GPS retention where no CPU runs between requests (Cloud Run): Cloud
    Scheduler calls this daily with the shared secret. 404 unless configured."""
    if not config.CRON_SECRET:
        raise HTTPException(status_code=404, detail="Not Found")
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret.encode(), config.CRON_SECRET.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.routers.tracking import purge_old_pings
    db = SessionLocal()
    try:
        n = purge_old_pings(db, config.PING_RETENTION_DAYS)
    finally:
        db.close()
    logger.info("%s purged %s ping(s) older than %s days (scheduled)", TAG.TRACK, n, config.PING_RETENTION_DAYS)
    return {"ok": True, "purged": n, "retention_days": config.PING_RETENTION_DAYS}


# ── Built PWA (same origin → no CORS, and HTTPS on HF for geolocation) ───────
_index = os.path.join(config.STATIC_DIR, "index.html")
if os.path.isfile(_index):
    _assets = os.path.join(config.STATIC_DIR, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = os.path.realpath(os.path.join(config.STATIC_DIR, path))
        if path and candidate.startswith(os.path.realpath(config.STATIC_DIR)) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(_index, headers={"Cache-Control": "no-cache"})
else:
    # API-only (the HF Space): the screens are frontend-task/ on Vercel. Answer
    # "/" so the Space's start-up probe and its page get a 200, not a 404.
    @app.get("/", include_in_schema=False)
    def root():
        return {"service": "bizassist-task", "ok": True, "health": "/api/health"}
