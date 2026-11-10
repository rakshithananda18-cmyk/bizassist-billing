import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def runner(monkeypatch):
    from database.db import Base
    from database.runtime_state import ScheduledJobRun
    from services import cron_runner
    engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ScheduledJobRun.__table__])
    monkeypatch.setattr(cron_runner, "SessionLocal", sessionmaker(bind=engine))
    return cron_runner


def test_cron_retries_resume_and_duplicate_delivery_is_noop(runner, monkeypatch):
    seen = []
    def job(after_business_id=None, deadline=None):
        values = [i for i in range(1,6) if i > (after_business_id or 0)]
        for i in values:
            seen.append(i)
            runner.checkpoint.get()(i)
            if i == 2:
                return i
        return None
    monkeypatch.setattr(runner, "JOBS", {"fake":(job,"daily")})
    assert runner.run("fake","2026-11-07") == "partial"
    assert runner.run("fake","2026-11-07") == "done"
    assert runner.run("fake","2026-11-07") == "already_ran"
    assert seen == [1,2,3,4,5]


def test_cron_secret_is_required_and_route_is_hidden(runner, monkeypatch):
    from routes.internal_cron import router
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    monkeypatch.delenv("BILLING_CRON_SECRET",raising=False)
    assert client.post("/internal/cron/fake").status_code == 404
    monkeypatch.setenv("BILLING_CRON_SECRET","private-test-value")
    assert client.post("/internal/cron/fake",headers={"X-Cron-Secret":"wrong"}).status_code == 403
    monkeypatch.setattr(runner,"JOBS",{"fake":(lambda **kwargs:None,"daily")})
    assert client.post("/internal/cron/fake",headers={"X-Cron-Secret":"private-test-value"}).json()["status"] == "done"
    assert "/internal/cron/{job}" not in app.openapi()["paths"]


def test_period_uses_ist_midnight_and_iso_week(runner):
    assert runner.period_for("daily_summary",datetime(2026,11,7,18,29,tzinfo=timezone.utc)) == "2026-11-07"
    assert runner.period_for("daily_summary",datetime(2026,11,7,18,31,tzinfo=timezone.utc)) == "2026-11-08"
    assert runner.period_for("memory_distillation",datetime(2027,1,1,tzinfo=timezone.utc)) == "2026-W53"


def test_cloud_scheduler_does_not_start_local_jobs(monkeypatch):
    from services import scheduler
    monkeypatch.setenv("K_SERVICE","staterbill-api")
    monkeypatch.setattr(scheduler,"BackgroundScheduler",lambda **kwargs:pytest.fail("cloud must not start APScheduler"))
    scheduler.start_scheduler()


def test_progress_makes_bounded_progress_and_resumes(monkeypatch):
    from services import alert_jobs
    monkeypatch.setattr(alert_jobs.time,"monotonic",lambda:100)
    batch = alert_jobs._BusinessProgress([1,2,3,4], None, 99)
    assert list(batch) == [1]
    assert batch.cursor == 1
    rest = alert_jobs._BusinessProgress([1,2,3,4], batch.cursor, None)
    assert list(rest) == [2,3,4]
    assert rest.cursor is None
