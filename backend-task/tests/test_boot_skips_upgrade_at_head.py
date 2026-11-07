"""Bug condition exploration, task 1.5 (Property 1; clause 1.5).

Expected behaviour (2.5, design.md C3 item 1): a cold start whose ft_* schema
is already at head does no migration work. `run_migrations()` compares the
database heads with `script.get_heads()` and returns True without calling
`alembic.command.upgrade`. A spy records each upgrade call and passes it on to
the real function.
"""
# Observed on the unfixed code (task 1.5, both cases fail as expected):
#   fresh SQLite database migrated to 0003_ft_task_payment, second run_migrations(bind=...)
#       -> command.upgrade(cfg, "head") called once
#   the service's own database at 0003_ft_task_payment after start-up, run_migrations()
#       -> command.upgrade(cfg, "head") called once
# Confirms root cause 5: the Field Team API calls command.upgrade on every boot.

import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app import main
from app.db import engine
from app.migration_scope import VERSION_TABLE


@pytest.fixture
def upgrade_calls(monkeypatch):
    """Install the spy on `alembic.command.upgrade` when the test asks for it."""
    calls = []

    def install():
        real = command.upgrade

        def spy(cfg, revision, *args, **kwargs):
            calls.append(revision)
            return real(cfg, revision, *args, **kwargs)

        monkeypatch.setattr(command, "upgrade", spy)
        return calls

    return install


def _heads(bind):
    cfg = Config(os.path.join(main.BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(main.BACKEND_DIR, "alembic"))
    with bind.connect() as conn:
        current = MigrationContext.configure(conn, opts={"version_table": VERSION_TABLE}).get_current_heads()
    return set(current), set(ScriptDirectory.from_config(cfg).get_heads())


def test_cold_start_at_head_does_not_upgrade(tmp_path, upgrade_calls):
    """**Validates: Requirements 1.5, 2.5** (a fresh database is migrated once, the next boot skips)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'at_head.db'}")
    try:
        assert main.run_migrations(bind=eng) is True  # first boot migrates to head
        current, heads = _heads(eng)
        assert current == heads, f"precondition: database at {current}, script heads {heads}"

        calls = upgrade_calls()
        assert main.run_migrations(bind=eng) is True  # the next cold start
        assert calls == [], f"command.upgrade was called with {calls} on a database already at {sorted(heads)}"
    finally:
        eng.dispose()


def test_service_database_at_head_does_not_upgrade(client, upgrade_calls):
    """**Validates: Requirements 1.5, 2.5** (the boot path itself: no bind, the service's own database)."""
    current, heads = _heads(engine)  # the session client's start-up already migrated it
    assert current == heads, f"precondition: database at {current}, script heads {heads}"

    calls = upgrade_calls()
    assert main.run_migrations() is True
    assert calls == [], f"command.upgrade was called with {calls} on a database already at {sorted(heads)}"


def test_one_revision_behind_upgrades_once(tmp_path, upgrade_calls):
    eng = create_engine(f"sqlite:///{tmp_path / 'behind_test.db'}")
    try:
        cfg = Config(os.path.join(main.BACKEND_DIR, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(main.BACKEND_DIR, "alembic"))
        with eng.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head-1")
        calls = upgrade_calls()
        assert main.run_migrations(bind=eng) is True
        assert calls == ["head"]
        assert _heads(eng)[0] == _heads(eng)[1]
        assert main.run_migrations(bind=eng) is True
        assert calls == ["head"]
    finally:
        eng.dispose()
