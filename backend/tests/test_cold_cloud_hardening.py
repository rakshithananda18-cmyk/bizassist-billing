"""Busy cloud responses must preserve credentials and respect server backoff."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")
import pytest
from datetime import datetime, timedelta, timezone


@pytest.mark.parametrize("value,expected", [(None,30),("",30),("0",0),("120",120),("86400",300),("-5",0),("abc",30)])
def test_retry_after(value, expected):
    from services.sync_worker import _parse_retry_after
    assert _parse_retry_after(value, 1000) == expected


def test_refresh_starts_twelve_hours_early_and_retries(monkeypatch, tmp_path):
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    from services import sync_worker as w
    now = w.utc_now()
    w._REFRESH_BACKOFF.clear()
    w._REFRESH_FAILURES.clear()
    monkeypatch.setattr(w, "_get_cloud_token", lambda bid: "kept")
    monkeypatch.setattr(w, "_token_expiry", lambda token: now + timedelta(hours=11))
    monkeypatch.setattr(w, "utc_now", lambda: now)
    def unavailable(*args, **kwargs):
        assert kwargs['timeout'] == 45.0
        raise w.httpx.ReadTimeout("starting")
    monkeypatch.setattr(w.httpx, "post", unavailable)
    assert w.ensure_fresh_cloud_token(9123) == "kept"
    assert w._REFRESH_BACKOFF[9123] == now + timedelta(seconds=60)


def test_chunk_id_is_stable_and_payload_bound():
    from services.sync_worker import _chunk_request_id
    assert _chunk_request_id(1,[2,1],{'a':1}) == _chunk_request_id(1,[1,2],{'a':1})
    assert _chunk_request_id(1,[1,2],{'a':1}) != _chunk_request_id(1,[1,2],{'a':2})


@pytest.mark.parametrize("outcome,expected", [("timeout","waking"),("connect","offline"),("html","busy"),(200,"online"),(429,"busy"),(500,"busy"),(502,"busy"),(503,"busy"),(504,"busy")])
def test_cloud_probe_state_and_retry_after(outcome,expected,monkeypatch,tmp_path):
    from services import sync_worker as w
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import httpx
    bid = 99271
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    # This unit supplies a synthetic session; committed consent is exercised
    # separately by the real-database Local-only boundary tests.
    monkeypatch.setattr(w, "_hybrid_sync_enabled", lambda requested: requested == bid)
    w._CLOUD_STATE.clear(); w._OFFLINE_STATE.clear(); w._PLAN_BLOCKED.clear()
    monkeypatch.setattr(w,"_heal_unqueued_rows",lambda *args:None)
    monkeypatch.setattr(w,"_repair_stuck_child_payloads",lambda *args:None)
    monkeypatch.setattr(w,"_get_cloud_token",lambda *args:None)
    from services import auth
    monkeypatch.setattr(auth,"subscription_enforced",lambda:False)
    calls = []
    def health(*args,**kwargs):
        calls.append(kwargs)
        if outcome == "timeout": raise httpx.ReadTimeout("starting")
        if outcome == "connect": raise httpx.ConnectError("offline")
        if outcome == "html": return httpx.Response(200,text="<html>starting</html>")
        return httpx.Response(outcome,json={"status":"ok"} if outcome==200 else {},headers={"Retry-After":"120"})
    monkeypatch.setattr(w.httpx,"get",health)
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    w._sync_business_impl(db,SimpleNamespace(id=bid, public_id="BA-PROBE"))
    assert w.get_cloud_state(bid)["state"] == expected
    assert calls[0]["timeout"].read == 45
    if expected in ("busy","waking"):
        db.add.assert_not_called()
    if expected == "busy":
        calls.clear()
        w._sync_business_impl(db,SimpleNamespace(id=bid))
        assert not calls
    w._CLOUD_STATE.clear(); w._OFFLINE_STATE.clear(); w._PULL_AUTH_BLOCKED.pop(bid,None)


@pytest.mark.anyio
@pytest.mark.parametrize("method",["GET","POST","PUT","PATCH","DELETE"])
@pytest.mark.parametrize("status",[401,429,500,502,503,504])
async def test_b2b_reads_fallback_writes_keep_actionable_error(method,status,monkeypatch):
    from routes import b2b_proxy as p
    from services import sync_worker as w
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    import httpx
    monkeypatch.setattr(p,"_is_local_backend",lambda:True)
    monkeypatch.setattr(p,"_proxy_allowed",lambda:True)
    monkeypatch.setattr(p,"_business_id_from",lambda req:1)
    monkeypatch.setattr(w,"_get_cloud_token",lambda bid:"cloud")
    monkeypatch.setattr(w,"_invalidate_cloud_token",lambda bid, **kwargs:None)
    class Client:
        def __init__(self,**kwargs):
            assert kwargs["timeout"] == (p._TIMEOUT if method=="GET" else p._WRITE_TIMEOUT)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def request(self,*args,**kwargs):
            return httpx.Response(status,text="starting",headers={"Retry-After":"120"})
    monkeypatch.setattr(p.httpx,"AsyncClient",Client)
    async def receive(): return {"type":"http.request","body":b"","more_body":False}
    req = Request({"type":"http","method":method,"path":"/connections","query_string":b"","headers":[]},receive)
    async def local(req): return JSONResponse({"mirror":True})
    response = await p.b2b_cloud_proxy(req,local)
    if method == "GET":
        assert response.status_code == 200 and b"mirror" in response.body
    elif status == 401:
        assert response.status_code == 424 and b"cloud_sign_in_required" in response.body
    else:
        assert response.status_code == status and response.headers["retry-after"] == "120"
