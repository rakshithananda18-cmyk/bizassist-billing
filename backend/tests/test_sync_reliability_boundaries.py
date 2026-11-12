import json
from datetime import timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.db import Base, sync_disabled_var
from database.models import User, Customer, StockLedger, SyncQueue, SyncTombstone, InvoicePayment
from routes import sync
from core.sync import tombstones
from core.sync.readiness import assert_financial_ready
from services.dates import utc_now


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    token = sync_disabled_var.set(True)
    session.add(User(id=7, username="boundary-owner", public_id="BOUNDARY-BIZ", role="enterprise",
                     password="synthetic", settings=json.dumps({"general": {"hosting_mode": "local"}})))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        sync_disabled_var.reset(token)
        engine.dispose()


def identity():
    return {"id": 7, "user_id": 7, "username": "boundary-owner", "public_id": "BOUNDARY-BIZ", "role": "enterprise"}


def push(db, changes):
    changes = [dict(change, created_at=change.get("created_at") or utc_now().isoformat()) for change in changes]
    return sync.push_changes(sync.PushPayload(changes=changes), BackgroundTasks(),
                             current_user=identity(), _plan={"plan": "pro"}, db=db)


@pytest.mark.parametrize("mode", ["local", "hybrid"])
def test_partial_restore_blocks_local_financial_flush_even_if_paused(db, mode):
    owner = db.get(User, 7)
    owner.settings = json.dumps({"general": {"hosting_mode": mode, "sync_bootstrap_pending": True}})
    db.commit()
    token = sync_disabled_var.set(False)
    try:
        db.add(StockLedger(business_id=7, uid="blocked-movement", product_name="Rice", movement_type="opening", qty_delta=10))
        with pytest.raises(HTTPException) as error:
            db.flush()
        assert error.value.status_code == 409
        assert error.value.headers["X-Sync-State"] == "restoring"
    finally:
        db.rollback()
        sync_disabled_var.reset(token)


def test_completed_local_books_remain_writable_offline(db):
    token = sync_disabled_var.set(False)
    try:
        db.add(StockLedger(business_id=7, uid="offline-movement", product_name="Rice", movement_type="opening", qty_delta=10))
        db.commit()
        assert db.query(StockLedger).count() == 1
        assert_financial_ready(db, 7)
    finally:
        sync_disabled_var.reset(token)


def test_bad_existing_update_does_not_abort_other_records(db):
    old = utc_now() - timedelta(days=2)
    movement = StockLedger(business_id=7, uid="existing-movement", product_name="Rice", movement_type="opening", qty_delta=10, updated_at=old)
    db.add(movement)
    db.commit()
    result = push(db, [
        {"entity": "stock_ledger", "entity_id": movement.id, "operation": "UPDATE", "payload": {
            "uid": movement.uid, "qty_delta": None, "updated_at": utc_now().isoformat()}},
        {"entity": "customers", "entity_id": 9901, "operation": "INSERT", "payload": {
            "uid": "valid-next-customer", "name": "Valid customer", "updated_at": utc_now().isoformat()}},
    ])
    assert len(result["rejected"]) == 1
    assert db.query(Customer).one().name == "Valid customer"
    from database.models import ConflictLog
    assert db.query(ConflictLog).filter_by(business_id=7, resolution="review_needed").count() == 0
    db.refresh(movement)
    assert movement.qty_delta == 10


def test_stale_delete_and_stale_resurrection_keep_newer_state(db):
    old = utc_now() - timedelta(days=2)
    newer = utc_now() - timedelta(days=1)
    row = Customer(business_id=7, uid="versioned-customer", name="Newer name", updated_at=newer)
    db.add(row)
    db.commit()
    result = push(db, [{"entity": "customers", "entity_id": row.id, "operation": "DELETE",
        "payload": {"uid": row.uid, "_sync_deleted_at": old.isoformat()}}])
    assert len(result["skipped"]) == 1
    assert db.query(Customer).one().name == "Newer name"
    push(db, [{"entity": "customers", "entity_id": row.id, "operation": "DELETE",
        "payload": {"uid": row.uid, "_sync_deleted_at": utc_now().isoformat()}}])
    assert db.query(Customer).count() == 0
    result = push(db, [{"entity": "customers", "entity_id": 999, "operation": "INSERT",
        "payload": {"uid": "versioned-customer", "name": "Stale replay", "updated_at": old.isoformat()}}])
    assert len(result["skipped"]) == 1
    assert db.query(Customer).count() == 0


def test_raw_delete_also_retains_durable_version(db):
    row = Customer(business_id=7, uid="raw-deleted", name="Raw", updated_at=utc_now() - timedelta(days=1))
    db.add(row)
    db.commit()
    db.execute(text("DELETE FROM customers WHERE uid='raw-deleted'"))
    db.commit()
    assert db.query(SyncTombstone).filter_by(row_uid="raw-deleted").one().deleted_at
    assert not tombstones.check_upsert(db, 7, "customers", "raw-deleted", utc_now() - timedelta(hours=1))


def test_local_only_delete_is_remembered_for_later_enable(db):
    row = Customer(business_id=7, uid="offline-deleted", name="Offline")
    db.add(row)
    db.commit()
    token = sync_disabled_var.set(False)
    try:
        db.delete(row)
        db.commit()
    finally:
        sync_disabled_var.reset(token)
    marker = db.query(SyncTombstone).filter_by(row_uid="offline-deleted").one()
    assert marker.needs_upload
    assert tombstones.queue_pending_deletes(db, 7) == 1
    queued = db.query(SyncQueue).filter_by(operation="DELETE").one()
    payload = json.loads(queued.payload)
    assert payload["uid"] == "offline-deleted"
    tombstones.acknowledge_delete(db, 7, "customers", payload)
    db.commit()
    db.refresh(marker)
    assert marker.needs_upload is False


def test_equal_version_financial_change_is_reviewed_without_overwrite(db):
    stamp = utc_now() - timedelta(days=1)
    row = StockLedger(business_id=7, uid="equal-version", product_name="Rice", movement_type="opening", qty_delta=10, updated_at=stamp)
    db.add(row)
    db.commit()
    result = push(db, [{"entity": "stock_ledger", "entity_id": row.id, "operation": "UPDATE",
        "payload": {"uid": row.uid, "qty_delta": 8, "updated_at": stamp.isoformat()}}])
    assert len(result["rejected"]) == 1
    db.refresh(row)
    assert row.qty_delta == 10


def test_integer_parent_collision_is_never_accepted_in_strict_sync(db):
    from database.sync_map import resolve_parent_fk_uids
    payload = {"invoice_id": 1}
    assert resolve_parent_fk_uids(db, InvoicePayment, payload, business_id=7, require_uid=True)


def test_integer_b2b_party_collision_requires_durable_business_identity(db):
    from database.sync_map import resolve_parent_fk_uids
    from core.models import B2BConnection
    assert resolve_parent_fk_uids(db, B2BConnection,
        {"seller_business_id": 7, "buyer_business_id": 8}, business_id=7, require_uid=True)


def test_unknown_entity_rejects_transaction_without_partial_ack(db):
    with pytest.raises(HTTPException) as error:
        push(db, [{"entity": "future-unsupported-entity", "entity_id": 1, "operation": "INSERT", "payload": {}}])
    assert error.value.status_code == 426


def test_postgres_sync_decisions_take_transaction_business_lock():
    from types import SimpleNamespace
    calls = []
    fake = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
                           execute=lambda statement, params: calls.append((str(statement), params)))
    tombstones.lock_business(fake, 7)
    assert calls and "pg_advisory_xact_lock" in calls[0][0]
