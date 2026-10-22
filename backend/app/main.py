"""
app/main.py — BizAssist Task API (field team: attendance, routes, deliveries,
tasks, points, live location) + the built PWA at "/".

Run:  uvicorn app.main:app --port 8002            (dev)
HF :  see ../Dockerfile (one process, port 7860)

ONE PROCESS ONLY. Login throttling and the purge loop are in-memory, like
billing's (WEB_CONCURRENCY=1). Do not add --workers without moving them out.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect

from app import config
from app.billing_models import BillingBase
from app.db import SessionLocal, engine, utc_now
from app.routers import attendance, auth, dashboard, requests, runs, shops, staff, tasks, tracking

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bizassist.task")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["configure_logger"] = False
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def prepare_database() -> None:
    if config.CREATE_BILLING_MIRROR:
        BillingBase.metadata.create_all(bind=engine)
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
    task = asyncio.create_task(_purge_loop())
    logger.info("[BOOT] BizAssist Task ready db=%s tz=%s", engine.dialect.name, config.BIZ_TIMEZONE)
    yield
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

for r in (auth, staff, attendance, shops, runs, tasks, requests, tracking, dashboard):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    from app.timeutil import biz_today, iso_utc
    return {"ok": True, "server_time": iso_utc(utc_now()), "business_date": biz_today(), "tz": config.BIZ_TIMEZONE}


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
