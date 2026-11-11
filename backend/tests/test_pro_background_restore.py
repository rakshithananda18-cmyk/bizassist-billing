"""Verified Pro bootstrap and local-only cancellation, using disposable SQLite.

Every network call is replaced; no cloud account or installed token store is
touched. The restore tests run the actual background worker and feed apply path.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models import (User, Customer, SyncCursor, SyncQueue, SyncLog, SyncInbox, ConflictLog,
                             SyncControlOutbox, SyncFeedClock, SyncFeedEvent, TableAlteration)
from routes import sync as routes
from services import sync_worker as worker
from services.dates import utc_now


@pytest.fixture
def device(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_restore.db'}")
    # Only the real tables exercised by this workflow are needed. Creating the
    # unrelated document/AI/B2B schemas per test makes the suite much slower.
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        User, Customer, SyncCursor, SyncQueue, SyncLog, SyncInbox, ConflictLog,
        SyncControlOutbox, SyncFeedClock, SyncFeedEvent, TableAlteration)])
    sessions = sessionmaker(bind=engine)
    db = sessions()
    owner = User(id=50191, public_id="RESTORE-BUSINESS", username="restore-owner",
                 password="unused-test-hash", role="enterprise",
                 settings=json.dumps({"general": {"hosting_mode": "local", "app_zoom": 90},
                                      "subscription": {"plan": "free"}}))
    db.add(owner)
    db.commit()
    identity = {"id": owner.id, "user_id": owner.id, "username": owner.username,
                "public_id": owner.public_id, "role": "enterprise"}
    bid = owner.id
    for mapping in (worker._LAST_RUN, worker._LAST_PULL, worker._PULL_CURSOR,
                    worker._CLOUD_STATE, worker._PULL_AUTH_BLOCKED, worker._PLAN_BLOCKED,
                    worker._PUSH_INFLIGHT, worker._OFFLINE_STATE):
        mapping.pop(bid, None)
    worker._PULL_MORE_PENDING.discard(bid)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "CLOUD_URL", "https://trusted-cloud.example")
    import core.cloud_endpoint as endpoint
    monkeypatch.setattr(endpoint, "CLOUD_URL", "https://trusted-cloud.example")
    saved = []
    monkeypatch.setattr(worker, "store_cloud_token", lambda b, t: saved.append((b, t)))
    monkeypatch.setattr(worker, "_get_cloud_token", lambda b: "cloud-issued-test-token")
    monkeypatch.setattr(worker, "ensure_fresh_cloud_token", lambda b: "cloud-issued-test-token")
    monkeypatch.setattr(worker, "_safe_broadcast", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_heal_unqueued_rows", lambda *a, **k: 0)
    monkeypatch.setattr(worker, "_repair_stuck_child_payloads", lambda *a, **k: 0)
    from services import cloud_listener, control_outbox
    monkeypatch.setattr(cloud_listener, "start", lambda *a: None)
    monkeypatch.setattr(cloud_listener, "stop", lambda *a: None)
    monkeypatch.setattr(control_outbox, "flush_control_outbox", lambda *a: {})
    profile = {"public_id": owner.public_id, "role": "enterprise"}
    subscription = {"plan": "pro", "status": "active"}
    calls, pages = [], []

    def cloud_get(url, **kwargs):
        assert url.startswith("https://trusted-cloud.example/")
        calls.append((url, kwargs))
        if url.endswith("/profile"):
            return httpx.Response(200, json=profile)
        if url.endswith("/settings"):
            return httpx.Response(200, json={"subscription": subscription})
        if url.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"})
        if url.endswith("/api/sync/pull"):
            response = pages.pop(0) if pages else {"protocol": 2, "cursor": "feed:v2:812:0", "changes": {}, "has_more": False}
            return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
        raise AssertionError(f"Unexpected cloud read: {url}")

    monkeypatch.setattr(httpx, "get", cloud_get)
    monkeypatch.setattr(httpx, "post", Mock(side_effect=AssertionError("Unexpected cloud write")))
    env = SimpleNamespace(db=db, sessions=sessions, owner=owner, bid=bid, identity=identity,
                          saved=saved, profile=profile, subscription=subscription,
                          calls=calls, pages=pages, cloud_get=cloud_get)
    yield env
    db.close()
    engine.dispose()
    worker._PULL_MORE_PENDING.discard(bid)
    for mapping in (worker._LAST_RUN, worker._LAST_PULL, worker._PULL_CURSOR,
                    worker._CLOUD_STATE, worker._PULL_AUTH_BLOCKED, worker._PLAN_BLOCKED,
                    worker._PUSH_INFLIGHT, worker._OFFLINE_STATE):
        mapping.pop(bid, None)


def provision(device, enabled=True):
    tasks = BackgroundTasks()
    response = routes.save_cloud_token(routes.CloudTokenBody(token="cloud-issued-test-token", enable_sync=enabled),
                                       tasks, current_user=device.identity, db=device.db)
    return response, tasks


def settings(device):
    device.db.expire_all()
    return json.loads(device.db.get(User, device.bid).settings)


def change_mode(device, mode):
    with device.sessions() as db:
        owner = db.get(User, device.bid)
        current = json.loads(owner.settings)
        current["general"]["hosting_mode"] = mode
        owner.settings = json.dumps(current)
        db.commit()


def explicit_local_choice(device, monkeypatch):
    from routes import auth
    monkeypatch.setattr(auth, "_DB_MODE", "local")
    monkeypatch.setattr(auth, "_subscription_view", lambda *a, **k: {"plan": "pro"})
    with device.sessions() as db:
        auth.update_settings(auth.SettingsUpdateRequest(general={"hosting_mode": "local"}),
                             current_user=device.identity, db=db)


@pytest.mark.parametrize("starting_mode", ["local", "hybrid"])
def test_new_local_confirmation_during_verification_cannot_be_overwritten(device, monkeypatch, starting_mode):
    change_mode(device, starting_mode)
    def cloud_get(url, **kwargs):
        if url.endswith("/settings"):
            explicit_local_choice(device, monkeypatch)
        return device.cloud_get(url, **kwargs)
    monkeypatch.setattr(httpx, "get", cloud_get)
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == 409
    assert not device.saved
    assert settings(device)["general"]["hosting_mode"] == "local"
    assert settings(device)["general"]["sync_mode_revision"] == 1


def test_local_choice_between_verification_and_commit_wins_atomic_activation(device, monkeypatch):
    def store_token(bid, token):
        device.saved.append((bid, token))
        explicit_local_choice(device, monkeypatch)
    monkeypatch.setattr(worker, "store_cloud_token", store_token)
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == 409
    assert settings(device)["general"]["hosting_mode"] == "local"


def test_client_cannot_clear_server_restore_state_or_forge_consent_revision(device, monkeypatch):
    from routes import auth
    monkeypatch.setattr(auth, "_subscription_view", lambda *a, **k: {"plan": "pro"})
    owner = device.db.get(User, device.bid)
    owner.settings = json.dumps({"general": {"hosting_mode": "local", "sync_bootstrap_pending": True, "sync_mode_revision": 3}})
    device.db.commit()
    auth.update_settings(auth.SettingsUpdateRequest(general={"sync_bootstrap_pending": False, "sync_mode_revision": 100}),
                         current_user=device.identity, db=device.db)
    general = settings(device)["general"]
    assert general["sync_bootstrap_pending"] is True
    assert general["sync_mode_revision"] == 3


def test_failed_credential_persistence_does_not_enable_or_queue_sync(device, monkeypatch):
    def denied(*args):
        raise OSError("Synthetic storage failure")
    monkeypatch.setattr(worker, "store_cloud_token", denied)
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == 503
    assert settings(device)["general"]["hosting_mode"] == "local"


def run_queued(tasks):
    assert len(tasks.tasks) == 1
    task = tasks.tasks[0]
    task.func(*task.args, **task.kwargs)


def page(revision, name=None, more=False):
    rows = [] if name is None else [{"id": revision, "uid": f"customer-{revision}", "name": name,
                                    "business_id": 812, "updated_at": utc_now().isoformat()}]
    return {"protocol": 2, "cursor": f"feed:v2:812:{revision}", "changes": {"customers": rows}, "has_more": more}


def test_verified_pro_activation_persists_identity_entitlement_then_queues(device):
    response, tasks = provision(device)
    assert response == {"status": "ok", "hosting_mode": "hybrid", "sync_started": True, "initial_restore_pending": True}
    local = settings(device)
    assert local["general"] == {"hosting_mode": "hybrid", "app_zoom": 90, "sync_bootstrap_pending": True}
    assert local["subscription"]["plan"] == "pro"
    assert device.saved == [(device.bid, "cloud-issued-test-token")]
    assert tasks.tasks[0].kwargs == {"pull": True}
    for _, request in device.calls:
        assert request["headers"]["Authorization"] == "Bearer cloud-issued-test-token"
        assert request["timeout"] == 5.0


@pytest.mark.parametrize("enabled", [False, True])
def test_another_business_token_never_replaces_the_working_credential(device, enabled):
    device.profile["public_id"] = "ANOTHER-BUSINESS"
    with pytest.raises(HTTPException) as exc:
        provision(device, enabled)
    assert exc.value.status_code == 409
    assert not device.saved
    assert settings(device)["general"]["hosting_mode"] == "local"


def test_staff_cloud_token_cannot_activate_owner_sync(device):
    device.profile["role"] = "cashier"
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == 409
    assert not device.saved


@pytest.mark.parametrize("subscription", [{"plan": "free"}, {"plan": "pro", "expires_at": "2020-01-01"}])
def test_free_or_expired_cloud_plan_does_not_activate_or_overwrite_token(device, subscription):
    device.subscription.clear()
    device.subscription.update(subscription)
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == 402
    assert not device.saved
    assert settings(device)["subscription"] == {"plan": "free"}


def test_free_identity_can_store_a_verified_credential_without_enabling_sync(device):
    device.subscription["plan"] = "free"
    response, tasks = provision(device, False)
    assert response == {"status": "ok"}
    assert device.saved and not tasks.tasks
    assert settings(device)["general"]["hosting_mode"] == "local"
    assert all(not url.endswith("/settings") for url, _ in device.calls)


@pytest.mark.parametrize("status, expected", [(401, 401), (429, 503), (503, 503)])
def test_cloud_refusal_or_outage_keeps_local_mode_and_existing_credential(device, monkeypatch, status, expected):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(status, json={}))
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == expected
    assert not device.saved
    assert settings(device)["general"]["hosting_mode"] == "local"


def test_local_only_choice_wins_over_an_already_queued_restore(device):
    _, tasks = provision(device)
    change_mode(device, "local")
    device.calls.clear()
    run_queued(tasks)
    assert not device.calls
    assert settings(device)["general"]["hosting_mode"] == "local"
    assert device.db.query(Customer).count() == 0


def test_switch_to_local_while_cloud_page_is_in_flight_discards_page_without_advancing(device, monkeypatch):
    _, tasks = provision(device)
    def cloud_get(url, **kwargs):
        if url.endswith("/api/sync/pull"):
            change_mode(device, "local")
            return httpx.Response(200, json=page(1, "Must stay cloud-only"))
        return device.cloud_get(url, **kwargs)
    monkeypatch.setattr(httpx, "get", cloud_get)
    run_queued(tasks)
    assert device.db.query(Customer).count() == 0
    assert device.db.query(SyncCursor).count() == 0
    assert settings(device)["general"]["hosting_mode"] == "local"


def test_initial_restore_continues_pages_and_never_claims_empty_outbox_means_ready(device):
    _, tasks = provision(device)
    device.pages.extend([page(1, "First cloud customer", more=True), page(2, "Second cloud customer")])
    run_queued(tasks)
    status = routes.get_queue_depth(current_user=device.identity, db=device.db)
    assert status["pending_count"] == 0
    assert status["pull"] == {"initialized": False, "initial_restore_pending": True, "has_more": True}
    assert device.db.query(Customer).count() == 1
    # The normal sync interval has not elapsed. An initial restore still drains
    # its next bounded page on the next scheduler tick.
    worker.run_hybrid_sync()
    device.db.expire_all()
    assert {r.name for r in device.db.query(Customer)} == {"First cloud customer", "Second cloud customer"}
    status = routes.get_queue_depth(current_user=device.identity, db=device.db)
    assert status["pull"] == {"initialized": True, "initial_restore_pending": False, "has_more": False}
    assert device.db.query(SyncCursor).one().cursor_value == "feed:v2:812:2"


def test_initial_restore_retries_after_a_failed_page_and_process_memory_reset(device):
    _, tasks = provision(device)
    device.pages.append(httpx.Response(503, json={"detail": "Starting"}))
    run_queued(tasks)
    assert settings(device)["general"]["sync_bootstrap_pending"] is True
    assert device.db.query(SyncCursor).count() == 0
    worker._LAST_PULL.pop(device.bid, None)
    worker._PULL_MORE_PENDING.discard(device.bid)
    device.pages.append(page(1, "Recovered customer"))
    worker.run_hybrid_sync()
    assert settings(device)["general"]["sync_bootstrap_pending"] is False
    assert device.db.query(Customer).one().name == "Recovered customer"


def test_legacy_successful_push_log_is_not_an_initial_restore_cursor(device):
    device.db.add(SyncLog(business_id=device.bid, status="success", synced_at=utc_now()))
    device.db.commit()
    _, tasks = provision(device)
    device.pages.append(page(1, "Older cloud history"))
    run_queued(tasks)
    request = next(options for url, options in device.calls if url.endswith("/api/sync/pull"))
    assert "cursor" not in request["params"]
    assert "last_sync_at" not in request["params"]
    assert device.db.query(Customer).one().name == "Older cloud history"


def test_an_unapplied_inbox_row_keeps_initial_restore_pending(device):
    _, tasks = provision(device)
    invalid = page(1, "Cloud customer")
    # The customer name is nullable. Missing the durable UID is a real held
    # outcome: applying it would risk duplicating an existing customer.
    invalid["changes"]["customers"][0].pop("uid")
    device.pages.append(invalid)
    run_queued(tasks)
    status = routes.get_queue_depth(current_user=device.identity, db=device.db)
    assert status["inbox"]["pending_count"] == 1
    assert status["pull"]["initialized"] is False
    assert status["pull"]["initial_restore_pending"] is True


def test_local_choice_at_restore_completion_is_not_overwritten(device, monkeypatch):
    from sqlalchemy.orm import Query
    _, tasks = provision(device)
    original_update = Query.update
    choices = []

    def concurrent_choice(query, values, **kwargs):
        raw = values.get(User.settings)
        if raw and json.loads(raw).get("general", {}).get("sync_bootstrap_pending") is False:
            explicit_local_choice(device, monkeypatch)
            choices.append("local")
        return original_update(query, values, **kwargs)

    monkeypatch.setattr(Query, "update", concurrent_choice)
    device.pages.append(page(1, "Restored before the choice"))
    run_queued(tasks)
    assert choices == ["local"]
    general = settings(device)["general"]
    assert general["hosting_mode"] == "local"
    assert general["sync_bootstrap_pending"] is True


def test_cloud_backend_does_not_accept_local_device_activation(device, monkeypatch):
    monkeypatch.setattr(device.db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    with pytest.raises(HTTPException) as exc:
        provision(device)
    assert exc.value.status_code == 409
    assert not device.calls and not device.saved


def test_local_only_scheduler_stops_an_existing_cloud_listener(device, monkeypatch):
    from services import cloud_listener
    stopped = []
    monkeypatch.setattr(cloud_listener, "stop", stopped.append)
    worker.run_hybrid_sync()
    assert device.bid in stopped
    assert not device.calls


def test_local_only_switch_between_upload_chunks_prevents_later_uploads(device, monkeypatch):
    _, tasks = provision(device)
    for i in range(worker._PUSH_CHUNK_SIZE + 1):
        device.db.add(Customer(business_id=device.bid, name=f"Local customer {i}"))
    device.db.commit()
    sent = []
    def upload(url, json=None, **kwargs):
        assert url.endswith("/api/sync/push")
        sent.append(json)
        change_mode(device, "local")
        return httpx.Response(200, json={"applied": len(json["changes"])})
    monkeypatch.setattr(httpx, "post", upload)
    run_queued(tasks)
    assert len(sent) == 1
    assert settings(device)["general"]["hosting_mode"] == "local"
    assert device.db.query(SyncQueue).filter(SyncQueue.synced_at.is_(None)).count() >= 1
