"""
app/db.py — engine, sessions and the two metadata registries.
=============================================================
Two declarative bases, on purpose:

  * `BillingBase` — a READ-MOSTLY mirror of the handful of billing tables this
    service needs (`users`, `customers`). Billing owns those tables and their
    migrations. This service never creates or alters them in production; on
    SQLite (dev/tests) it creates a minimal copy so the app runs standalone.

  * `Base` — this service's own tables, all prefixed `ft_` (field team). Managed
    by this repo's Alembic chain, recorded in its own version table
    (`ft_alembic_version`) so it can never collide with billing's chain.

Timestamps are stored NAIVE UTC, the same convention billing uses
(services/dates.utc_now) so rows from both services compare cleanly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app import config

_NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base(metadata=MetaData(naming_convention=_NAMING))
BillingBase = declarative_base(metadata=MetaData(naming_convention=_NAMING))


# Added to every utc_now(). Always zero in the service; the test suite sets it
# to pin the business clock to midday IST (tests/conftest.py), so a run that
# crosses midnight neither turns on-time work late nor moves "today".
CLOCK_OFFSET = timedelta(0)


def utc_now() -> datetime:
    """Naive UTC now — the storage convention shared with billing."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + CLOCK_OFFSET


if config.IS_SQLITE:
    engine = create_engine(
        config.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
        finally:
            cur.close()
else:
    # Small pool: Supabase's free tier caps connections and billing already holds
    # pool_size=3 + overflow 2. Keep this service's footprint at most the same.
    engine = create_engine(
        config.DATABASE_URL,
        connect_args={"connect_timeout": 5},
        pool_size=3,
        max_overflow=2,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _clear_postgres_tenant_guc(dbapi_connection, _connection_record, _connection_proxy):
    """Clear any tenant left by an older build before a pooled connection is used."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("RESET app.current_business_id")
    finally:
        cursor.close()


def _set_postgres_tenant_guc(session, _transaction, connection):
    """Bind the Session's authenticated tenant to each new transaction.

    A commit returns the connection to the pool. ORM serialization can then
    start another transaction on a different connection, so setting the GUC
    once per request is insufficient. SET LOCAL also disappears automatically
    on commit/rollback instead of leaking into another request.
    """
    business_id = session.info.get("rls_bid")
    value = "" if business_id is None else str(int(business_id))
    connection.execute(
        text("SELECT set_config('app.current_business_id', :bid, true)"),
        {"bid": value},
    )


if engine.dialect.name == "postgresql":
    event.listen(engine, "checkout", _clear_postgres_tenant_guc)
    event.listen(SessionLocal, "after_begin", _set_postgres_tenant_guc)


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_rls_business(db, business_id: int) -> None:
    """Mirror billing's RLS context (`app.current_business_id`) on Postgres.

    Billing's tables carry FORCE ROW LEVEL SECURITY policies keyed on this
    setting, and the ft_* migration adds the same policy to our tables. The app
    already scopes every query by business_id; this is defence in depth for a
    connection role that does not bypass RLS.
    """
    if engine.dialect.name != "postgresql":
        return
    # Authentication may already have opened a transaction while resolving the
    # owner. Bind that transaction now and retain the tenant for future ones.
    db.info["rls_bid"] = int(business_id)
    db.execute(
        text("SELECT set_config('app.current_business_id', :bid, true)"),
        {"bid": str(int(business_id))},
    )
