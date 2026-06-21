"""
main_groq.py
============
BizAssist FastAPI application entry point.

Intentionally thin — wires app, middleware, and routers only.
All business logic lives in services/ and routes/.
"""
from contextlib import asynccontextmanager

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
from core.api import core_router          # billing ecosystem — wired from core/
from database.db import engine
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
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Total-Count"],
)

# ── Error contract ────────────────────────────────────────────────────────────
@app.exception_handler(AskError)
async def _ask_error_handler(_request: Request, exc: AskError):
    """Render AskError as a real HTTP status code with the canonical envelope (H1)."""
    return JSONResponse(status_code=exc.status_code, content=exc.payload)

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
app.include_router(core_router)           # billing ecosystem (sales + business templates + future)
