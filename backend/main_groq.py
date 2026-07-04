"""
main_groq.py
============
BizAssist FastAPI application entry point.

Intentionally thin — wires app, middleware, and routers only.
All business logic lives in services/ and routes/.
"""
from __future__ import annotations  # PEP 604 (X | Y) on Python 3.9 dev venvs
from contextlib import asynccontextmanager
from sqlalchemy import text

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

from services.errors import AskError

from routes.upload import router as upload_router
from routes.ai_insights import router as ai_insights_router
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.chat import router as chat_router
from routes.alerts import router as alerts_router
from routes.intents import router as intents_router
from routes.actions import router as actions_router
from routes.ask import router as ask_router
from routes.feedback import router as feedback_router
from routes.data_transfer import router as data_transfer_router
from routes.sync import router as sync_router
from routes.shifts import router as shifts_router   # shift & cash-drawer management (Phase 3)
from routes.public import router as public_router
from routes.telemetry import router as telemetry_router  # testing-phase install diagnostics
from core.api import core_router          # billing ecosystem — wired from core/

from database.db import engine, SessionLocal, DATABASE_URL
from database.models import Base
from database.migration import run_migrations_and_seed
from services.scheduler import start_scheduler, stop_scheduler
from services.embeddings import preload_model_async

load_dotenv()

from logging_config import configure_logging, get_logger
configure_logging()                       # one clean, env-tunable (LOG_LEVEL) config
logger = get_logger("app")

# ── Single-worker guard ───────────────────────────────────────────────────────
# Caches, rate-limit windows, and the APScheduler are process-local (C5). With
# >1 worker you'd get cache misses, doubled rate-limit allowances, and duplicate
# alert emails. Warn loudly until shared state (Redis) lands in Phase 5.
_workers = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS") or os.getenv("GUNICORN_WORKERS")
if _workers and str(_workers).strip().isdigit() and int(_workers) > 1:
    logger.warning(
        f"[ADMIN] {_workers} workers detected, but BizAssist's caches, rate "
        f"limiter, and scheduler are process-local — run a SINGLE worker, or "
        f"expect duplicate alerts and inconsistent limits."
    )

# ── DB ────────────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)
run_migrations_and_seed()

@asynccontextmanager
async def lifespan(_app):
    """Startup/shutdown lifecycle handler."""
    import asyncio
    from services.realtime import realtime_manager
    realtime_manager.set_loop(asyncio.get_running_loop())

    # Start a background task to watch for Uvicorn's should_exit flag.
    # Uvicorn waits for active connections (like our SSE streams) to close
    # *before* calling the lifespan yield teardown. This watcher detects
    # the shutdown signal early and closes SSE queues so Uvicorn can reload.
    async def watch_uvicorn_shutdown():
        import gc
        while True:
            await asyncio.sleep(1.0)
            for obj in gc.get_objects():
                if type(obj).__name__ == "Server" and getattr(obj, "should_exit", False):
                    logger.info("[LIFESPAN] Uvicorn shutdown detected — closing realtime SSE connections...")
                    realtime_manager.shutdown()
                    return
                    
    watcher_task = asyncio.create_task(watch_uvicorn_shutdown())

    start_scheduler()
    preload_model_async()
    yield
    
    watcher_task.cancel()
    realtime_manager.shutdown()
    stop_scheduler()

# ── CORS ──────────────────────────────────────────────────────────────────────
# NOTE: the "null" origin (file:// pages) is intentionally NOT in the defaults —
# it would let any locally-saved HTML file call the API. If you need it for
# local file testing, add it explicitly via ALLOWED_ORIGINS.
_default_origins = (
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,"
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:5174,http://127.0.0.1:5174,"
    "http://localhost:5175,http://127.0.0.1:5175,"
    # Packaged desktop app serves its renderer on these loopback ports
    # (desktop/src/main.js: BILLING_PORT 8450, AI_PORT 8451). The regex below
    # also covers any 127.0.0.1:PORT, but list them explicitly so the app's
    # allowed origin is obvious and greppable.
    "http://127.0.0.1:8450,http://localhost:8450,"
    "http://127.0.0.1:8451,http://localhost:8451,"
    "https://bizassist-react.vercel.app,"
    "https://bizassist.vercel.app,"
    "https://rakshit-dev-bizassist.hf.space"
)
_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="BizAssist API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Client-Request-Id"],
    expose_headers=["X-Total-Count"],
)

# ── Error contract ────────────────────────────────────────────────────────────
@app.exception_handler(AskError)
async def _ask_error_handler(_request: Request, exc: AskError):
    """Render AskError as a real HTTP status code with the canonical envelope (H1)."""
    return JSONResponse(status_code=exc.status_code, content=exc.payload)





@app.get("/")
async def root():
    return {"status": "ok", "message": "BizAssist API is running"}


# ── Postgres RLS & User Context middleware ───────────────────────────────────
# On every request that carries a valid JWT, set the session-local variable
# `app.current_business_id` so Postgres RLS policies can filter by tenant,
# and populate user context variables for audit logging.
from database.db import current_business_id_var, current_user_id_var, current_username_var

@app.middleware("http")
async def _set_rls_business_id(request: Request, call_next):
    """Set business, user, and username contextvars before each request."""
    business_id = None
    user_id = None
    username = None

    # Check for Authorization header or query parameter
    auth_header = request.headers.get("Authorization", "")
    token_param = request.query_params.get("token")
    jwt_token = None

    if auth_header and auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:]
    elif token_param:
        jwt_token = token_param

    if jwt_token:
        try:
            import jwt
            from services.auth import JWT_SECRET, JWT_ALGORITHM
            payload = jwt.decode(
                jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM]
            )
            business_id = payload.get("id")
            user_id = payload.get("user_id") or payload.get("id")
            username = payload.get("username")
        except Exception:
            pass  # invalid / expired token — route will 401 later

    t_biz = current_business_id_var.set(business_id)
    t_uid = current_user_id_var.set(user_id)
    t_uname = current_username_var.set(username)

    try:
        return await call_next(request)
    finally:
        current_business_id_var.reset(t_biz)
        current_user_id_var.reset(t_uid)
        current_username_var.reset(t_uname)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log all unhandled exceptions so no crashes or errors go silent."""
    import logging
    logger = logging.getLogger("bizassist.api")
    logger.error("Unhandled exception during request %s %s: %s", request.method, request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)}
    )



@app.get("/health")
def health_check():
    """
    Liveness / readiness probe.

    Always returns HTTP 200 — callers must inspect the JSON body to determine
    whether the DB is reachable.  This lets load-balancer health checks read
    the response without triggering a 5xx alert on a transient DB hiccup.

    Response shape:
      {"status": "ok",    "db": "connected",    "db_type": "sqlite|postgresql", "mode": "local|cloud", "version": "1.0.0"}
      {"status": "error", "db": "disconnected"}
    """
    # Determine DB type and hosting mode from DATABASE_URL
    _db_url = DATABASE_URL or ""
    db_type = "postgresql" if _db_url.startswith("postgresql") else "sqlite"
    mode    = "cloud" if db_type == "postgresql" else "local"

    # Probe DB with a cheap round-trip
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_status = "connected"
            
            # If SQLite, check if any user has hybrid mode enabled in settings
            if db_type == "sqlite":
                try:
                    import json
                    res = db.execute(text("SELECT settings FROM users")).fetchall()
                    for row in res:
                        settings_str = row[0]
                        if settings_str:
                            s = json.loads(settings_str)
                            if s.get("general", {}).get("hosting_mode") == "hybrid":
                                mode = "hybrid"
                                break
                except Exception:
                    pass
        finally:
            db.close()
        return {
            "status":  "ok",
            "db":      db_status,
            "db_type": db_type,
            "mode":    mode,
            "version": "1.0.0",
        }
    except Exception:
        return {"status": "error", "db": "disconnected"}


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(ask_router)
app.include_router(telemetry_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(upload_router)
app.include_router(ai_insights_router)
app.include_router(chat_router)
app.include_router(alerts_router)
app.include_router(intents_router)
app.include_router(actions_router)
app.include_router(feedback_router)
app.include_router(data_transfer_router)  # Phase 1 – hosting-mode data migration
app.include_router(sync_router)           # Phase 2 – hosting-mode synchronization
app.include_router(shifts_router)         # Phase 3 – shift & cash-drawer management
app.include_router(public_router)         # Phase 4 - Public share links
app.include_router(core_router)           # billing ecosystem (sales + business templates + future)
