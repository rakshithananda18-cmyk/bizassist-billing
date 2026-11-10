"""Tenant identity survives commits without persisting on pooled connections."""
from types import SimpleNamespace
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app import db as app_db


@pytest.fixture
def transaction_probe(tmp_path):
    """Real Session/pool lifecycle; record PostgreSQL GUC SQL on SQLite.

    Only the PostgreSQL-specific statement is translated. Commits, rollbacks,
    connection checkouts and Session info are exercised by SQLAlchemy itself.
    The Postgres-only test below additionally executes the unmodified SQL.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'tenant_test.db'}")
    calls = []

    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if "set_config('app.current_business_id'" in statement:
            calls.append((statement, parameters))
            return "SELECT 1", ()
        return statement, parameters

    factory = sessionmaker(bind=engine)
    event.listen(factory, "after_begin", app_db._set_postgres_tenant_guc)
    try:
        yield factory, calls
    finally:
        engine.dispose()


def test_tenant_reapplied_after_commit_and_rollback(transaction_probe, monkeypatch):
    factory, calls = transaction_probe
    monkeypatch.setattr(app_db, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    with factory() as session:
        # Owner lookup can already have begun before authentication binds it.
        session.execute(text("SELECT 1"))
        assert calls[-1][1] == ("",)
        app_db.set_rls_business(session, 41)
        assert calls[-1][1] == ("41",)
        session.commit()
        session.execute(text("SELECT 1"))
        assert calls[-1][1] == ("41",)
        session.rollback()
        session.execute(text("SELECT 1"))
        assert calls[-1][1] == ("41",)
    assert all(", true)" in statement for statement, _ in calls)


def test_fresh_session_begins_without_previous_business(transaction_probe):
    factory, calls = transaction_probe
    with factory() as old:
        old.info["rls_bid"] = 41
        old.execute(text("SELECT 1"))
        old.commit()
    with factory() as fresh:
        fresh.execute(text("SELECT 1"))
        assert calls[-1][1] == ("",)
        fresh.info["rls_bid"] = 73
        fresh.commit()
        fresh.execute(text("SELECT 1"))
        assert calls[-1][1] == ("73",)


def test_pool_checkout_clears_legacy_session_setting_and_closes_cursor():
    calls = []
    cursor = SimpleNamespace(execute=lambda sql: calls.append(sql), close=lambda: calls.append("close"))
    connection = SimpleNamespace(cursor=lambda: cursor)
    app_db._clear_postgres_tenant_guc(connection, None, None)
    assert calls == ["RESET app.current_business_id", "close"]


@pytest.mark.skipif(app_db.engine.dialect.name != "postgresql", reason="requires disposable Postgres test database")
def test_real_postgres_tenant_survives_connection_change_and_pool_reuse():
    """CI's Postgres job executes real GUCs, even with a superuser test role."""
    read = text("SELECT current_setting('app.current_business_id', true)")
    with app_db.SessionLocal() as owner:
        app_db.set_rls_business(owner, 41)
        assert owner.scalar(read) == "41"
        owner.commit()
        # Occupy the connection just returned by commit, forcing the Session
        # to obtain another connection for post-commit ORM/read work.
        with app_db.engine.connect() as occupied:
            assert occupied.scalar(read) in (None, "")
            assert owner.scalar(read) == "41"
            owner.rollback()
            assert owner.scalar(read) == "41"
    with app_db.SessionLocal() as public:
        assert public.scalar(read) in (None, "")


@pytest.mark.skipif(not os.getenv("TASK_RLS_ADMIN_TEST_URL"), reason="requires disposable Postgres admin test URL")
def test_non_bypass_role_keeps_rls_isolation_across_transactions():
    """Exercise real FORCE RLS using a role that cannot bypass the policy.

    This is opt-in because creating a login role needs a disposable cluster's
    admin account. All objects use a unique test schema/role and are removed.
    No Billing/Field business table or production connection is used.
    """
    admin_url = make_url(os.environ["TASK_RLS_ADMIN_TEST_URL"])
    task_url = app_db.engine.url
    assert app_db.engine.dialect.name == "postgresql"
    assert admin_url.host in {"localhost", "127.0.0.1", "::1"}
    assert admin_url.database and "test" in admin_url.database.lower()
    assert (admin_url.host, admin_url.port, admin_url.database) == (task_url.host, task_url.port, task_url.database)
    if admin_url.drivername in {"postgres", "postgresql"}:
        admin_url = admin_url.set(drivername="postgresql+psycopg2")
    suffix = uuid.uuid4().hex[:16]
    schema, role = f"ft_rls_test_{suffix}", f"ft_rls_user_{suffix}"
    password = uuid.uuid4().hex
    table = f'"{schema}".tenant_probe'
    admin = create_engine(admin_url, connect_args={"connect_timeout": 5})
    restricted = None
    try:
        with admin.begin() as conn:
            conn.execute(text(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f"CREATE TABLE {table} (business_id integer NOT NULL, label text NOT NULL)"))
            conn.execute(text(f"INSERT INTO {table} VALUES (41, 'first'), (73, 'second')"))
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            bid = "nullif(current_setting('app.current_business_id', true), '')::integer"
            conn.execute(text(f"CREATE POLICY tenant_isolation ON {table} USING (business_id = {bid}) WITH CHECK (business_id = {bid})"))
            conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}'))
            conn.execute(text(f"GRANT SELECT, INSERT ON {table} TO {role}"))
            assert conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"), {"role": role}).one() == (False, False)

        restricted = create_engine(admin_url.set(username=role, password=password), pool_size=3, max_overflow=0,
                                   connect_args={"connect_timeout": 5})
        event.listen(restricted, "checkout", app_db._clear_postgres_tenant_guc)
        sessions = sessionmaker(bind=restricted)
        event.listen(sessions, "after_begin", app_db._set_postgres_tenant_guc)
        read = text(f"SELECT label FROM {table} ORDER BY label")
        with sessions() as owner:
            app_db.set_rls_business(owner, 41)
            assert owner.scalars(read).all() == ["first"]
            owner.commit()
            with restricted.connect() as occupied:
                assert occupied.scalars(read).all() == []
                assert owner.scalars(read).all() == ["first"]
                owner.rollback()
                assert owner.scalars(read).all() == ["first"]
                with sessions() as other:
                    app_db.set_rls_business(other, 73)
                    assert other.scalars(read).all() == ["second"]
                assert owner.scalars(read).all() == ["first"]
            with pytest.raises(DBAPIError):
                owner.execute(text(f"INSERT INTO {table} VALUES (73, 'blocked')"))
            owner.rollback()
        with sessions() as public:
            assert public.scalars(read).all() == []
        # Explicitly seed a legacy session-wide value. Checkout must remove
        # it even for an engine connection with no Session after_begin hook.
        # Empty the idle pool so both operations reuse its sole connection.
        restricted.dispose()
        with restricted.begin() as legacy:
            legacy_pid = legacy.scalar(text("SELECT pg_backend_pid()"))
            legacy.execute(text("SELECT set_config('app.current_business_id', '41', false)"))
        with restricted.connect() as public:
            assert public.scalar(text("SELECT pg_backend_pid()")) == legacy_pid
            assert public.scalars(read).all() == []
    finally:
        if restricted is not None:
            restricted.dispose()
        try:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        finally:
            admin.dispose()
