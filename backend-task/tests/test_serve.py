"""Deployment entry points: serve.py, "/" for the host's probe, and the
scheduled GPS purge that replaces the in-process loop on Cloud Run."""
from datetime import timedelta
from types import SimpleNamespace

from app import config
from app.db import SessionLocal, utc_now
from app.models import FieldLocationPing

import serve

SECRET = "cron-secret-0123456789abcdef"


def test_serve_starts_the_same_app():
    assert serve.APP == "app.main:app"


def test_allowed_origins_match_what_browsers_send():
    # Pasted from the address bar with a trailing slash, the Vercel URL never
    # matched the browser's Origin header and CORS refused the app (2026-10-23).
    assert config.parse_origins("https://bizassist-task.vercel.app/, http://localhost:5176 ,") == [
        "https://bizassist-task.vercel.app", "http://localhost:5176"]


def test_root_and_health_answer_for_the_hosts_probe(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "bizassist-task", "ok": True, "health": "/api/health"}
    health = client.get("/api/health").json()
    assert health["ok"] is True and health["db"] in ("sqlite", "postgresql")
    assert health["pro_required"] is config.REQUIRE_PRO
    assert health["billing_mirror"] is config.CREATE_BILLING_MIRROR
    assert health["cloud_only"] is True


def test_health_fails_closed_without_exposing_database_errors(client, monkeypatch):
    from app import main

    def unavailable():
        raise RuntimeError("private connection details must not reach the client")

    monkeypatch.setattr(main, "engine", SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"), connect=unavailable,
    ))
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["reason"] == "database_unavailable"
    assert "private connection details" not in response.text


def _ping(business_id, staff_id, age_days):
    db = SessionLocal()
    try:
        p = FieldLocationPing(business_id=business_id, staff_id=staff_id, lat=12.97, lng=77.59,
                              recorded_at=utc_now() - timedelta(days=age_days))
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


def _exists(ping_id):
    db = SessionLocal()
    try:
        return db.get(FieldLocationPing, ping_id) is not None
    finally:
        db.close()


def test_purge_endpoint_does_not_exist_without_a_secret(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "")
    assert client.post("/api/internal/purge-pings", headers={"X-Cron-Secret": "x"}).status_code == 404


def test_purge_endpoint_refuses_a_wrong_or_missing_secret(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", SECRET)
    assert client.post("/api/internal/purge-pings").status_code == 403
    assert client.post("/api/internal/purge-pings", headers={"X-Cron-Secret": "wrong"}).status_code == 403


def test_scheduled_purge_drops_only_pings_past_retention(client, biz, other_biz, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", SECRET)
    s1, s2 = biz.staff(), other_biz.staff()
    old_1 = _ping(biz.business_id, s1["id"], config.PING_RETENTION_DAYS + 5)
    old_2 = _ping(other_biz.business_id, s2["id"], config.PING_RETENTION_DAYS + 1)
    recent = _ping(biz.business_id, s1["id"], 1)

    r = client.post("/api/internal/purge-pings", headers={"X-Cron-Secret": SECRET})
    assert r.status_code == 200, r.text
    assert r.json()["purged"] >= 2 and r.json()["retention_days"] == config.PING_RETENTION_DAYS
    # Both businesses purged (on Postgres, business by business under RLS).
    assert not _exists(old_1) and not _exists(old_2)
    assert _exists(recent)
