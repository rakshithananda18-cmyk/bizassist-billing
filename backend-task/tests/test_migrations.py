"""The ft_* migration matches the models, and never claims billing's tables."""
import logging

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.billing_models import BillingBase
from app.db import Base, engine
from app.migration_scope import VERSION_TABLE, include_object
from app.main import add_missing_mirror_columns, run_migrations
from tests.conftest import EXTERNAL_BILLING_SCHEMA


def test_migrated_schema_matches_models(client):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": include_object,
                                                     "version_table": VERSION_TABLE})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_own_version_table_and_billing_tables_untouched(client):
    tables = set(inspect(engine).get_table_names())
    assert VERSION_TABLE in tables
    if not EXTERNAL_BILLING_SCHEMA:
        assert "alembic_version" not in tables  # billing's chain is not ours to create
        mirrored = set(BillingBase.metadata.tables)  # billing tables a dev/test DB copies
        assert all(t.startswith("ft_") or t in mirrored for t in tables)


def test_include_object_ignores_billing_tables():
    assert include_object(None, "users", "table", True, None) is False
    assert include_object(None, "invoices", "table", True, None) is False
    assert include_object(None, "ft_tasks", "table", False, None) is True


def test_newer_database_is_left_alone_instead_of_failing_start(tmp_path, caplog):
    """A rollback (or a dev folder switched to an older branch) meets a database
    that a newer build migrated: start, warn, and change nothing."""
    eng = create_engine(f"sqlite:///{tmp_path / 'ahead.db'}")
    with eng.begin() as conn:
        conn.execute(text(f"CREATE TABLE {VERSION_TABLE} (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text(f"INSERT INTO {VERSION_TABLE} VALUES ('9999_from_a_newer_build')"))
    try:
        with caplog.at_level(logging.WARNING, logger="task"):
            assert run_migrations(bind=eng) is False
        assert "9999_from_a_newer_build" in caplog.text and "skipping migrations" in caplog.text
        assert inspect(eng).get_table_names() == [VERSION_TABLE]
    finally:
        eng.dispose()


def test_fresh_database_still_migrates_to_head(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        assert run_migrations(bind=eng) is True
        assert {t for t in inspect(eng).get_table_names() if t.startswith("ft_")} == set(Base.metadata.tables) | {VERSION_TABLE}
        assert run_migrations(bind=eng) is True  # at head already: a no-op, not a skip
    finally:
        eng.dispose()


def test_old_local_mirror_gets_new_columns(tmp_path):
    """A dev database made before users.settings existed: start-up adds the
    column instead of every sign-in failing with "no such column"."""
    eng = create_engine(f"sqlite:///{tmp_path / 'old_dev.db'}")
    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, password VARCHAR, "
                              "business_name VARCHAR, role VARCHAR, parent_business_id INTEGER, public_id VARCHAR, "
                              "phone VARCHAR, token_version INTEGER NOT NULL DEFAULT 0, last_login DATETIME, "
                              "created_at DATETIME, updated_at DATETIME)"))
            conn.execute(text("INSERT INTO users (id, username, token_version) VALUES (1, 'old_owner', 0)"))
        assert add_missing_mirror_columns(bind=eng) == ["users.settings"]
        assert "settings" in {c["name"] for c in inspect(eng).get_columns("users")}
        with eng.connect() as conn:  # existing rows kept, new column empty
            assert conn.execute(text("SELECT username, settings FROM users")).one() == ("old_owner", None)
        assert add_missing_mirror_columns(bind=eng) == []  # second start: nothing to do
    finally:
        eng.dispose()
