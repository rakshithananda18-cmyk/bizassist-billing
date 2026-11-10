"""Provision a disposable local Postgres app role and run the real sync smoke.

TS_SCHEMA_ADMIN_DATABASE_URL must point to a loopback database whose name
contains 'test'. Passwords are generated for this fixture and never printed.
No configured developer .env or production database is consulted.
"""
from pathlib import Path
import importlib.util
import os
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from sqlalchemy.engine import make_url
    raw = os.environ.get("TS_SCHEMA_ADMIN_DATABASE_URL", "")
    url = make_url(raw)
    if url.host not in {"localhost", "127.0.0.1", "::1"} or "test" not in (url.database or "").lower():
        raise RuntimeError("A disposable loopback Postgres database with 'test' in its name is required")
    os.environ.update(DATABASE_URL=raw, BIZASSIST_TEST_DATABASE_URL=raw, BIZASSIST_TESTING="1",
        JWT_SECRET="test-only-secret-please-change-0123456789abcdef", GROQ_API_KEY="mock",
        TELEMETRY_ENABLED="0", SENTRY_DSN="", CLOUD_API_URL="http://127.0.0.1:9")
    import dotenv
    dotenv.load_dotenv = lambda *_a, **_kw: False
    from sqlalchemy import create_engine, text
    from database.db import Base
    import database.models
    from database.security import install_security
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = create_engine(raw)
    role, password = "bizassist_runtime_test", secrets.token_urlsafe(24)
    trade_role, trade_password = "bizassist_trade_test", secrets.token_urlsafe(24)
    admin_role, admin_password = "bizassist_platform_test", secrets.token_urlsafe(24)
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).scalar():
            conn.exec_driver_sql(f'ALTER ROLE "{role}" WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD \'{password}\'')
        else:
            conn.exec_driver_sql(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD \'{password}\'')
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": trade_role}).scalar():
            conn.exec_driver_sql(f'ALTER ROLE "{trade_role}" WITH LOGIN NOSUPERUSER BYPASSRLS PASSWORD \'{trade_password}\'')
        else:
            conn.exec_driver_sql(f'CREATE ROLE "{trade_role}" LOGIN NOSUPERUSER BYPASSRLS PASSWORD \'{trade_password}\'')
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": admin_role}).scalar():
            conn.exec_driver_sql(f'ALTER ROLE "{admin_role}" WITH LOGIN NOSUPERUSER BYPASSRLS PASSWORD \'{admin_password}\'')
        else:
            conn.exec_driver_sql(f'CREATE ROLE "{admin_role}" LOGIN NOSUPERUSER BYPASSRLS PASSWORD \'{admin_password}\'')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # Exercise the additive financial, durable-sync and archival upgrades
        # twice on the complete current schema, proving retry idempotency.
        with Operations.context(MigrationContext.configure(conn)):
            for _ in range(2):
                for name in ("a30f1d7b9c02", "b40e2c8d1f03", "c50f3b9e2a04", "e70b5d2a4c06"):
                    path = next((ROOT / "backend/alembic/versions").glob(name + "_*.py"))
                    spec = importlib.util.spec_from_file_location("smoke_" + name, path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.upgrade()
        install_security(conn, role)
        from database.trade_service import install_trade_role
        install_trade_role(conn, trade_role)
        # Minimal synthetic Field table proves the maintenance service can
        # validate/purge Field-owned rows despite FORCE RLS; it is not a full
        # substitute for Field's own migration/contract suite.
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS ft_settings(id SERIAL PRIMARY KEY,business_id INTEGER NOT NULL)")
        conn.exec_driver_sql("ALTER TABLE ft_settings ENABLE ROW LEVEL SECURITY")
        conn.exec_driver_sql("ALTER TABLE ft_settings FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql("DROP POLICY IF EXISTS test_tenant ON ft_settings")
        conn.exec_driver_sql("CREATE POLICY test_tenant ON ft_settings USING (business_id=nullif(current_setting('app.current_business_id',true),'')::integer)")
        from database.admin_service import install_admin_role
        install_admin_role(conn, admin_role)
    engine.dispose()
    app_url = url.set(username=role, password=password).render_as_string(hide_password=False)
    trade_url = url.set(username=trade_role, password=trade_password).render_as_string(hide_password=False)
    admin_url = url.set(username=admin_role, password=admin_password).render_as_string(hide_password=False)
    env = dict(os.environ, DATABASE_URL=app_url, BIZASSIST_TEST_DATABASE_URL=app_url, DATABASE_TRADE_SERVICE_URL=trade_url,
        ADMIN_SERVICE_URL=admin_url, TS_RUNTIME_TEST_DATABASE_URL=app_url, TS_ADMIN_TEST_DATABASE_URL=raw)
    with tempfile.TemporaryDirectory(prefix="bizassist-test-role-") as work:
        env["PYTHONPATH"] = str(ROOT / "backend")
        script = ("import dotenv; dotenv.load_dotenv=lambda *a,**k:False; "
                  "import pytest,sys; raise SystemExit(pytest.main(sys.argv[1:]))")
        args = [sys.executable, "-c", script, "--noconftest", "-q", "--tb=short", "-p", "no:randomly",
                str(ROOT / "backend/tests/test_sync_protocol_v2.py")]
        args.extend(sys.argv[1:])
        return subprocess.call(args, env=env, cwd=work)


if __name__ == "__main__":
    raise SystemExit(main())
