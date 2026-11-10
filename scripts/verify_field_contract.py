"""Run Field on Billing's full migrated schema in a disposable loopback PG DB.

TS_SCHEMA_ADMIN_DATABASE_URL must privately name a loopback test/control DB.
The generated database is removed on exit; no URL or credential is printed.
"""
from pathlib import Path
import os
import re
import socket
import sys
import uuid


def main():
    root = Path(__file__).resolve().parents[1]
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    control_url = make_url(os.environ.get("TS_SCHEMA_ADMIN_DATABASE_URL", ""))
    if control_url.host not in {"localhost", "127.0.0.1", "::1"} or (
        control_url.database != "postgres" and "test" not in (control_url.database or "").lower()
    ):
        raise RuntimeError("Disposable loopback PostgreSQL test/control URL required")

    import dotenv
    dotenv.load_dotenv = lambda *_a, **_kw: False
    original_connect, original_dns = socket.socket.connect, socket.getaddrinfo

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"localhost", "127.0.0.1", "::1"}:
            raise OSError("External network denied during Field contract verification")
        return original_connect(sock, address)

    def dns(host, *args, **kwargs):
        if host not in {None, "localhost", "127.0.0.1", "::1"}:
            raise OSError("External DNS denied during Field contract verification")
        return original_dns(host, *args, **kwargs)

    socket.socket.connect, socket.getaddrinfo = connect, dns
    task_db_name = "field_contract_test_" + uuid.uuid4().hex[:12]
    admin = create_engine(control_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    target = control_url.set(database=task_db_name).render_as_string(hide_password=False)
    app_engine = None
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(
                f'CREATE DATABASE "{task_db_name}" WITH TEMPLATE template0 '
                "ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
            )
        os.environ.update({
            "DATABASE_URL": target, "BIZASSIST_TEST_DATABASE_URL": target,
            "TASK_TEST_DATABASE_URL": target, "TASK_RLS_ADMIN_TEST_URL": target,
            "TASK_TEST_BILLING_SCHEMA": "external", "TASK_CREATE_BILLING_MIRROR": "0",
            "BILLING_BACKEND_DIR": str(root / "backend"), "BIZASSIST_TESTING": "1",
            "JWT_SECRET": "test-only-secret-please-change-0123456789abcdef",
            "SUBSCRIPTION_ENFORCED": "0", "TASK_PURGE_LOOP": "0", "TASK_CRON_SECRET": "",
            "SPACE_ID": "", "K_SERVICE": "", "ENVIRONMENT": "", "GROQ_API_KEY": "mock",
            "SENTRY_DSN": "", "TELEMETRY_ENABLED": "0", "CHAT_MEMORY_ENABLED": "0",
            "ANONYMIZED_TELEMETRY": "False", "CLOUD_URL": "http://127.0.0.1:9",
            "CLOUD_API_URL": "http://127.0.0.1:9", "BIZASSIST_CLOUD_URL": "http://127.0.0.1:9",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "LOG_FORMAT": "text", "LOG_LEVEL": "WARNING",
        })
        # Field's app package must win over Billing's legacy app.py module.
        sys.path.insert(0, str(root / "backend-task"))
        sys.path.append(str(root / "backend"))
        os.chdir(root / "backend")
        from alembic import command
        from alembic.config import Config
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        from database.db import engine as billing_engine
        app_engine = billing_engine
        os.chdir(root / "backend-task")
        # Each Billing Alembic environment prepends backend/ to sys.path.
        # Restore Field's package precedence before pytest imports conftest.
        sys.path.insert(0, str(root / "backend-task"))
        import pytest
        return pytest.main(["-p", "anyio.pytest_plugin", *sys.argv[1:]])
    finally:
        if app_engine is not None:
            app_engine.dispose()
        if "app.db" in sys.modules:
            sys.modules["app.db"].engine.dispose()
        if not re.fullmatch(r"field_contract_test_[0-9a-f]{12}", task_db_name):
            raise RuntimeError("Refusing unexpected test database cleanup target")
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{task_db_name}" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
