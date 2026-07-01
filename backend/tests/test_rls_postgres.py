"""
tests/test_rls_postgres.py
==========================
Automated RLS tenant-isolation tests on REAL Postgres — the S-1 (fail-open →
fail-closed) matrix from RLS_FAIL_CLOSED_TEST_PLAN.md, runnable in CI without
touching production.

Provisioning (auto, in priority order):
  1. $TEST_PG_URL set         → use that throwaway Postgres.
  2. Docker + testcontainers  → boot an ephemeral postgres:15 container.
  3. neither                  → SKIP (never blocks the normal SQLite suite).

Why a tiny self-contained `customers` table instead of the app schema: S-1 is
about the *policy predicate* (`... IS NULL OR business_id = ...` vs fail-closed).
This reproduces that predicate on real Postgres and proves the behaviour change,
fast and dependency-free. The production migration applies the same predicate
shape across all tenant tables (see d7e3a9c6f8b1_create_rls_policies).

CRITICAL: RLS does NOT apply to SUPERUSER or BYPASSRLS roles. The tests connect
as a dedicated NOSUPERUSER `app_user` so the policy actually takes effect — this
also mirrors the real-world requirement that the app's DB role must not bypass.
"""
import os
import contextlib
from pathlib import Path
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")


# --------------------------------------------------------------------------- #
# Fixtures: get a superuser DSN (owner) + spin a non-superuser app role.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def pg_admin_dsn():
    """A superuser/owner connection string, from $TEST_PG_URL or testcontainers."""
    url = os.environ.get("TEST_PG_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except Exception:
        pytest.skip("set TEST_PG_URL or install testcontainers[postgres] + run Docker")
    try:
        with PostgresContainer("postgres:15") as pg:
            yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    except Exception as e:
        pytest.skip(f"could not start Postgres container (Docker running?): {e}")


def _connect(dsn, autocommit=True):
    conn = psycopg2.connect(dsn)
    conn.autocommit = autocommit
    return conn


@pytest.fixture()
def schema(pg_admin_dsn):
    """As owner: build `customers`, seed two tenants, enable+FORCE RLS with the
    CURRENT fail-open policy, and create a NOSUPERUSER app role to test under.
    Yields (admin_dsn, app_dsn). Tears down the role/table after."""
    admin = _connect(pg_admin_dsn)
    cur = admin.cursor()
    # Derive an app_user DSN on the same host/db.
    import urllib.parse as up
    u = up.urlparse(pg_admin_dsn)
    app_pw = "app_pw"
    cur.execute("DROP TABLE IF EXISTS customers;")
    cur.execute("DROP ROLE IF EXISTS app_user;")
    cur.execute(f"CREATE ROLE app_user LOGIN PASSWORD '{app_pw}' NOSUPERUSER NOBYPASSRLS;")
    cur.execute("""
        CREATE TABLE customers (
            id          serial PRIMARY KEY,
            business_id integer NOT NULL,
            name        text
        );
    """)
    cur.execute("INSERT INTO customers (business_id, name) VALUES (1,'A-Alice'),(1,'A-Bob'),(2,'B-Carol'),(2,'B-Dave');")
    cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON customers TO app_user;")
    cur.execute("GRANT USAGE, SELECT ON SEQUENCE customers_id_seq TO app_user;")
    cur.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE customers FORCE ROW LEVEL SECURITY;")
    _apply_fail_open(cur)
    app_dsn = f"postgresql://app_user:{app_pw}@{u.hostname}:{u.port}{u.path}"
    try:
        yield pg_admin_dsn, app_dsn
    finally:
        cur.execute("DROP TABLE IF EXISTS customers;")
        cur.execute("DROP ROLE IF EXISTS app_user;")
        cur.close(); admin.close()


def _apply_fail_open(cur):
    cur.execute("DROP POLICY IF EXISTS tenant_isolation ON customers;")
    cur.execute("""
        CREATE POLICY tenant_isolation ON customers
        USING (
            nullif(current_setting('app.current_business_id', true), '') IS NULL
            OR business_id = nullif(current_setting('app.current_business_id', true), '')::integer
        )
        WITH CHECK (
            nullif(current_setting('app.current_business_id', true), '') IS NULL
            OR business_id = nullif(current_setting('app.current_business_id', true), '')::integer
        );
    """)


def _apply_fail_closed(cur):
    # The S-1 fix: drop the `... IS NULL OR` — unset context => no rows.
    cur.execute("DROP POLICY IF EXISTS tenant_isolation ON customers;")
    cur.execute("""
        CREATE POLICY tenant_isolation ON customers
        USING (
            business_id = nullif(current_setting('app.current_business_id', true), '')::integer
        )
        WITH CHECK (
            business_id = nullif(current_setting('app.current_business_id', true), '')::integer
        );
    """)


@contextlib.contextmanager
def _as_app(app_dsn, business_id=None):
    conn = _connect(app_dsn, autocommit=False)
    cur = conn.cursor()
    cur.execute("SELECT set_config('app.current_business_id', %s, false);",
                ("" if business_id is None else str(business_id),))
    try:
        yield cur
    finally:
        conn.rollback(); cur.close(); conn.close()


def _count(cur):
    cur.execute("SELECT count(*) FROM customers;")
    return cur.fetchone()[0]


# --------------------------------------------------------------------------- #
# Tests — mirror RLS_FAIL_CLOSED_TEST_PLAN.md §4.
# --------------------------------------------------------------------------- #
def test_T1_fail_open_unset_context_sees_all(schema):
    """T1 (repro): with today's fail-open policy, an UNSET context sees every
    tenant's rows — this is the S-1 gap."""
    _, app_dsn = schema
    with _as_app(app_dsn, None) as cur:
        assert _count(cur) == 4   # all of A + B


def test_T2_fail_closed_unset_context_sees_nothing(schema):
    """T2: after the fix, an unset context sees ZERO rows (no leak)."""
    admin_dsn, app_dsn = schema
    admin = _connect(admin_dsn); _apply_fail_closed(admin.cursor()); admin.close()
    with _as_app(app_dsn, None) as cur:
        assert _count(cur) == 0


def test_T3_fail_closed_tenant_sees_only_own(schema):
    """T3: tenant A sees only A's rows, never B's."""
    admin_dsn, app_dsn = schema
    admin = _connect(admin_dsn); _apply_fail_closed(admin.cursor()); admin.close()
    with _as_app(app_dsn, 1) as cur:
        assert _count(cur) == 2
        cur.execute("SELECT DISTINCT business_id FROM customers;")
        assert [r[0] for r in cur.fetchall()] == [1]


def test_T5_fail_closed_cross_tenant_insert_blocked(schema):
    """T5: as tenant A, inserting a row scoped to B is rejected by WITH CHECK."""
    admin_dsn, app_dsn = schema
    admin = _connect(admin_dsn); _apply_fail_closed(admin.cursor()); admin.close()
    with _as_app(app_dsn, 1) as cur:
        with pytest.raises(psycopg2.errors.Error):
            cur.execute("INSERT INTO customers (business_id, name) VALUES (2, 'sneaky');")


def test_T6_fail_closed_cross_tenant_update_affects_zero(schema):
    """T6: as tenant A, UPDATE/DELETE of B's rows affects 0 rows (invisible)."""
    admin_dsn, app_dsn = schema
    admin = _connect(admin_dsn); _apply_fail_closed(admin.cursor()); admin.close()
    with _as_app(app_dsn, 1) as cur:
        cur.execute("UPDATE customers SET name='hacked' WHERE business_id = 2;")
        assert cur.rowcount == 0


def test_production_rls_migration_does_not_fail_open():
    """The production Alembic policy must not reintroduce the old
    `setting IS NULL OR tenant_match` fail-open predicate."""
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "d7e3a9c6f8b1_create_rls_policies.py"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "nullif(current_setting('app.current_business_id', true), '') IS NULL" not in sql
    assert "WITH CHECK" in sql


def test_optimized_rls_migration_uses_init_plan_wrapper():
    """Supabase's advisor expects policy helper calls to be wrapped in a scalar
    SELECT so they are initialized once per statement."""
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "3b7d5e0a9c1f_optimize_rls_init_plan.py"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "(select nullif(current_setting('app.current_business_id', true), '')::integer)" in sql
    assert "BID = \"nullif(current_setting" not in sql
    assert "USING (true)" not in sql
