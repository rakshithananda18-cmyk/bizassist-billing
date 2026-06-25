import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData, Column, Integer, DateTime
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

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False
        }
    )
else:
    from sqlalchemy.pool import NullPool
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool
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


import contextvars
from sqlalchemy import text

current_business_id_var = contextvars.ContextVar("current_business_id", default=None)
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
            db.execute(text(f"SET app.current_business_id = '{int(business_id)}'"))
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