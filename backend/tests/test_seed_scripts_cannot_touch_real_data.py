"""
tests/test_seed_scripts_cannot_touch_real_data.py
=================================================
Test fixtures and real books share a machine. They must never share a database.

`database/db.py` is already fail-closed: in a test context it refuses any
DATABASE_URL without "test" in it. But it INFERS that context from
BIZASSIST_TESTING or an argv basename starting with `test_`, and a seeding
script satisfies neither — it is named `seed_…` and is run by hand. With no
DATABASE_URL exported it inherited .env's `sqlite:///./bizassist.db`.

That is not hypothetical. `seed_load_test.py` inserts its business with an
EXPLICIT id, and one run against the dev database on 2026-07-23 created
users.id = 9999. SQLite allocates MAX(id)+1 thereafter, so the next two REAL
businesses signed up as 10000 and 10001 rather than 134 and 135 — an id space
that never recovers, and load-test rows sitting beside real books.

A script that CREATES test data has to declare itself a test context, so the
existing guard applies to it too.
"""
import os
import subprocess
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SEEDERS = ["seed_load_test.py"]


def _run(script, database_url):
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    env.pop("BIZASSIST_TESTING", None)      # the script must assert this itself
    return subprocess.run(
        [sys.executable, os.path.join(BACKEND, script), "--help"],
        capture_output=True, text=True, cwd=BACKEND, env=env, timeout=120)


def test_seeders_refuse_a_non_test_database():
    for script in SEEDERS:
        r = _run(script, "sqlite:///./bizassist.db")
        assert r.returncode != 0, (
            f"{script} opened the REAL database. This is how users.id 9999 got "
            f"into the production id space.")
        assert "non-test database" in (r.stderr + r.stdout), (
            f"{script} failed for some other reason:\n{r.stderr[-500:]}")


def test_seeders_still_run_against_a_test_database():
    """The guard must not make the tool unusable — that is how guards get
    deleted. Pointed at a test DB it has to work exactly as before."""
    for script in SEEDERS:
        r = _run(script, "sqlite:///./test_bizassist.db")
        assert r.returncode == 0, (
            f"{script} refused a legitimate test database:\n{r.stderr[-500:]}")
        assert "--count" in r.stdout, "expected the script's own --help output"
