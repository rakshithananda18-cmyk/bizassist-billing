"""A restored local primary key must never select another business's cloud JWT.

Only disposable SQLite files, synthetic cloud keys and HTTP doubles are used.
The actual getter, refresh, worker and consumer paths remain in place.
"""
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import db as database
from database.models import Base, Customer, SyncQueue, User
from routes import b2b_proxy
from services import log_uploader, sync_worker as worker
from services.dates import utc_now


BID = 7
PUBLIC_ID = "BA-SYNTHETIC-B"


def cloud_token(*, expires_in=timedelta(hours=24), **changes):
    claims = {"id": 42, "user_id": 42, "public_id": PUBLIC_ID,
              "role": "enterprise", "exp": utc_now() + expires_in}
    claims.update(changes)
    return jwt.encode(claims, "synthetic-cloud-only-key-not-shared-with-local", algorithm="HS256")


@pytest.fixture
def device(tmp_path, monkeypatch):
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    local_engine = create_engine(f"sqlite:///{tmp_path / 'credential_binding_test.db'}")
    Base.metadata.create_all(local_engine)
    sessions = sessionmaker(bind=local_engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(database, "engine", local_engine)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "engine", local_engine)
    monkeypatch.setattr(worker, "_TOKEN_FILE", tmp_path / "cloud_sync_tokens.json")
    monkeypatch.setattr(worker, "_TOKEN_STORE_LAST_STATE", None)
    monkeypatch.setattr(worker, "_heal_unqueued_rows", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_repair_stuck_child_payloads", lambda *a, **k: None)
    disabled = database.sync_disabled_var.set(True)
    with sessions() as db:
        db.add(User(id=BID, username="synthetic-binding-owner", password="unused", role="enterprise",
                    public_id=PUBLIC_ID, settings=json.dumps({"general": {
                        "hosting_mode": "hybrid", "diagnostic_upload_enabled": True},
                        "subscription": {"plan": "pro", "status": "active"}})))
        db.commit()
    for state in (worker._CLOUD_STATE, worker._REFRESH_BACKOFF, worker._REFRESH_FAILURES,
                  worker._PULL_AUTH_BLOCKED, worker._PLAN_BLOCKED, worker._LAST_PULL):
        state.pop(BID, None)
    yield SimpleNamespace(sessions=sessions, token_path=worker._TOKEN_FILE, root=tmp_path)
    database.sync_disabled_var.reset(disabled)
    local_engine.dispose()
    for state in (worker._CLOUD_STATE, worker._REFRESH_BACKOFF, worker._REFRESH_FAILURES,
                  worker._PULL_AUTH_BLOCKED, worker._PLAN_BLOCKED, worker._LAST_PULL):
        state.pop(BID, None)


def change_owner(device, **changes):
    with device.sessions() as db:
        owner = db.get(User, BID)
        for key, value in changes.items():
            setattr(owner, key, value)
        db.commit()


def test_numeric_id_reuse_rejects_previous_business_credential_without_deleting_it(device):
    previous = cloud_token(public_id="BA-SYNTHETIC-A")
    worker.store_cloud_token(BID, previous)
    before = device.token_path.read_bytes()
    assert worker._get_cloud_token(BID) is None
    assert device.token_path.read_bytes() == before
    assert worker._load_token_map()[str(BID)] == previous


def test_cloud_numeric_ids_can_differ_from_the_local_owner_id(device):
    token = cloud_token(id=9021, user_id=9021)
    worker.store_cloud_token(BID, token)
    assert worker._get_cloud_token(BID) == token


@pytest.mark.parametrize("claims", [
    {"public_id": None}, {"public_id": ""}, {"public_id": {"value": PUBLIC_ID}},
    {"role": None}, {"role": "cashier"}, {"role": "admin", "user_id": 43},
    {"parent_business_id": 42}, {"id": None}, {"user_id": None}, {"id": True, "user_id": True},
])
def test_missing_malformed_or_staff_identity_is_not_an_owner_credential(device, claims):
    token = cloud_token(**claims)
    worker.store_cloud_token(BID, token)
    assert worker._get_cloud_token(BID) is None
    assert worker._load_token_map()[str(BID)] == token


@pytest.mark.parametrize("token", ["", "not-a-jwt", "header.invalid.signature"])
def test_unreadable_jwt_is_rejected_without_losing_the_store(device, token):
    worker.store_cloud_token(BID, token)
    assert worker._get_cloud_token(BID) is None
    assert worker._load_token_map()[str(BID)] == token


@pytest.mark.parametrize("changes", [{"role": "retired"}, {"parent_business_id": 55}, {"public_id": None}])
def test_token_requires_a_current_root_owner_with_a_bizid(device, changes):
    worker.store_cloud_token(BID, cloud_token())
    change_owner(device, **changes)
    assert worker._get_cloud_token(BID) is None


def test_replaced_active_database_is_authoritative_even_if_worker_factory_is_stale(device, monkeypatch):
    token = cloud_token()
    worker.store_cloud_token(BID, token)
    assert worker._get_cloud_token(BID) == token
    replacement = create_engine(f"sqlite:///{device.root / 'replacement_test.db'}")
    Base.metadata.create_all(replacement)
    sessions = sessionmaker(bind=replacement)
    with sessions() as db:
        db.add(User(id=BID, username="restored-owner", password="unused", role="owner", public_id="BA-REPLACED"))
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", sessions)
    try:
        assert worker._get_cloud_token(BID) is None
        assert worker._load_token_map()[str(BID)] == token
    finally:
        replacement.dispose()


@pytest.mark.parametrize("push,pull", [(True, False), (False, True), (True, True)])
def test_wrong_credential_cannot_push_or_pull_and_preserves_local_data(device, monkeypatch, push, pull):
    worker.store_cloud_token(BID, cloud_token(public_id="BA-SYNTHETIC-A"))
    before = device.token_path.read_bytes()
    with device.sessions() as db:
        customer = Customer(business_id=BID, uid="local-B-customer", name="Business B customer")
        db.add(customer)
        db.flush()
        if push:
            db.add(SyncQueue(business_id=BID, entity="customers", entity_id=customer.id,
                             operation="INSERT", payload=json.dumps({"uid": customer.uid, "name": customer.name})))
        db.commit()
    probes = []
    def get(url, **kwargs):
        # The existing unauthenticated health probe contains no business data.
        assert url.endswith("/health") and not kwargs.get("headers")
        probes.append(url)
        return httpx.Response(200, json={"status": "ok"})
    monkeypatch.setattr(worker.httpx, "get", get)
    monkeypatch.setattr(worker.httpx, "post", lambda *a, **k: pytest.fail("Wrong business attempted authenticated cloud egress"))
    with device.sessions() as db:
        worker._sync_business_impl(db, db.get(User, BID), force=True, do_pull=pull)
    assert len(probes) == 1
    with device.sessions() as db:
        assert db.query(Customer).one().name == "Business B customer"
        queued = db.query(SyncQueue).all()
        assert len(queued) == int(push)
        assert all(row.synced_at is None and not row.attempts for row in queued)
    assert device.token_path.read_bytes() == before


@pytest.mark.anyio
async def test_b2b_proxy_uses_central_binding_filter(device, monkeypatch):
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    worker.store_cloud_token(BID, cloud_token(public_id="BA-SYNTHETIC-A"))
    monkeypatch.setattr(b2b_proxy, "_is_local_backend", lambda: True)
    monkeypatch.setattr(b2b_proxy, "_proxy_allowed", lambda: True)
    monkeypatch.setattr(b2b_proxy, "_business_id_from", lambda request: BID)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: pytest.fail("Wrong business opened B2B cloud connection"))
    local_calls = []
    async def local(request):
        local_calls.append(request.url.path)
        return JSONResponse({"mode": "local"})
    request = Request({"type": "http", "method": "GET", "path": "/connections", "headers": [], "query_string": b""})
    response = await b2b_proxy.b2b_cloud_proxy(request, local)
    assert response.status_code == 200 and local_calls == ["/connections"]
    assert b2b_proxy.b2b_status({"id": BID})["cloud_linked"] is False


def test_diagnostics_uses_central_binding_filter_before_opening_archive(device, monkeypatch):
    worker.store_cloud_token(BID, cloud_token(public_id="BA-SYNTHETIC-A"))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("Business B archive uploaded under business A"))
    assert log_uploader.upload_logs_to_cloud(BID, str(device.root / "not-opened.tar.gz")) is False


def test_expired_same_owner_credential_can_refresh_without_the_cloud_signing_key(device, monkeypatch):
    old = cloud_token(expires_in=timedelta(minutes=-1))
    fresh = cloud_token(expires_in=timedelta(hours=24))
    worker.store_cloud_token(BID, old)
    assert worker._get_cloud_token(BID) == old
    sent = []
    def refresh(url, **kwargs):
        sent.append((url, kwargs["headers"]["Authorization"]))
        return httpx.Response(200, json={"token": fresh})
    monkeypatch.setattr(worker.httpx, "post", refresh)
    assert worker.ensure_fresh_cloud_token(BID) == fresh
    assert worker._get_cloud_token(BID) == fresh
    assert len(sent) == 1 and sent[0][0].endswith("/auth/refresh") and sent[0][1] == f"Bearer {old}"


@pytest.mark.parametrize("changes", [{"public_id": "BA-SYNTHETIC-A"}, {"role": "cashier"}, {"role": "admin", "user_id": 51}])
def test_refresh_cannot_persist_foreign_or_staff_credential(device, monkeypatch, changes):
    old = cloud_token(expires_in=timedelta(hours=1))
    worker.store_cloud_token(BID, old)
    before = device.token_path.read_bytes()
    monkeypatch.setattr(worker.httpx, "post", lambda *a, **k: httpx.Response(200, json={"token": cloud_token(**changes)}))
    assert worker.ensure_fresh_cloud_token(BID) == old
    assert device.token_path.read_bytes() == before
    assert worker._REFRESH_BACKOFF[BID] > utc_now()


def test_db_identity_change_during_refresh_cannot_rebind_or_return_old_credential(device, monkeypatch):
    old = cloud_token(expires_in=timedelta(hours=1))
    worker.store_cloud_token(BID, old)
    before = device.token_path.read_bytes()
    def refresh(*args, **kwargs):
        change_owner(device, public_id="BA-RESTORED-C")
        return httpx.Response(200, json={"token": cloud_token()})
    monkeypatch.setattr(worker.httpx, "post", refresh)
    assert worker.ensure_fresh_cloud_token(BID) is None
    assert device.token_path.read_bytes() == before


def test_refresh_cas_rechecks_identity_inside_persistence_lock(device, monkeypatch):
    old = cloud_token(expires_in=timedelta(hours=1))
    worker.store_cloud_token(BID, old)
    before = device.token_path.read_bytes()
    persist = worker.store_cloud_token
    def replace_after_precheck(*args, **kwargs):
        change_owner(device, public_id="BA-RESTORED-C")
        return persist(*args, **kwargs)
    monkeypatch.setattr(worker.httpx, "post", lambda *a, **k: httpx.Response(200, json={"token": cloud_token()}))
    monkeypatch.setattr(worker, "store_cloud_token", replace_after_precheck)
    assert worker.ensure_fresh_cloud_token(BID) is None
    assert device.token_path.read_bytes() == before
