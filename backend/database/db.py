import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData
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
    engine = create_engine(
        DATABASE_URL
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base(metadata=MetaData(naming_convention=_NAMING_CONVENTION))


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
    try:
        yield db
    finally:
        db.close()