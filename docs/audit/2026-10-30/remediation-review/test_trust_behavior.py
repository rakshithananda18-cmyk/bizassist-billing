"""Desired invariants against current production code, all data in-memory.

Failures identify remaining defects; this file does not alter the application.
Run through trust-proof-runner.py with --noconftest.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.db import Base, sync_disabled_var
from database.models import Customer, User, SyncControlOutbox, utc_now
import routes.sync as sync_routes
import routes.sync_staff as sync_staff
from services import auth, control_outbox
from core.api import staff as staff_api

ROOT = Path(__file__).resolve().parents[4]
IDENTITY = {"id": 1, "user_id": 1, "username": "trust_owner", "public_id": "BIZ-TRUST-REVIEW", "role": "enterprise"}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    token = sync_disabled_var.set(True)
    with Session(engine) as db:
        db.add(User(id=1, username=IDENTITY["username"], public_id=IDENTITY["public_id"],
                    role="enterprise", password="fake", business_name="Audit only"))
        db.commit()
        yield db
    sync_disabled_var.reset(token)
    engine.dispose()


def pull(db, **kw):
    return sync_routes.pull_changes(current_user=IDENTITY, db=db, **kw)


def test_compound_cursor_drains_identical_timestamp_rows(db):
    stamp = utc_now() - timedelta(minutes=5)
    db.add_all(Customer(id=i, business_id=1, name=str(i), updated_at=stamp) for i in range(1, 8))
    db.commit()
    cursor = None
    delivered = []
    for _ in range(6):
        page = pull(db, cursor=cursor, limit=2)
        delivered += [r["id"] for r in page["changes"].get("customers", [])]
        cursor = page["cursor"]
        if not page["has_more"]:
            break
    assert delivered == list(range(1, 8))


def test_legacy_worker_timestamp_cursor_does_not_omit_ties(db):
    stamp = utc_now() - timedelta(minutes=5)
    db.add_all(Customer(id=i, business_id=1, name=str(i), updated_at=stamp) for i in (1, 2, 3))
    db.commit()
    page1 = pull(db, limit=2)
    # The previous worker derives its watermark from timestamps in truncated
    # tables and does not consume the new response cursor.
    legacy_cursor = max(r["updated_at"] for r in page1["changes"]["customers"])
    page2 = pull(db, last_sync_at=legacy_cursor, limit=2)
    got = [r["id"] for r in page1["changes"]["customers"] + page2["changes"].get("customers", [])]
    assert got == [1, 2, 3], f"Legacy worker permanently omitted rows: {got}"


def test_write_after_select_with_current_clock_is_delivered_next(db):
    db.add(Customer(id=1, business_id=1, name="before", updated_at=utc_now() - timedelta(seconds=30)))
    db.commit()
    original = sync_routes._serialize_orm_obj
    wrote = False
    def commit_after_materialization(row, session):
        nonlocal wrote
        result = original(row, session)
        if isinstance(row, Customer) and not wrote:
            wrote = True
            session.add(Customer(id=2, business_id=1, name="during", updated_at=utc_now()))
            session.commit()
        return result
    with patch.object(sync_routes, "_serialize_orm_obj", commit_after_materialization):
        page1 = pull(db, limit=None)
    page2 = pull(db, cursor=page1["cursor"], limit=None)
    assert 2 not in [r["id"] for r in page1["changes"]["customers"]]
    assert 2 in [r["id"] for r in page2["changes"].get("customers", [])]


def test_delayed_commit_predating_snapshot_is_eventually_delivered(db):
    page1 = pull(db, limit=None)
    boundary = datetime.fromisoformat(page1["pulled_at"]).replace(tzinfo=None)
    # Models use client/Python timestamps before commit, and sync accepts
    # source timestamps. This models a long transaction or an offline device
    # whose clock lags the cloud, committing only after page1 completed.
    db.add(Customer(id=7, business_id=1, name="late commit", updated_at=boundary - timedelta(seconds=2)))
    db.commit()
    page2 = pull(db, cursor=page1["cursor"], limit=None)
    assert 7 in [r["id"] for r in page2["changes"].get("customers", [])], "Committed row fell behind the timestamp cursor"


def test_actual_worker_decision_holds_any_unread_table():
    tree = ast.parse((ROOT / "backend/services/sync_worker.py").read_text(encoding="utf-8"))
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Name) and n.test.id == "_cloud_cursor"
                  and any(isinstance(x, ast.Name) and x.id == "_pull_row_failures" for x in ast.walk(n)))
    for rejected in (0, 1, 3):
        for unread in (0, 1, 3):
            advances = []
            ns = dict(_cloud_cursor="cursor:proof", _pull_row_failures=[{}] * rejected,
                      _pull_failed_tables=[{"table": "invoices"}] * unread,
                      _PULL_FAILED_STREAK={}, business_id=1, db=None,
                      logger=logging.getLogger("audit"), _set_pull_cursor=lambda *_: advances.append(1))
            exec(compile(ast.fix_missing_locations(ast.Module(body=[branch], type_ignores=[])), "actual-worker-decision", "exec"), ns)
            assert bool(advances) == (unread == 0)


def test_staff_replication_revokes_and_identical_retry_is_idempotent(db):
    db.add(User(id=2, parent_business_id=1, staff_login_name="counter", username="counter__1",
                password="old", role="supply adder", token_version=0))
    db.commit()
    auth._tv_cache[2] = (0, 10**12)
    rec = sync_staff.StaffRecord(staff_login_name="counter", internal_username="counter__1",
                                hashed_password="new", role="cashier")
    req = sync_staff.StaffPushRequest(staff=[rec])
    sync_staff.sync_staff_push(req, current_user=IDENTITY, db=db)
    assert db.get(User, 2).token_version == 1
    assert 2 not in auth._tv_cache
    sync_staff.sync_staff_push(req, current_user=IDENTITY, db=db)
    assert db.get(User, 2).token_version == 1
    auth._tv_cache[2] = (1, 10**12)
    req.staff[0].deleted = True
    sync_staff.sync_staff_push(req, current_user=IDENTITY, db=db)
    assert db.get(User, 2) is None and 2 not in auth._tv_cache


def test_local_delete_payload_passes_cloud_tombstone_validation(db):
    db.add(User(id=2, parent_business_id=1, staff_login_name="counter", username="counter__1",
                password="old", role="cashier", token_version=0))
    db.commit()
    captured = []
    with patch.object(staff_api, "_push_staff_to_cloud", side_effect=lambda _b, records, **_: captured.extend(records)):
        staff_api.delete_staff(2, current_user=IDENTITY, db=db)
    # Validate the actual local route's payload with the actual receiver schema.
    sync_staff.StaffPushRequest(staff=captured)


def test_staff_mutation_and_control_event_are_atomic_on_enqueue_failure(db):
    with patch("services.immediate_sync.syncs_to_cloud", return_value=True), \
         patch.object(control_outbox, "enqueue_control_event", side_effect=RuntimeError("simulated disk/enqueue failure")), \
         patch.object(control_outbox, "trigger_control_flush"):
        try:
            staff_api.create_staff(staff_api.CreateStaff(username="new_counter", password="StaffPass123!"), current_user=IDENTITY, db=db)
        except RuntimeError:
            db.rollback()
    committed_staff = db.query(User).filter(User.parent_business_id == 1).all()
    events = db.query(SyncControlOutbox).all()
    assert not committed_staff or events, "Staff mutation committed with no durable replication event"


def test_control_outbox_does_not_replay_older_profile_after_newer_success(db):
    old = control_outbox.enqueue_control_event(db, 1, "profile_update", {"business_name": "old"})
    control_outbox.enqueue_control_event(db, 1, "profile_update", {"business_name": "new"})
    cloud_state = {"business_name": "initial"}
    fail_old_once = True
    def cloud(_url, json, **_kw):
        nonlocal fail_old_once
        if json["business_name"] == "old" and fail_old_once:
            fail_old_once = False
            return SimpleNamespace(status_code=503, text="offline")
        cloud_state.update(json)
        return SimpleNamespace(status_code=200, text="ok")
    with patch.object(control_outbox, "is_hybrid_cloud", return_value=True), \
         patch("services.sync_worker._get_cloud_token", return_value="fake"), patch("httpx.post", cloud):
        control_outbox.flush_control_outbox(db, 1)
        old.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()
        control_outbox.flush_control_outbox(db, 1)
    assert cloud_state["business_name"] == "new", f"Older event reverted cloud: {cloud_state}"


def test_control_event_enqueuing_does_not_commit_unrelated_transaction(db):
    owner = db.get(User, 1)
    owner.business_name = "uncommitted"
    control_outbox.enqueue_control_event(db, 1, "profile_update", {"business_name": "uncommitted"})
    db.rollback()
    assert db.get(User, 1).business_name == "Audit only", "Enqueue committed caller-owned transaction"


def test_control_only_backlog_is_retried_with_periodic_pull_disabled(db):
    import services.sync_worker as worker
    owner = db.get(User, 1)
    owner.settings = json.dumps({"general": {"hosting_mode": "hybrid", "cloud_pull_enabled": False}})
    db.commit()
    control_outbox.enqueue_control_event(db, 1, "profile_update", {"business_name": "pending"})
    with patch.object(worker, "SessionLocal", return_value=db), \
         patch.object(worker, "ensure_fresh_cloud_token"), \
         patch("services.cloud_listener.start"), patch("services.cloud_listener.stop"), \
         patch("services.admin_service.effective_plan", return_value="pro"), \
         patch.object(worker, "_LAST_RUN", {}), patch.object(worker, "_LAST_PULL", {}), \
         patch.object(worker, "sync_business") as scheduled:
        worker.run_hybrid_sync()
    assert scheduled.called, "Control backlog is ignored by scheduler idle-skip"


def test_purge_and_rekey_do_not_send_old_tenant_control_event(db):
    from services.admin_service import purge_business_data
    control_outbox.enqueue_control_event(db, 1, "profile_update", {"business_name": "OLD TENANT PROFILE"})
    # Execute the real relational purge, with only external Field/Chroma hooks
    # replaced. No actual vector-store namespace is opened or deleted.
    with patch("services.field_business_cleanup.purge_field_business", return_value={}), \
         patch("services.embeddings.delete_user_chroma_memories"):
        purge_business_data(1, db, delete_owner=False, delete_staff=True)
        owner = db.get(User, 1)
        owner.public_id = "BIZ-RECREATED-IDENTITY"
        db.commit()
    sends = []
    def cloud(_url, **kw):
        sends.append(kw)
        return SimpleNamespace(status_code=200, text="ok")
    with patch.object(control_outbox, "is_hybrid_cloud", return_value=True), \
         patch("services.sync_worker._get_cloud_token", return_value="FAKE-NEW-IDENTITY-TOKEN"), \
         patch("httpx.post", cloud):
        control_outbox.flush_control_outbox(db, 1)
    assert not sends, "Old tenant profile was sent after purge/rekey using the new cloud identity"


def test_export_read_failure_raises_instead_of_empty(db):
    from routes import data_transfer
    with patch.object(data_transfer, "inspect", side_effect=RuntimeError("simulated failed SELECT")):
        with pytest.raises(RuntimeError, match="Database read failure"):
            data_transfer._fetch_table(db, "customers", 1)


def test_plan_guard_binds_tenant_before_lookup():
    service_db = MagicMock()
    service_db.info = {}
    service_db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(parent_business_id=None)
    def effective_plan(_holder):
        assert service_db.info.get("business_id") == 1
        return "pro"
    with patch("database.db.SessionLocal", return_value=service_db), \
         patch("services.admin_service.effective_plan", side_effect=effective_plan):
        assert auth.require_plan(force_enforcement=True)(IDENTITY) == IDENTITY


def test_short_jwt_secret_fails_actual_auth_import_and_long_secret_is_stable():
    env = dict(os.environ, JWT_SECRET="short", PYTHONPATH=str(ROOT / "backend"))
    short = subprocess.run([sys.executable, "-c", "import services.auth"], env=env, capture_output=True, text=True, timeout=20)
    assert short.returncode != 0 and "at least 32 bytes" in short.stderr
    env["JWT_SECRET"] = "review-only-stable-test-key-0123456789abcdef"
    expression = "import services.auth,os; print(services.auth.JWT_SECRET == os.environ['JWT_SECRET'])"
    for _ in range(2):
        valid = subprocess.run([sys.executable, "-c", expression], env=env, capture_output=True, text=True, timeout=20)
        assert valid.returncode == 0 and valid.stdout.strip() == "True"
