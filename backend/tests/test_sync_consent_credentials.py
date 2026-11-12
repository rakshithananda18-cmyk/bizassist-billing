"""Production-path regressions for audit E07/E08/E09/E17/E18.

All identities, tokens, database rows and process stores are synthetic. These
exercise the imported functions rather than compiling substituted ASTs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import db as database
from database.models import Base, User
from services import sync_policy, sync_retry, sync_worker as worker
from services.dates import utc_now


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "_TOKEN_FILE", tmp_path / "cloud_sync_tokens.json")
    monkeypatch.setattr(worker, "_TOKEN_STORE_LAST_STATE", None)
    worker._REFRESH_BACKOFF.clear()
    worker._REFRESH_FAILURES.clear()
    local_engine = create_engine("sqlite:///" + str(tmp_path / "consent_test.db"))
    Base.metadata.create_all(local_engine)
    sessions = sessionmaker(bind=local_engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(database, "engine", local_engine)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "engine", local_engine)
    guard = database.sync_disabled_var.set(True)
    with sessions() as db:
        db.add(User(id=77, username="audit-owner", password="synthetic", role="owner",
                    public_id="BA-AUDIT77", business_name="Audit fixture",
                    settings=json.dumps({"general": {"hosting_mode": "hybrid", "sync_mode_revision": 0}})))
        db.commit()
    yield sessions
    database.sync_disabled_var.reset(guard)
    local_engine.dispose()


def _local(sessions):
    with sessions() as db:
        owner = db.get(User, 77)
        value = json.loads(owner.settings)
        value["general"].update(hosting_mode="local", sync_mode_revision=1)
        owner.settings = json.dumps(value)
        db.commit()


def test_unrelated_settings_save_cannot_restore_stale_consent(isolated, monkeypatch):
    from routes import auth
    original = auth._get_user_settings
    def interleave(user, db):
        stale = original(user, db)
        _local(isolated)
        return stale
    monkeypatch.setattr(auth, "_get_user_settings", interleave)
    monkeypatch.setattr(auth, "_subscription_view", lambda *a, **k: {"plan": "pro"})
    from routes.auth import SettingsUpdateRequest
    with isolated() as db:
        auth.update_settings(SettingsUpdateRequest(general={"app_zoom": 110}),
                             {"username": "audit-owner", "role": "owner"}, db)
    with isolated() as db:
        general = json.loads(db.get(User, 77).settings)["general"]
    assert general["hosting_mode"] == "local"
    assert general["sync_mode_revision"] == 1
    assert general["app_zoom"] == 110


def test_staff_preference_save_preserves_inherited_owner_configuration(isolated, monkeypatch):
    from routes import auth
    monkeypatch.setattr(auth, "_subscription_view", lambda *a, **k: {"plan": "pro"})
    with isolated() as db:
        owner = db.get(User, 77)
        settings = json.loads(owner.settings)
        settings["inventory"] = {"batch_tracking": True}
        owner.settings = json.dumps(settings)
        db.add(User(id=78, username="audit-cashier", password="synthetic", role="cashier",
                    parent_business_id=77, public_id="BA-AUDIT78"))
        db.commit()
        auth.update_settings(auth.SettingsUpdateRequest(general={"app_zoom": 110}),
                             {"username": "audit-cashier", "role": "cashier"}, db)
    with isolated() as db:
        settings = auth._get_user_settings(db.get(User, 78), db)
    assert settings["inventory"]["batch_tracking"] is True
    assert settings["general"]["app_zoom"] == 110


def test_subscription_response_preserves_consent_changed_during_request(isolated, monkeypatch):
    from routes import auth
    monkeypatch.setattr(auth, "_DB_MODE", "local")
    monkeypatch.setattr(worker, "_get_cloud_token", lambda bid: "synthetic")
    auth._sub_sync_next.clear()
    def reply(*args, **kwargs):
        _local(isolated)
        return httpx.Response(200, json={"subscription": {"plan": "pro"}})
    monkeypatch.setattr(httpx, "get", reply)
    with isolated() as db:
        auth._sync_subscription_from_cloud(db.get(User, 77), db, force=True)
    with isolated() as db:
        saved = json.loads(db.get(User, 77).settings)
    assert saved["general"] == {"hosting_mode": "local", "sync_mode_revision": 1}
    assert saved["subscription"]["plan"] == "pro"


def test_explicit_local_blocks_automatic_activation_before_cloud_request(isolated, monkeypatch):
    from fastapi import BackgroundTasks, HTTPException
    from routes import auth, sync
    monkeypatch.setattr(auth, "_subscription_view", lambda *a, **k: {"plan": "pro"})
    actor = {"id": 77, "username": "audit-owner", "role": "owner", "public_id": "BA-AUDIT77"}
    with isolated() as db:
        auth.update_settings(auth.SettingsUpdateRequest(general={"hosting_mode": "local"}), actor, db)
    monkeypatch.setattr(sync, "_read_verified_cloud_document", lambda *a: pytest.fail("explicit Local attempted cloud verification"))
    with isolated() as db, pytest.raises(HTTPException) as failure:
        sync.save_cloud_token(sync.CloudTokenBody(token="synthetic", enable_sync=True), BackgroundTasks(), actor, db)
    assert failure.value.status_code == 409
    with isolated() as db:
        saved = json.loads(db.get(User, 77).settings)["general"]
    assert saved["hosting_mode"] == "local"
    assert saved["sync_local_only_explicit"] is True
    assert worker._get_cloud_token(77) is None


def test_explicit_hybrid_choice_clears_local_only_flag(isolated, monkeypatch):
    from routes import auth
    monkeypatch.setattr(auth, "_subscription_view", lambda *a, **k: {"plan": "pro"})
    actor = {"id": 77, "username": "audit-owner", "role": "owner", "public_id": "BA-AUDIT77"}
    with isolated() as db:
        auth.update_settings(auth.SettingsUpdateRequest(general={"hosting_mode": "local"}), actor, db)
        # An older client's automatic mode derivation cannot undo the choice.
        auth.update_settings(auth.SettingsUpdateRequest(general={"hosting_mode": "hybrid", "hosting_choice_explicit": False}), actor, db)
        assert json.loads(db.get(User, 77).settings)["general"]["hosting_mode"] == "local"
        auth.update_settings(auth.SettingsUpdateRequest(general={"hosting_mode": "hybrid", "hosting_choice_explicit": True}), actor, db)
    with isolated() as db:
        saved = json.loads(db.get(User, 77).settings)["general"]
    assert saved["hosting_mode"] == "hybrid"
    assert saved["sync_local_only_explicit"] is False
    assert saved["sync_mode_revision"] >= 2


@pytest.mark.parametrize("status", [200, 401])
def test_old_refresh_response_cannot_replace_new_login(isolated, monkeypatch, status):
    worker.store_cloud_token(77, "old-session")
    monkeypatch.setattr(worker, "_token_expiry", lambda value: utc_now() + timedelta(hours=1))
    def reply(*args, **kwargs):
        worker.store_cloud_token(77, "new-login")
        return httpx.Response(status, json={"token": "old-session-refresh"})
    monkeypatch.setattr(worker.httpx, "post", reply)
    assert worker.ensure_fresh_cloud_token(77) == "new-login"
    assert worker._get_cloud_token(77) == "new-login"


def test_old_request_invalidation_is_compare_and_set(isolated):
    worker.store_cloud_token(77, "new-login")
    assert worker._invalidate_cloud_token(77, expected_token="old-session") is False
    assert worker._get_cloud_token(77) == "new-login"
    assert worker._invalidate_cloud_token(77, expected_token="new-login") is True
    assert worker._get_cloud_token(77) is None


def test_refresh_retry_storage_failure_preserves_token_and_in_memory_budget(isolated, monkeypatch):
    worker.store_cloud_token(77, "old-session")
    monkeypatch.setattr(worker, "_token_expiry", lambda value: utc_now() + timedelta(hours=1))
    monkeypatch.setattr(worker.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(sync_retry, "defer", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert worker.ensure_fresh_cloud_token(77) == "old-session"
    assert worker._get_cloud_token(77) == "old-session"
    assert worker._REFRESH_BACKOFF[77] > utc_now()


def test_saved_refresh_survives_retry_budget_cleanup_failure(isolated, monkeypatch):
    worker.store_cloud_token(77, "old-session")
    monkeypatch.setattr(worker, "_token_expiry", lambda value: utc_now() + timedelta(hours=1))
    monkeypatch.setattr(worker.httpx, "post", lambda *a, **k: httpx.Response(200, json={"token": "fresh-session"}))
    monkeypatch.setattr(sync_retry, "success", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert worker.ensure_fresh_cloud_token(77) == "fresh-session"
    assert worker._get_cloud_token(77) == "fresh-session"


def test_whole_settings_writer_cannot_restore_declined_diagnostics(isolated):
    from services.settings_store import replace_settings_preserving_consent
    with isolated() as db:
        owner = db.get(User, 77)
        stale = json.loads(owner.settings)
        stale["general"]["diagnostic_upload_enabled"] = True
        with isolated() as newer:
            current = newer.get(User, 77)
            value = json.loads(current.settings)
            value["general"]["diagnostic_upload_enabled"] = False
            current.settings = json.dumps(value)
            newer.commit()
        replace_settings_preserving_consent(db, owner, stale)
        db.commit()
    with isolated() as db:
        assert json.loads(db.get(User, 77).settings)["general"]["diagnostic_upload_enabled"] is False


def test_local_only_realtime_never_opens_a_cloud_client(isolated, monkeypatch):
    from services import realtime
    _local(isolated)
    monkeypatch.setattr(realtime, "_IS_LOCAL_BACKEND", True)
    worker.store_cloud_token(77, "synthetic")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("Local-only relay opened client"))
    pending = realtime.realtime_manager._relay_to_cloud(77, {"type": "pos.cart_update", "items": [1]})
    with pytest.raises(StopIteration):
        pending.send(None)


def test_realtime_rechecks_consent_after_opening_client(isolated, monkeypatch):
    from services import realtime
    monkeypatch.setattr(realtime, "_IS_LOCAL_BACKEND", True)
    worker.store_cloud_token(77, "synthetic")
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            _local(isolated)
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, *args, **kwargs):
            pytest.fail("relay sent after consent changed")
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    pending = realtime.realtime_manager._relay_to_cloud(77, {"type": "pos.cart_update", "items": [1]})
    with pytest.raises(StopIteration):
        pending.send(None)


def test_control_flush_stops_between_events_when_local_only_is_committed(isolated, monkeypatch):
    from database.models import SyncControlOutbox
    from services import control_outbox
    monkeypatch.setattr(control_outbox, "_IS_LOCAL", True)
    worker.store_cloud_token(77, "synthetic")
    with isolated() as db:
        control_outbox.enqueue_control_event(db, 77, "profile_update", {"business_name": "First"})
        control_outbox.enqueue_control_event(db, 77, "profile_update", {"business_name": "Second"})
        db.commit()
    sent = []
    def reply(*args, **kwargs):
        sent.append(kwargs["json"])
        _local(isolated)
        return httpx.Response(200, json={"status": "success"})
    monkeypatch.setattr(httpx, "post", reply)
    with isolated() as db:
        result = control_outbox.flush_control_outbox(db, 77)
        assert db.query(SyncControlOutbox).filter_by(status="pending").count() == 1
    assert len(sent) == 1
    assert result["completed"] == 1


def test_parity_discards_response_and_stops_paging_after_local_only(isolated, monkeypatch):
    worker.store_cloud_token(77, "synthetic")
    worker._LAST_PARITY.pop(77, None)
    sent = []
    def reply(*args, **kwargs):
        sent.append(kwargs)
        _local(isolated)
        return httpx.Response(200, json={"has_more": True, "cursor": "page-2", "changes": {}})
    monkeypatch.setattr(httpx, "get", reply)
    with isolated() as db:
        result = worker._cloud_parity_check(db, 77)
    assert len(sent) == 1
    assert any("disabled" in error for error in result["errors"])


def test_listener_refuses_local_only_and_stop_closes_active_stream(isolated, monkeypatch):
    from types import SimpleNamespace
    from services import cloud_listener
    _local(isolated)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: pytest.fail("Local-only opened stream"))
    listener = cloud_listener._Listener(77)
    listener._stream("http://127.0.0.1:9", "synthetic")
    closed = []
    listener.response = SimpleNamespace(close=lambda: closed.append(True))
    listener.thread = SimpleNamespace(is_alive=lambda: True)
    listener.connected = True
    monkeypatch.setitem(cloud_listener._listeners, 77, listener)
    assert cloud_listener.stop(77)
    assert closed == [True]
    assert listener.stop_event.is_set()
    assert listener.connected is False


def test_diagnostics_need_separate_opt_in_and_hybrid(isolated, monkeypatch, tmp_path):
    from services import telemetry_relay, log_uploader
    assert sync_policy.cloud_egress_allowed(77)
    assert not sync_policy.cloud_egress_allowed(77, diagnostics=True)
    with isolated() as db:
        owner = db.get(User, 77)
        settings = json.loads(owner.settings)
        settings["general"]["diagnostic_upload_enabled"] = True
        owner.settings = json.dumps(settings)
        db.commit()
    assert sync_policy.cloud_egress_allowed(77, diagnostics=True)
    _local(isolated)
    assert not sync_policy.cloud_egress_allowed(77, diagnostics=True)
    monkeypatch.setattr(telemetry_relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("telemetry sent"))
    monkeypatch.setattr(log_uploader.httpx, "post", lambda *a, **k: pytest.fail("archive sent"))
    assert not telemetry_relay._post_import([{"bizid": "BA-AUDIT77"}], "synthetic")
    assert not log_uploader.upload_logs_to_cloud(77, str(tmp_path / "unopened.tar.gz"))


def test_retry_after_is_durable_and_specific_to_business_and_operation(isolated, monkeypatch):
    monkeypatch.setattr(sync_retry.time, "time", lambda: 1000)
    monkeypatch.setattr(sync_retry.random, "uniform", lambda *a: 0)
    state = sync_retry.defer(77, "pull", httpx.Response(503, headers={"Retry-After": "7200"}))
    assert state["next_attempt_at"] == 8200
    assert not sync_retry.ready(77, "pull")
    assert sync_retry.ready(77, "push")
    assert sync_retry.ready(78, "pull")
    import importlib
    importlib.reload(sync_retry)
    assert not sync_retry.ready(77, "pull")
    sync_retry.success(77, "pull")
    assert sync_retry.ready(77, "pull")


def test_worker_push_retry_after_holds_queue_and_suppresses_immediate_retry(isolated, monkeypatch):
    from database.models import SyncQueue
    worker.store_cloud_token(77, "synthetic")
    for mapping in (worker._CLOUD_STATE, worker._PLAN_BLOCKED, worker._PULL_AUTH_BLOCKED, worker._OFFLINE_STATE):
        mapping.pop(77, None)
    monkeypatch.setattr(worker, "_safe_broadcast", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_heal_unqueued_rows", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_repair_stuck_child_payloads", lambda *a, **k: None)
    monkeypatch.setattr(worker.httpx, "get", lambda *a, **k: httpx.Response(200, json={"status": "ok"}))
    sent = []
    def busy(*args, **kwargs):
        sent.append(kwargs["json"])
        return httpx.Response(503, text="starting", headers={"Retry-After": "3600"})
    monkeypatch.setattr(worker.httpx, "post", busy)
    with isolated() as db:
        db.add(SyncQueue(business_id=77, entity="customers", entity_id=123,
                         operation="INSERT", payload=json.dumps({"uid": "queued-fixture", "name": "Fixture"})))
        db.commit()
        worker.sync_business(db, db.get(User, 77), force=True)
        assert db.query(SyncQueue).filter_by(synced_at=None).count() == 1
        assert not sync_retry.ready(77, "push")
        assert sync_retry.ready(77, "pull")
        worker.sync_business(db, db.get(User, 77), force=True)
        assert db.query(SyncQueue).filter_by(synced_at=None).count() == 1
    assert len(sent) == 1


def test_processes_cannot_lose_each_others_credential_updates(isolated, tmp_path):
    script = """
import sys, time
from pathlib import Path
from services import sync_worker as w
w._TOKEN_FILE = Path(sys.argv[1])
save = w._save_token_map
def delayed(values):
    time.sleep(.04)
    return save(values)
w._save_token_map = delayed
for i in range(4):
    w.store_cloud_token(int(sys.argv[2]) + i, 'synthetic-process-token')
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(worker.__file__).resolve().parent.parent)
    children = [subprocess.Popen([sys.executable, "-c", script, str(worker._TOKEN_FILE), str(start)],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for start in (100, 200)]
    for child in children:
        stdout, stderr = child.communicate(timeout=60)
        assert child.returncode == 0, stderr.decode(errors="replace")
    assert set(worker._load_token_map()) == {str(start + i) for start in (100, 200) for i in range(4)}


def test_second_backend_process_cannot_run_sync(isolated):
    from services.process_lock import acquire_sync_process_lease
    assert acquire_sync_process_lease()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(worker.__file__).resolve().parent.parent)
    child = subprocess.run([sys.executable, "-c",
        "from services.process_lock import acquire_sync_process_lease; print(acquire_sync_process_lease())"],
        env=env, capture_output=True, text=True, timeout=20)
    assert child.returncode == 0
    assert child.stdout.strip() == "False"
