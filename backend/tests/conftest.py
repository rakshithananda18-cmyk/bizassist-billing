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

# Force the test suite to run against the test database (test_bizassist.db)
# so it never writes to or pollutes the development database (bizassist.db).
# Since load_dotenv(override=False) is called by db.py, pre-setting it here
# guarantees it won't be overridden by the .env file.
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"

# Clean up test database file immediately on module load to prevent cross-run pollution
try:
    _root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _test_db = os.path.join(_root_dir, "backend", "test_bizassist.db")
    if os.path.exists(_test_db):
        os.remove(_test_db)
except Exception:
    pass

# Deterministic default for the whole suite. load_dotenv(override=False) later
# will NOT overwrite this, so tests ignore whatever the dev's .env says.
os.environ["LLM_ROUTER"] = "off"

import pytest

@pytest.fixture(scope="module", autouse=True)
def setup_and_dispose_db():
    try:
        from database.db import engine
        from database.models import Base
        from database.migration import run_migrations_and_seed
        engine.dispose()
        Base.metadata.create_all(bind=engine)
        run_migrations_and_seed()
    except Exception:
        pass
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

