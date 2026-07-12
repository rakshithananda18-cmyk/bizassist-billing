import os
import sys
import uuid
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData, Column, Integer, DateTime, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

# Deterministic names for indexes/constraints. Required for Alembic to ALTER
# tables on SQLite (batch mode can't create unnamed constraints), and good
# practice everywhere. Applied to every model via the shared Base below.
_NAMING_CONVENTION = {
    "ix":  "ix_%(column_0_label)s",
    "uq":  "uq_%(table_name)s_%(column_0_name)s",
    "ck":  "ck_%(table_name)s_%(constraint_name)s",
    "fk":  "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk":  "pk_%(table_name)s",
}

# Load .env file
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./bizassist.db")

# ── Fail-closed test-isolation guard ──
# History (July 2026): the test suite seeded ~21 fixture cashiers ("c_XXXX" /
# "cash_XXXX") into the real dev DB (bizassist.db) under a live business, because
# every test file uses os.environ.setdefault("DATABASE_URL", ".../test_bizassist.db")
# and setdefault does NOT override a DATABASE_URL already exported in the shell
# (or the db.py default) when tests are launched outside pytest/conftest. This
# guard makes that impossible: in any test context the DB URL MUST be a test DB.
_IN_TEST = ("pytest" in sys.modules
            or "PYTEST_CURRENT_TEST" in os.environ
            or os.environ.get("BIZASSIST_TESTING") == "1"
            or any(os.path.basename(a).startswith("test_") for a in sys.argv))
if _IN_TEST and "test" not in DATABASE_URL.lower():
    raise RuntimeError(
        "Refusing to run tests against a non-test database. "
        "DATABASE_URL=%r . A test context was detected but the DB is not a test "
        "DB. Point DATABASE_URL at a URL containing 'test' (e.g. "
        "sqlite:///./test_bizassist.db) or unset the exported DATABASE_URL. This "
        "guard stops test fixtures polluting real data." % DATABASE_URL
    )

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False
        }
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=3,
        max_overflow=2,
        pool_recycle=1800,
        pool_pre_ping=True
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base(metadata=MetaData(naming_convention=_NAMING_CONVENTION))


# ---------------------------------------------------------------------------
# SHARED MIXINS
# ---------------------------------------------------------------------------
# Live here (neutral, model-free module) rather than in database/models.py so
# that BOTH the shared models AND core/models.py can inherit them without an
# import cycle (core/models ↔ database/models would otherwise loop). They are
# re-exported from database.models for backward compatibility.

class TimestampMixin:
    """Adds created_at / updated_at. Does NOT add id or business_id."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)


class BusinessOwnedMixin(TimestampMixin):
    """Every tenant-scoped table inherits this: id, business_id, timestamps."""
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=True)
    # Step 3 (R-3) — Durable, globally-unique key for cross-DB sync/migration.
    # `id` is a per-database autoincrement (local id=10 != cloud id=10), so
    # matching on it causes wrong-row overwrites. Sync/migration match on `uid`
    # instead (Phase B). Generated ORM-side at row creation; nullable for
    # backfill (the Phase A migration fills existing rows). No index yet — no
    # uid lookups happen until Phase B lands, which adds it alongside the
    # match-key switch. The integer `id` stays for fast local joins/FKs.
    uid = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))


import contextvars
from sqlalchemy import text

current_business_id_var = contextvars.ContextVar("current_business_id", default=None)
current_user_id_var = contextvars.ContextVar("current_user_id", default=None)
current_username_var = contextvars.ContextVar("current_username", default=None)
sync_disabled_var = contextvars.ContextVar("sync_disabled", default=False)

def get_db():
    """
    FastAPI dependency that yields a DB session and always closes it — even on
    an early return or a raised exception (H6). Use in routes:

        @router.get("/x")
        def x(db: Session = Depends(get_db)):
            ...

    Service-layer functions called outside a request (e.g. the scheduler) keep
    using `SessionLocal()` directly.
    """
    db = SessionLocal()
    business_id = current_business_id_var.get()
    
    if business_id is not None and db.bind.dialect.name == "postgresql":
        try:
            # set_config() takes bound parameters (SET does not) — defense in
            # depth even though business_id is already int()-cast upstream.
            db.execute(text("SELECT set_config('app.current_business_id', :bid, false)"),
                       {"bid": str(int(business_id))})
        except Exception:
            # We fail silently or log, but do not block request startup unless database is totally down
            pass
            
    try:
        yield db
    finally:
        if business_id is not None and db.bind.dialect.name == "postgresql":
            try:
                db.execute(text("RESET app.current_business_id"))
            except Exception:
                pass
        db.close()