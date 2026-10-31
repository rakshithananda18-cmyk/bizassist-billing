"""Run the complete Alembic chain on a fresh disposable DB, then check metadata.

Postgres requires TS_SCHEMA_ADMIN_DATABASE_URL on loopback, pointing to the
control database 'postgres' or a test database. It creates a separate random
test database; no developer or
production schema is altered. Connection strings and passwords are not printed.
"""
from pathlib import Path
import argparse
import os
import sys
import tempfile
import uuid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dialect", choices=("sqlite", "postgres"), required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    admin = None
    task_database_name = None
    if args.dialect == "sqlite":
        (root / "scratch").mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="schema_chain_test_", dir=root / "scratch"))
        target = "sqlite:///" + (work / "test_upgrade.db").as_posix()
    else:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        raw = os.environ.get("TS_SCHEMA_ADMIN_DATABASE_URL", "")
        url = make_url(raw)
        if url.host not in {"localhost", "127.0.0.1", "::1"} or (url.database != "postgres" and "test" not in (url.database or "").lower()):
            raise RuntimeError("Disposable loopback PostgreSQL admin URL with test database required")
        admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
        task_database_name = "schema_chain_test_" + uuid.uuid4().hex[:12]
        with admin.connect() as conn:
            conn.exec_driver_sql(
                f'CREATE DATABASE "{task_database_name}" WITH TEMPLATE template0 '
                "ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
            )
        target = url.set(database=task_database_name).render_as_string(hide_password=False)
    os.environ.update(DATABASE_URL=target, BIZASSIST_TEST_DATABASE_URL=target,
        BIZASSIST_TESTING="1", JWT_SECRET="test-only-secret-please-change-0123456789abcdef",
        GROQ_API_KEY="mock", CLOUD_URL="http://127.0.0.1:9", CLOUD_API_URL="http://127.0.0.1:9")
    import dotenv
    dotenv.load_dotenv = lambda *_a, **_kw: False
    os.chdir(root / "backend")
    sys.path.insert(0, str(root / "backend"))
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from database.db import engine, Base
    import database.models
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        inspector = inspect(engine)
        missing = {}
        for name, table in Base.metadata.tables.items():
            if not inspector.has_table(name):
                missing[name] = ["ENTIRE_TABLE"]
            else:
                present = {c["name"] for c in inspector.get_columns(name)}
                columns = sorted(c.name for c in table.columns if c.name not in present)
                if columns:
                    missing[name] = columns
        if missing:
            raise RuntimeError("Migrated schema is missing model fields: " + str(missing))
        print(f"Complete {args.dialect} migration chain, retry and metadata parity passed ({len(Base.metadata.tables)} tables)")
        return 0
    finally:
        engine.dispose()
        if admin is not None:
            # The identifier is generated above and always names our own test DB.
            import re
            if not re.fullmatch(r"schema_chain_test_[0-9a-f]{12}", task_database_name or ""):
                raise RuntimeError("Refusing cleanup of an unexpected database name")
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE "{task_database_name}" WITH (FORCE)')
            admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
