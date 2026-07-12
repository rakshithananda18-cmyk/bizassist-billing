"""
tests/conftest.py
=================
Pin the routing mode for the test suite BEFORE the app imports (and before
db.py / main_groq.py call load_dotenv, which uses override=False and therefore
won't clobber an already-set value).

Why: most tests assert the deterministic legacy tiers — exact Groq-call counts
and TokenUsage row counts. A local `.env` with LLM_ROUTER=on would add an extra
8B classify call per query and break those assertions. Router-specific tests
(e.g. test_router_switch.py) call set_mode() at runtime, which takes precedence
over this env default, so they are unaffected.
"""
import os
import sys

_orig_remove = os.remove
_orig_unlink = os.unlink

def secure_remove(path):
    path_str = str(path)
    if "test_bizassist" in path_str:
        try:
            from database.db import engine
            engine.dispose()
        except Exception:
            pass
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = path_str + suffix
            try:
                _orig_remove(p)
            except Exception:
                pass
    else:
        _orig_remove(path)

def secure_unlink(path):
    path_str = str(path)
    if "test_bizassist" in path_str:
        secure_remove(path)
    else:
        _orig_unlink(path)

os.remove = secure_remove
os.unlink = secure_unlink

# Force the test suite to run against the test database (test_bizassist.db)
# so it never writes to or pollutes the development database (bizassist.db).
# Since load_dotenv(override=False) is called by db.py, pre-setting it here
# guarantees it won't be overridden by the .env file.
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
# Explicit signal for database/db.py's fail-closed guard: even on an odd entry
# path, this marks the process as a test run so the DB layer refuses any
# non-test DATABASE_URL.
os.environ["BIZASSIST_TESTING"] = "1"

# Clean up test database file immediately on module load to prevent cross-run pollution
_root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_test_db = os.path.join(_root_dir, "backend", "test_bizassist.db")
try:
    if os.path.exists(_test_db):
        os.remove(_test_db)
except Exception:
    pass

# Deterministic default for the whole suite. load_dotenv(override=False) later
# will NOT overwrite this, so tests ignore whatever the dev's .env says.
os.environ["LLM_ROUTER"] = "off"

# The admin API is fail-closed (404) unless explicitly enabled — enable it for
# the suite so /admin/* tests exercise the real auth logic. Individual tests
# flip it to "0" to assert the closed behaviour.
os.environ["ADMIN_API_ENABLED"] = "1"
# Keep the paywall dormant for the suite (free users can call /ask etc.);
# subscription tests flip it on explicitly.
os.environ.setdefault("SUBSCRIPTION_ENFORCED", "0")

import pytest


def pytest_configure(config):
    """Fail the whole session immediately if the resolved DB isn't a test DB.
    Backstop to the db.py guard: gives a clear, early error instead of letting
    fixtures write into real data (the July 2026 c_/cash_ pollution incident)."""
    db_url = os.environ.get("DATABASE_URL", "")
    if "test" not in db_url.lower():
        raise pytest.UsageError(
            f"Test suite resolved a non-test DATABASE_URL ({db_url!r}). "
            "Refusing to run so fixtures cannot pollute real data. Unset any "
            "exported DATABASE_URL before running the tests."
        )


def _clear_sqlite_sidecars():
    """Delete stale -wal/-shm sidecars of the test DB. On Windows a leftover
    WAL/SHM (or a handle an AV/indexer still holds on it) surfaces as
    'sqlite3.OperationalError: disk I/O error' during DDL — the flake seen in
    test_phase4_sync setup. Uses the ORIGINAL os.remove (bypasses the guard
    above, which would recurse)."""
    for suffix in ("-wal", "-shm"):
        try:
            _orig_remove(_test_db + suffix)
        except OSError:
            pass


@pytest.fixture(scope="module", autouse=True)
def setup_and_dispose_db():
    import time
    from database.db import engine
    from database.models import Base
    from database.migration import run_migrations_and_seed

    last_err = None
    for attempt in range(3):
        try:
            engine.dispose()
            if attempt > 0:
                # retry path: clear sidecars; on the final attempt drop the DB
                # file itself and let create_all rebuild from scratch.
                _clear_sqlite_sidecars()
                if attempt == 2:
                    try:
                        _orig_remove(_test_db)
                    except OSError:
                        pass
                time.sleep(0.7)
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            run_migrations_and_seed()
            last_err = None
            break
        except Exception as e:  # OperationalError('disk I/O error') et al.
            last_err = e
            import traceback
            traceback.print_exc()
            engine.dispose()
    if last_err is not None:
        raise last_err
    yield
    try:
        from database.db import engine
        engine.dispose()
    except Exception:
        pass


import time
import json
from datetime import datetime

# Store results in a session-scoped dictionary
test_results = {
    "summary": {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "duration": 0.0,
        "timestamp": "",
        "status": "running"
    },
    "tests": []
}

_session_start_time = 0.0

def _write_results():
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    results_path = os.path.join(root_dir, "test_results.json")
    try:
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(test_results, f, indent=2)
    except Exception:
        pass

def pytest_sessionstart(session):
    global _session_start_time
    _session_start_time = time.time()
    test_results["summary"]["timestamp"] = datetime.now().isoformat()
    test_results["summary"]["status"] = "running"
    test_results["tests"] = []
    _write_results()

def pytest_collection_finish(session):
    test_results["summary"]["total"] = len(session.items)
    _write_results()

def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.failed):
        duration = report.duration
        outcome = report.outcome
        
        if report.failed:
            status = "failed"
        elif report.skipped:
            status = "skipped"
        else:
            status = "passed"
            
        test_info = {
            "nodeid": report.nodeid,
            "name": report.location[2] if report.location else report.nodeid,
            "file": report.location[0] if report.location else "",
            "line": report.location[1] if report.location else 0,
            "outcome": status,
            "duration": duration,
            "traceback": None,
            "longrepr": None
        }
        
        if report.failed:
            test_info["traceback"] = str(report.longrepr)
            test_info["longrepr"] = report.longreprtext if hasattr(report, "longreprtext") else str(report.longrepr)
            
        test_results["tests"].append(test_info)
        
        passed = sum(1 for t in test_results["tests"] if t["outcome"] == "passed")
        failed = sum(1 for t in test_results["tests"] if t["outcome"] == "failed")
        skipped = sum(1 for t in test_results["tests"] if t["outcome"] == "skipped")
        
        test_results["summary"]["passed"] = passed
        test_results["summary"]["failed"] = failed
        test_results["summary"]["skipped"] = skipped
        test_results["summary"]["duration"] = time.time() - _session_start_time
        _write_results()

def pytest_sessionfinish(session, exitstatus):
    duration = time.time() - _session_start_time
    test_results["summary"]["duration"] = duration
    test_results["summary"]["status"] = "completed"
    
    passed = sum(1 for t in test_results["tests"] if t["outcome"] == "passed")
    failed = sum(1 for t in test_results["tests"] if t["outcome"] == "failed")
    skipped = sum(1 for t in test_results["tests"] if t["outcome"] == "skipped")
    
    test_results["summary"]["total"] = len(test_results["tests"])
    test_results["summary"]["passed"] = passed
    test_results["summary"]["failed"] = failed
    test_results["summary"]["skipped"] = skipped
    
    _write_results()

