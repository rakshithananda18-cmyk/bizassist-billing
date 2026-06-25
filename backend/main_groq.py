"""
main_groq.py
============
BizAssist FastAPI application entry point.

Intentionally thin — wires app, middleware, and routers only.
All business logic lives in services/ and routes/.
"""
from contextlib import asynccontextmanager
from sqlalchemy import text

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

from services.errors import AskError

from routes.upload import router as upload_router
from routes.insights import router as insights_router
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.chat import router as chat_router
from routes.alerts import router as alerts_router
from routes.intents import router as intents_router
from routes.actions import router as actions_router
from routes.ask import router as ask_router
from routes.feedback import router as feedback_router
from routes.smart_insights import router as smart_insights_router
from routes.migrate import router as migrate_router
from routes.sync import router as sync_router
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

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app):
    """Startup/shutdown lifecycle handler."""
    start_scheduler()
    preload_model_async()
    yield
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


# ── Postgres RLS middleware ───────────────────────────────────────────────────
# On every request that carries a valid JWT, set the session-local variable
# `app.current_business_id` so Postgres RLS policies can filter by tenant.
# No-op on SQLite (dev/test) — the dialect check guards safely.
from database.db import current_business_id_var

@app.middleware("http")
async def _set_rls_business_id(request: Request, call_next):
    """Set current_business_id_var contextvar for Postgres RLS before each request."""
    business_id: int | None = None

    # Extract business_id from Bearer token (best-effort — auth errors are
    # handled by the route-level dependency; we never raise here).
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import jwt
            from services.auth import JWT_SECRET, JWT_ALGORITHM
            payload = jwt.decode(
                auth_header[7:], JWT_SECRET, algorithms=[JWT_ALGORITHM]
            )
            business_id = payload.get("id")
        except Exception:
            pass  # invalid / expired token — route will 401 later

    token = current_business_id_var.set(business_id)
    try:
        return await call_next(request)
    finally:
        current_business_id_var.reset(token)


@app.get("/")
async def root():
    return {"status": "ok", "message": "BizAssist API is running"}


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
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(upload_router)
app.include_router(insights_router)
app.include_router(chat_router)
app.include_router(alerts_router)
app.include_router(intents_router)
app.include_router(actions_router)
app.include_router(feedback_router)
app.include_router(smart_insights_router)
app.include_router(migrate_router)        # Phase 1 – hosting-mode data migration
app.include_router(sync_router)           # Phase 2 – hosting-mode synchronization
app.include_router(core_router)           # billing ecosystem (sales + business templates + future)
