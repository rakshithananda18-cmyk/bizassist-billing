"""
tests/test_db_guard_fail_closed.py
==================================
T6.1 (MASTER_REVIEW §9.A): the fail-closed test-isolation guard in
`database/db.py` must REFUSE to build an engine when a test context is
detected but DATABASE_URL points at a non-test database. This is the
regression net for the July-2026 fixture-pollution incident (test cashiers
written into the real dev DB and the cloud tenant).

Each case runs in a SUBPROCESS so we can control DATABASE_URL and the
test-context signals seen at import time — the guard fires on module import,
which has already happened (safely) in this pytest process.
"""
import os
import subprocess
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")


def _import_db(database_url, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["DATABASE_URL"] = database_url
    env["BIZASSIST_TESTING"] = "1"          # explicit test-context signal
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", "import database.db; print('ENGINE_BUILT')"],
        capture_output=True, text=True, cwd=BACKEND, env=env, timeout=60,
    )


def test_guard_trips_on_prod_sqlite_url():
    r = _import_db("sqlite:///./bizassist.db")
    assert r.returncode != 0, "guard must refuse a non-test sqlite DB in a test context"
    assert "Refusing to run tests against a non-test database" in (r.stderr + r.stdout)
    assert "ENGINE_BUILT" not in r.stdout


def test_guard_trips_on_prod_like_postgres_url():
    # Prod-like URL (as a CI job would export). The guard raises BEFORE any
    # connection attempt, so no Postgres needs to be running.
    r = _import_db("postgresql://user:pass@db.example.com:5432/bizassist")
    assert r.returncode != 0, "guard must refuse a prod-like Postgres URL in a test context"
    assert "Refusing to run tests against a non-test database" in (r.stderr + r.stdout)


def test_guard_allows_test_db_url():
    r = _import_db("sqlite:///./test_bizassist.db")
    assert r.returncode == 0, r.stderr
    assert "ENGINE_BUILT" in r.stdout
