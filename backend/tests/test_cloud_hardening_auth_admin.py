"""Regression coverage for purpose-bound sessions and durable admin state."""
import asyncio
import os
import uuid
from datetime import timedelta

os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

import pytest
from sqlalchemy import event
from fastapi import HTTPException
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal, engine
from database.models import User, Invoice, ClientLogArchive, PlatformSetting, Base
from services import auth, admin_service, router_mode
from services.dates import utc_now


def _owner(db, role="enterprise"):
    user = User(username="hardening_" + uuid.uuid4().hex, password="unusable",
                public_id=uuid.uuid4().hex, role=role, business_name="Hardening Store")
    db.add(user)
    db.commit()
    return user


def _headers(user):
    token = auth.create_access_token({"id": user.id, "user_id": user.id,
                                     "username": user.username, "role": user.role})
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("purpose,ttl", [(None,30),("field_team",90),("ai_dashboard",60),("admin_console",60)])
def test_ticket_audience_lifetime_and_claims(purpose, ttl):
    import base64
    import json
    token = auth.create_sse_ticket({"id":1}, expires_in_seconds=ttl, aud=purpose)
    expires, encoded, _ = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded)%4)))
    assert int(expires)-claims["iat"] == ttl
    assert claims.get("aud") == purpose


def test_refresh_preserves_parent_session():
    from routes.auth import _session_claims
    with SessionLocal() as db:
        owner = _owner(db)
        claims = _session_claims(owner, sid="dashboard", psid="billing")
        token = auth.create_access_token(claims)
        response = TestClient(app).post("/auth/refresh", headers={"Authorization":"Bearer "+token})
        assert response.status_code == 200, response.text
        refreshed = auth.decode_access_token(response.json()["token"])
        assert (refreshed["sid"], refreshed["psid"]) == ("dashboard", "billing")


@pytest.mark.parametrize("role,status", [("enterprise",403),("cashier",403),("admin",200)])
def test_admin_session_confirms_role_in_database(role, status, monkeypatch):
    monkeypatch.setenv("ADMIN_API_ENABLED","1")
    with SessionLocal() as db:
        user = _owner(db, role)
        response = TestClient(app).get("/admin/session", headers=_headers(user))
        assert response.status_code == status


def test_control_state_excluded_from_sync():
    from database.sync_map import MODEL_MAP
    names = {"spent_tickets","revoked_sessions","platform_settings","client_log_archives",
             "schema_state","scheduled_job_runs","discovery_registrations"}
    assert names <= set(Base.metadata.tables)
    assert not names.intersection(MODEL_MAP)


def test_private_control_state_does_not_write_business_audit():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models import SpentTicket, RevokedSession
    from database.runtime_state import SchemaState, ScheduledJobRun, DiscoveryRegistration
    models = (SpentTicket,RevokedSession,PlatformSetting,ClientLogArchive,SchemaState,ScheduledJobRun,DiscoveryRegistration)
    isolated = create_engine("sqlite://")
    # No tenant audit table exists here. An accidental generic-audit write
    # fails this test and would leak private values in a real business database.
    Base.metadata.create_all(isolated,tables=[model.__table__ for model in models])
    now = utc_now()
    with Session(isolated) as db:
        rows = [SpentTicket(digest="a"*64,expires_at=now),RevokedSession(sid="secret-session",expires_at=now),
                PlatformSetting(key="router",value="on"),ClientLogArchive(business_id=1,kind="feedback",filename="log.gz",content=b"private log data",size=16),
                SchemaState(key="runtime",signature="b"*64,applied_at=now),ScheduledJobRun(job="summary",period="2026-11-07",status="running"),
                DiscoveryRegistration(biz_id="biz-1",ip="192.168.1.10",port=8001,url="http://192.168.1.10:8001",registered_at=1,last_seen=1)]
        db.add_all(rows)
        db.commit()
        for row in rows:
            db.delete(row)
        db.commit()
    isolated.dispose()


def test_router_mode_survives_process_cache_clear(monkeypatch):
    router_mode.reset_mode()
    try:
        assert router_mode.set_mode("new") == "on"
        monkeypatch.setattr(router_mode,"_explicit",None)
        monkeypatch.setattr(router_mode,"_cached_at",0.0)
        assert router_mode.get_mode() == "on"
    finally:
        router_mode.reset_mode()


def test_archive_survives_without_file_and_retention_is_bounded(monkeypatch):
    from services import client_log_archives as archives
    monkeypatch.setattr(archives,"_ARCHIVES_PER_BUSINESS",2)
    with SessionLocal() as db:
        owner = _owner(db)
        for i in range(4):
            archives.store_archive(db,business_id=owner.id,filename=f"log-{i}.tar.gz",content=f"archive-{i}".encode())
            db.commit()
        rows = db.query(ClientLogArchive).filter(ClientLogArchive.business_id==owner.id).order_by(ClientLogArchive.id).all()
        assert [r.content for r in rows] == [b"archive-2",b"archive-3"]
        admin = _owner(db,"admin")
        response = TestClient(app).get(f"/admin/business-logs/{owner.id}",headers=_headers(admin))
        assert response.status_code == 200, response.text
        assert response.content == b"archive-3"


def test_fleet_query_counts_do_not_grow_with_business_count():
    from services.admin_service import list_businesses, sync_doctor, all_usage_stats
    with SessionLocal() as db:
        _owner(db)
        def counts():
            out = []
            for function in (list_businesses,sync_doctor,all_usage_stats):
                statements = []
                def before(*args):
                    statements.append(args[2])
                event.listen(engine,"before_cursor_execute",before)
                try:
                    function(db)
                finally:
                    event.remove(engine,"before_cursor_execute",before)
                out.append(len(statements))
            return out
        before = counts()
        for _ in range(4):
            _owner(db)
        assert counts() == before


def test_business_details_paginate_and_reject_bad_sections():
    with SessionLocal() as db:
        owner = _owner(db)
        for i in range(3):
            db.add(Invoice(business_id=owner.id,invoice_id=f"page-{i}",amount=i))
        db.commit()
        first = admin_service.business_details(owner.id,db,section="invoices",limit=2)
        second = admin_service.business_details(owner.id,db,section="invoices",limit=2,offset=2)
        assert len(first["invoices"]) == 2 and first["has_more"]
        assert len(second["invoices"]) == 1 and not second["has_more"]
        assert not set(r["id"] for r in first["invoices"]).intersection(r["id"] for r in second["invoices"])
        with pytest.raises(HTTPException) as exc:
            admin_service.business_details(owner.id,db,section="unknown")
        assert exc.value.status_code == 422


def test_unavailable_process_metrics_are_null(monkeypatch):
    from services import admin_infrastructure as metrics
    monkeypatch.setattr(metrics,"_cache",None)
    monkeypatch.setattr(metrics,"_PROCESS",None)
    monkeypatch.setattr(metrics,"_probe",lambda url:{"url":url,"status":"ONLINE","code":200,"latency_ms":1,"edge_pop":None,"error":None})
    monkeypatch.delenv("HF_STANDBY_URL",raising=False)
    monkeypatch.delenv("CLOUD_RUN_REGION",raising=False)
    with SessionLocal() as db:
        data = metrics.metrics(db)
    assert data["cloud_run"]["cpu_percent"] is None
    assert data["cloud_run"]["region"] is None
    assert "cloud_run.cpu_percent" in data["unavailable"]
    assert all(value is None for value in data["supabase"]["table_counts"].values())


def test_instance_views_name_cloud_logging(monkeypatch):
    monkeypatch.setenv("K_SERVICE","staterbill-api")
    monkeypatch.setenv("K_REVISION","release-1")
    result = admin_service.server_log_tail()
    assert 'service_name="staterbill-api"' in result["cloud_logging_filter"]
    assert result["instance"]["revision"] == "release-1"
    assert result["instance"]["boot_id"]


@pytest.mark.anyio
async def test_realtime_replays_or_reports_gap(monkeypatch):
    from services.realtime import RealtimeManager
    monkeypatch.setenv("SSE_REPLAY_BUFFER","4")
    hub = RealtimeManager()
    first = {"type":"sync.trigger","entity":"products","payload":{"id":1}}
    await hub.broadcast(1,first)
    cursor = hub.event_id(1,first)
    later = [{"type":"sync.trigger","entity":"products","payload":{"id":i}} for i in range(2,5)]
    for item in later:
        await hub.broadcast(1,item)
    queue,replay,status = hub.subscribe_from(1,cursor)
    assert status == "complete" and replay == later
    hub.unsubscribe(1,queue)
    for _ in range(2):
        await hub.broadcast(1,{"type":"sync.trigger","entity":"invoices"})
    queue,replay,status = hub.subscribe_from(1,cursor)
    assert status == "gap" and replay == []
    hub.unsubscribe(1,queue)
    restarted = RealtimeManager()
    queue,replay,status = restarted.subscribe_from(1,cursor)
    assert status == "gap"
    restarted.unsubscribe(1,queue)


@pytest.mark.anyio
async def test_coalesced_live_trigger_keeps_id_after_replay_buffer_rolls_over(monkeypatch):
    from services.realtime import RealtimeManager
    monkeypatch.setenv("SSE_REPLAY_BUFFER","4")
    hub = RealtimeManager()
    queue = hub.subscribe(10)
    first = {"type":"sync.trigger","entity":"products"}
    await hub.broadcast(10,first)
    cursor = hub.event_id(10,first)
    for _ in range(8):
        await hub.broadcast(10,{"type":"sync.trigger","entity":"products"})
    assert queue.qsize() == 1
    event = await queue.get()
    assert event is first and hub.event_id(10,event,queue) == cursor
    hub.unsubscribe(10,queue)
    assert queue not in hub._queue_sequences
