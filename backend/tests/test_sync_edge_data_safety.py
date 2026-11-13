"""Sync audit regressions: identity isolation, ledger stock and durable restore.

All ORM data is disposable and every worker network request is mocked by the
background-restore fixture. No installed credential or application DB is used.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

from database.db import Base, sync_disabled_var
from database.models import Customer, Inventory, Product, StockLedger, SyncCursor, SyncInbox, User
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem
from services import sync_worker as worker
from services.dates import utc_now
from tests.test_pro_background_restore import device, page, provision, run_queued, settings


@pytest.fixture
def isolated_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    token = sync_disabled_var.set(True)
    db.add_all([
        User(id=7, username="test-local-a", password="unused", public_id="test-A"),
        User(id=42, username="test-local-b", password="unused", public_id="test-B"),
    ])
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
        sync_disabled_var.reset(token)


def test_source_owner_integer_never_selects_another_local_business(isolated_db):
    db = isolated_db
    foreign = Product(business_id=42, uid="other-business-product", name="Rice", selling_price=10,
                      updated_at=utc_now() - timedelta(days=1))
    db.add(foreign)
    db.commit()
    outcome = worker._apply_pulled_row(db, 7, "products", Product, {
        "id": 300, "uid": "cloud-A-product", "business_id": 42,
        "name": "Rice", "selling_price": 99, "updated_at": utc_now().isoformat(),
    })
    db.commit()
    assert outcome.status == "applied"
    assert (foreign.business_id, foreign.uid, foreign.selling_price) == (42, "other-business-product", 10)
    assert db.query(Product).filter(Product.business_id == 7).one().uid == "cloud-A-product"


def test_uid_lookup_cannot_transfer_a_foreign_owned_record(isolated_db):
    db = isolated_db
    foreign = Customer(business_id=42, uid="foreign-uid", name="Other tenant")
    db.add(foreign)
    db.commit()
    with pytest.raises(ValueError, match="Cross-business"):
        worker._apply_pulled_row(db, 7, "customers", Customer, {
            "id": 19, "uid": foreign.uid, "business_id": 7, "name": "Overwrite attempt",
            "updated_at": utc_now().isoformat(),
        })
    assert (foreign.business_id, foreign.name) == (42, "Other tenant")


@pytest.mark.parametrize("entity, model", [("customers", Customer), ("products", Product)])
def test_same_name_with_distinct_durable_uids_keeps_both_records(isolated_db, entity, model):
    db = isolated_db
    local = model(business_id=7, uid="local-identity", name="Same name",
                  updated_at=utc_now() - timedelta(days=1))
    db.add(local)
    db.commit()
    result = worker._apply_pulled_row(db, 7, entity, model, {
        "id": 200, "uid": "cloud-identity", "business_id": 7, "name": "Same name",
        "updated_at": utc_now().isoformat(),
    })
    db.commit()
    assert result.status == "applied"
    assert {row.uid for row in db.query(model).filter(model.business_id == 7)} == {
        "local-identity", "cloud-identity"}


def test_only_a_single_unkeyed_legacy_candidate_can_adopt_identity(isolated_db):
    db = isolated_db
    local = Customer(business_id=7, uid="", name="Legacy", phone="111",
                     updated_at=utc_now() - timedelta(days=1))
    db.add(local)
    db.commit()
    result = worker._apply_pulled_row(db, 7, "customers", Customer, {
        "uid": "adopted-identity", "business_id": 42, "name": "Legacy", "phone": "111",
        "updated_at": utc_now().isoformat(),
    })
    db.commit()
    assert result.status == "applied"
    assert db.query(Customer).count() == 1
    assert (local.business_id, local.uid) == (7, "adopted-identity")


def test_ambiguous_unkeyed_legacy_candidates_are_held_without_mutation(isolated_db):
    db = isolated_db
    rows = [Customer(business_id=7, uid="", name="Ambiguous") for _ in range(2)]
    db.add_all(rows)
    db.commit()
    with pytest.raises(Exception, match="Multiple rows"):
        worker._apply_pulled_row(db, 7, "customers", Customer, {
            "uid": "new-identity", "name": "Ambiguous", "updated_at": utc_now().isoformat(),
        })
    assert [row.uid for row in rows] == ["", ""]


def test_stock_snapshot_is_derived_from_merged_ledger_and_exact_bucket(isolated_db):
    db = isolated_db
    old = utc_now() - timedelta(days=1)
    product = Product(business_id=7, uid="shared-product", name="Stock item", updated_at=old)
    db.add(product)
    db.flush()
    inv = Inventory(business_id=7, uid="shared-inventory", product_id=product.id,
                    product_name=product.name, stock=7, updated_at=old)
    other_batch = Inventory(business_id=7, uid="legacy-batch", product_id=product.id,
                            product_name=product.name, batch_no="legacy", stock=25)
    db.add_all([inv, other_batch,
        StockLedger(business_id=7, uid="opening", product_id=product.id, product_name=product.name,
                    movement_type="opening", qty_delta=10, updated_at=old),
        StockLedger(business_id=7, uid="sale-A", product_id=product.id, product_name=product.name,
                    movement_type="sale", qty_delta=-3, updated_at=old),
    ])
    db.commit()
    stamp = utc_now().isoformat()
    assert worker._apply_pulled_row(db, 7, "inventory", Inventory, {
        "uid": inv.uid, "business_id": 42, "product_id_uid": product.uid,
        "product_name": product.name, "stock": 6, "updated_at": stamp,
    }).status == "applied"
    assert inv.stock == 7
    movement = {"uid": "sale-B", "business_id": 42, "product_id_uid": product.uid,
                "product_name": product.name, "movement_type": "sale", "qty_delta": -4,
                "updated_at": stamp}
    assert worker._apply_pulled_row(db, 7, "stock_ledger", StockLedger, movement).status == "applied"
    db.commit()
    assert inv.stock == 3
    assert other_batch.stock == 25
    # Replaying a page cannot count the same movement twice.
    replay = worker._apply_pulled_row(db, 7, "stock_ledger", StockLedger, movement)
    db.commit()
    assert replay.status == "applied" and replay.is_lost is False
    assert replay.conflicts == 0
    assert inv.stock == 3
    assert db.query(StockLedger).count() == 3


def test_legacy_inventory_without_movements_retains_its_synced_quantity(isolated_db):
    db = isolated_db
    result = worker._apply_pulled_row(db, 7, "inventory", Inventory, {
        "uid": "legacy-stock", "business_id": 42, "product_name": "Legacy loose goods",
        "stock": 12.5, "updated_at": utc_now().isoformat(),
    })
    db.commit()
    assert result.hook_failure is None
    assert db.query(Inventory).one().stock == 12.5


def test_duplicate_device_cache_rows_never_multiply_a_ledger_bucket(isolated_db):
    from core.stock import ledger
    from core.sync.apply_hooks import reconcile_stock_cache
    db = isolated_db
    product = Product(business_id=7, uid="same-product", name="Shared stock")
    db.add(product)
    db.flush()
    first = Inventory(business_id=7, uid="z-device-cache", product_id=product.id, product_name=product.name, stock=90)
    second = Inventory(business_id=7, uid="a-device-cache", product_id=product.id, product_name=product.name, stock=95)
    opening = StockLedger(business_id=7, uid="same-opening", product_id=product.id,
        product_name=product.name, movement_type="opening", qty_delta=100)
    db.add_all([first, second, opening])
    db.commit()
    assert reconcile_stock_cache(db, opening)
    assert (first.stock, second.stock) == (0, 100)
    ledger.record_movement(db, business_id=7, product_id=product.id, product_name=product.name,
        movement_type="sale", qty_delta=-3)
    db.flush()
    assert sum(row.stock for row in (first, second)) == 97
    first.stock, second.stock = 999, 999
    ledger.rebuild_inventory_cache(db, 7)
    assert sum(row.stock for row in (first, second)) == 97
    assert first.uid == "z-device-cache" and second.uid == "a-device-cache"


def test_failed_invariant_is_durable_and_restore_waits_for_successful_repair(device, monkeypatch):
    _, tasks = provision(device)
    failure = SimpleNamespace(ok=False, entity="customers", row_id=1, errors=["Injected invariant failure"])
    monkeypatch.setattr(worker._apply_hooks, "run_post_apply", lambda *a, **k: failure)
    broadcasts = []
    monkeypatch.setattr(worker, "_safe_broadcast", lambda bid, event: broadcasts.append(event))
    device.pages.append(page(1, "Cloud customer"))
    run_queued(tasks)
    assert device.db.query(Customer).count() == 1
    repair = device.db.query(SyncInbox).one()
    assert repair.reason == "hook-failed" and repair.applied_at is None
    assert settings(device)["general"]["sync_bootstrap_pending"] is True
    final_progress = [event for event in broadcasts if event.get("type") == "sync.progress"][-1]
    assert final_progress["failed"] == 1
    assert final_progress["done"] < final_progress["total"]

    # A repair must run against today's local row, without replaying the stale
    # source payload over an edit made since that payload arrived.
    customer = device.db.query(Customer).one()
    customer.name = "Newer local edit"
    customer.updated_at = utc_now() + timedelta(seconds=1)
    repair.next_attempt_at = utc_now() - timedelta(seconds=1)
    device.db.commit()
    seen = []
    def repaired(db, entity, obj, **kwargs):
        seen.append(obj.name)
        return SimpleNamespace(ok=True)
    monkeypatch.setattr(worker._apply_hooks, "run_post_apply", repaired)
    import httpx
    monkeypatch.setattr(httpx, "post", lambda _url, **kwargs: httpx.Response(200, json={
        "status": "success", "applied": len(kwargs["json"]["changes"]), "deferred": [], "rejected": [], "skipped": []}))
    from services import sync_retry
    next_attempt = sync_retry.snapshot(device.bid)["pull"]["next_attempt_at"]
    monkeypatch.setattr(sync_retry.time, "time", lambda: next_attempt + 1)
    device.pages.append({"protocol": 2, "cursor": "feed:v2:812:1", "changes": {}, "has_more": False})
    worker.run_hybrid_sync()
    device.db.expire_all()
    assert seen == ["Newer local edit"]
    assert device.db.query(Customer).one().name == "Newer local edit"
    assert device.db.query(SyncInbox).one().applied_at is not None
    assert settings(device)["general"]["sync_bootstrap_pending"] is False


def test_failed_inbox_receipt_holds_cursor_and_bootstrap(device, monkeypatch):
    _, tasks = provision(device)
    response = page(1, "Declined cloud customer")
    response["changes"]["customers"][0].pop("uid")
    monkeypatch.setattr(worker._inbox, "remember", lambda *a, **k: None)
    device.pages.append(response)
    run_queued(tasks)
    assert device.db.query(Customer).count() == 0
    assert device.db.query(SyncInbox).count() == 0
    assert device.db.query(SyncCursor).count() == 0
    assert settings(device)["general"]["sync_bootstrap_pending"] is True


def test_unknown_entity_requires_update_and_holds_entire_page(device):
    _, tasks = provision(device)
    response = page(1, "Known row must replay with unsupported entity")
    response["changes"]["future_financial_entity"] = [{"uid": "future-row", "id": 73}]
    device.pages.append(response)
    run_queued(tasks)
    assert worker._PROTOCOL_BLOCKED[device.bid] is True
    assert device.db.query(Customer).count() == 0
    assert device.db.query(SyncCursor).count() == 0
    assert settings(device)["general"]["sync_bootstrap_pending"] is True


def _b2b_rows(db):
    connection = B2BConnection(uid="shared-connection", seller_business_id=42, buyer_business_id=7,
                               seller_bizid="test-B", buyer_bizid="test-A", status="accepted")
    order = B2BOrder(uid="shared-order", seller_business_id=42, buyer_business_id=7,
                     seller_bizid="test-B", buyer_bizid="test-A", order_number="TEST-B2B-1",
                     order_date="2026-11-12")
    db.add_all([connection, order])
    db.flush()
    line = B2BOrderLineItem(uid="shared-line", order_id=order.id, product_name="B2B goods")
    db.add(line)
    db.commit()
    return connection, order, line


@pytest.mark.parametrize("index", [0, 1, 2])
def test_shared_b2b_rows_replay_for_either_verified_party(isolated_db, index):
    from database.models import _serialize_orm_obj
    db = isolated_db
    row = _b2b_rows(db)[index]
    payload = _serialize_orm_obj(row, db)
    for business_id in (7, 42):
        outcome = worker._apply_pulled_row(db, business_id, row.__tablename__, type(row), payload)
        assert outcome.status in {"applied", "skipped"}
        repair = worker._apply_pulled_row(db, business_id, row.__tablename__, type(row),
                                          dict(payload, _sync_repair_only=True))
        assert repair.status == "applied" and repair.hook_failure is None
    assert db.query(type(row)).count() == 1


def test_existing_b2b_identity_cannot_change_counterparty(isolated_db):
    from database.models import _serialize_orm_obj
    db = isolated_db
    connection, _, _ = _b2b_rows(db)
    db.add(User(id=99, username="test-stranger", password="unused", public_id="test-C"))
    db.commit()
    payload = _serialize_orm_obj(connection, db)
    payload.update(seller_business_id=999, seller_business_id_bizid="test-C",
                   seller_bizid="test-C", updated_at=utc_now().isoformat())
    with pytest.raises(ValueError, match="cannot change its business parties"):
        worker._apply_pulled_row(db, 7, "b2b_connections", B2BConnection, payload)
    assert connection.seller_business_id == 42


def test_new_b2b_row_requires_receiving_business_membership(isolated_db):
    db = isolated_db
    db.add(User(id=99, username="test-stranger", password="unused", public_id="test-C"))
    db.commit()
    with pytest.raises(ValueError, match="Cross-business B2B"):
        worker._apply_pulled_row(db, 7, "b2b_connections", B2BConnection, {
            "uid": "unrelated-relationship", "seller_business_id": 900,
            "buyer_business_id": 901, "seller_business_id_bizid": "test-B",
            "buyer_business_id_bizid": "test-C", "updated_at": utc_now().isoformat(),
        })
    assert db.query(B2BConnection).count() == 0


def test_b2b_parent_uid_cannot_attach_line_to_unrelated_business(isolated_db):
    from database.sync_map import resolve_parent_fk_uids
    db = isolated_db
    db.add(User(id=99, username="test-stranger", password="unused", public_id="test-C"))
    parent = B2BOrder(uid="unrelated-order", seller_business_id=42, buyer_business_id=99,
                      order_number="TEST-OTHER-1", order_date="2026-11-12")
    db.add(parent)
    db.commit()
    payload = {"uid": "bad-line", "order_id": parent.id, "order_id_uid": parent.uid,
               "product_name": "Private order item"}
    assert resolve_parent_fk_uids(db, B2BOrderLineItem, payload,
                                  business_id=7, require_uid=True) is True
    assert resolve_parent_fk_uids(db, B2BOrderLineItem, payload,
                                  business_id=42, require_uid=True) is False


def test_shared_parent_and_child_feed_locks_use_the_same_owner_order(isolated_db):
    from database.change_feed import _owner_expressions
    db = isolated_db
    _, order, _ = _b2b_rows(db)
    expressions = _owner_expressions("b2b_order_line_items", {"order_id"})
    assert "LEAST(" in expressions[0]
    assert "GREATEST(" in expressions[1]
    # The real SQLite triggers use the equivalent min/max ordering, even when
    # the seller has the greater local ID. Both parties receive each event.
    from database.models import SyncFeedEvent
    for bid in (7, 42):
        assert db.query(SyncFeedEvent).filter(SyncFeedEvent.business_id == bid,
            SyncFeedEvent.entity == "b2b_order_line_items", SyncFeedEvent.row_uid == "shared-line").count() == 1


def test_raw_sql_local_delete_is_retained_for_later_upload(isolated_db):
    from core.sync.tombstones import get_tombstone, queue_pending_deletes
    from database.models import SyncQueue
    db = isolated_db
    customer = Customer(business_id=7, uid="raw-delete", name="Removed while local-only")
    db.add(customer)
    db.commit()
    db.execute(text("DELETE FROM customers WHERE uid=:uid"), {"uid": customer.uid})
    db.commit()
    marker = get_tombstone(db, 7, "customers", "raw-delete")
    assert marker["needs_upload"] is True
    assert queue_pending_deletes(db, 7) == 1
    queued = db.query(SyncQueue).one()
    assert queued.entity == "customers" and queued.operation == "DELETE"


def test_accepted_remote_delete_keeps_author_version_and_never_echoes(isolated_db):
    from core.sync.tombstones import get_tombstone, queue_pending_deletes
    db = isolated_db
    stamp = utc_now() - timedelta(seconds=10)
    customer = Customer(business_id=7, uid="remote-delete", name="Cloud deletion",
                         updated_at=stamp - timedelta(days=1))
    db.add(customer)
    db.commit()
    outcome = worker._apply_pulled_row(db, 7, "customers", Customer, {
        "uid": customer.uid, "_sync_deleted": True, "_sync_deleted_at": stamp.isoformat(),
    })
    db.commit()
    assert outcome.status == "applied"
    assert db.query(Customer).count() == 0
    marker = get_tombstone(db, 7, "customers", "remote-delete")
    assert marker["deleted_at"] == stamp
    assert marker["needs_upload"] is False
    assert queue_pending_deletes(db, 7) == 0


def test_stale_remote_delete_cannot_clear_newer_pending_local_delete(isolated_db):
    from core.sync.tombstones import get_tombstone, record_delete
    db = isolated_db
    incoming = utc_now() - timedelta(seconds=10)
    newer = incoming + timedelta(seconds=5)
    record_delete(db, 7, "customers", "pending-local-delete", newer, needs_upload=True)
    db.commit()
    outcome = worker._apply_pulled_row(db, 7, "customers", Customer, {
        "uid": "pending-local-delete", "_sync_deleted": True,
        "_sync_deleted_at": incoming.isoformat(),
    })
    db.commit()
    assert outcome.status == "skipped"
    marker = get_tombstone(db, 7, "customers", "pending-local-delete")
    assert marker["deleted_at"] == newer and marker["needs_upload"] is True


def test_invalid_parent_uid_shape_does_not_issue_unknown_column_sql(isolated_db):
    from database.models import RegisterShift
    from database.sync_map import resolve_parent_fk_uids
    db = isolated_db
    statements = []
    connection = db.connection()
    listener = lambda conn, cursor, statement, *args: statements.append(statement)
    event.listen(connection, "before_cursor_execute", listener)
    try:
        assert resolve_parent_fk_uids(db, RegisterShift, {
            "uid": "bad-parent-shape", "user_id": 7, "user_id_uid": "users-have-no-uid",
        }, business_id=7, require_uid=True) is True
    finally:
        event.remove(connection, "before_cursor_execute", listener)
    assert not any('FROM "users" WHERE uid' in statement for statement in statements)
    db.add(Customer(business_id=7, uid="after-invalid-parent", name="Still writable"))
    db.flush()


def test_parent_resolution_query_failure_rolls_back_its_savepoint(isolated_db, monkeypatch):
    from database.sync_map import resolve_parent_fk_uids
    db = isolated_db
    original_execute = db.execute
    rollbacks = []
    connection = db.connection()
    listener = lambda conn, name, context: rollbacks.append(name)
    event.listen(connection, "rollback_savepoint", listener)
    def broken_parent_query(statement, *args, **kwargs):
        if 'FROM "products" WHERE uid' in str(statement):
            return original_execute(text("SELECT no_such_column FROM products"))
        return original_execute(statement, *args, **kwargs)
    monkeypatch.setattr(db, "execute", broken_parent_query)
    try:
        assert resolve_parent_fk_uids(db, Inventory, {
            "uid": "missing-child", "product_id_uid": "product-parent",
        }, business_id=7, require_uid=True) is True
    finally:
        event.remove(connection, "rollback_savepoint", listener)
    assert len(rollbacks) == 1
    db.add(Customer(business_id=7, uid="after-parent-query-error", name="Still writable"))
    db.flush()


def test_financial_inbox_repair_can_finish_while_restore_write_gate_is_active(device, monkeypatch):
    from core.sync.readiness import install_readiness_guard
    from services import sync_retry
    install_readiness_guard()
    Base.metadata.create_all(device.db.get_bind(), tables=[Inventory.__table__])
    _, tasks = provision(device)
    failure = SimpleNamespace(ok=False, entity="inventory", row_id=1, errors=["Injected stock cache failure"])
    monkeypatch.setattr(worker._apply_hooks, "run_post_apply", lambda *a, **k: failure)
    response = page(1)
    response["changes"] = {"inventory": [{
        "id": 1, "uid": "financial-repair-inventory", "business_id": 812,
        "product_name": "Stock requiring repair", "stock": 6,
        "updated_at": utc_now().isoformat(),
    }]}
    device.pages.append(response)
    run_queued(tasks)
    repair = device.db.query(SyncInbox).one()
    assert repair.applied_at is None
    assert settings(device)["general"]["sync_bootstrap_pending"] is True
    repair.next_attempt_at = utc_now() - timedelta(seconds=1)
    device.db.commit()
    def repair_stock(db, entity, obj, **kwargs):
        obj.stock = 3
        db.flush()
        return SimpleNamespace(ok=True)
    monkeypatch.setattr(worker._apply_hooks, "run_post_apply", repair_stock)
    next_attempt = sync_retry.snapshot(device.bid)["pull"]["next_attempt_at"]
    monkeypatch.setattr(sync_retry.time, "time", lambda: next_attempt + 1)
    device.pages.append({"protocol": 2, "cursor": "feed:v2:812:1", "changes": {}, "has_more": False})
    worker.run_hybrid_sync()
    device.db.expire_all()
    assert device.db.query(Inventory).one().stock == 3
    assert device.db.query(SyncInbox).one().applied_at is not None
    assert settings(device)["general"]["sync_bootstrap_pending"] is False


def test_deferred_inbox_row_that_fails_hooks_becomes_repair_only(device, monkeypatch):
    import json
    from services import sync_retry
    _, tasks = provision(device)
    original_apply = worker._apply_pulled_row
    offered = []
    def defer_first(db, bid, entity, model, record):
        offered.append(entity)
        if len(offered) == 1:
            return worker._Applied("deferred")
        return original_apply(db, bid, entity, model, record)
    monkeypatch.setattr(worker, "_apply_pulled_row", defer_first)
    failure = SimpleNamespace(ok=False, entity="customers", row_id=1, errors=["Injected journal failure"])
    monkeypatch.setattr(worker._apply_hooks, "run_post_apply", lambda *a, **k: failure)
    device.pages.append(page(1, "Deferred then applied customer"))
    run_queued(tasks)
    repair = device.db.query(SyncInbox).one()
    assert device.db.query(Customer).count() == 1
    assert repair.reason == "hook-failed" and repair.applied_at is None
    assert json.loads(repair.payload)["_sync_repair_only"] is True
    customer = device.db.query(Customer).one()
    customer.name = "Later local version"
    customer.updated_at = utc_now() + timedelta(seconds=1)
    repair.next_attempt_at = utc_now() - timedelta(seconds=1)
    device.db.commit()
    seen = []
    def repaired(db, entity, obj, **kwargs):
        seen.append(obj.name)
        return SimpleNamespace(ok=True)
    monkeypatch.setattr(worker._apply_hooks, "run_post_apply", repaired)
    import httpx
    monkeypatch.setattr(httpx, "post", lambda _url, **kwargs: httpx.Response(200, json={
        "status": "success", "applied": len(kwargs["json"]["changes"]),
        "deferred": [], "rejected": [], "skipped": []}))
    next_attempt = sync_retry.snapshot(device.bid)["pull"]["next_attempt_at"]
    monkeypatch.setattr(sync_retry.time, "time", lambda: next_attempt + 1)
    device.pages.append({"protocol": 2, "cursor": "feed:v2:812:1", "changes": {}, "has_more": False})
    worker.run_hybrid_sync()
    device.db.expire_all()
    assert seen == ["Later local version"]
    assert device.db.query(SyncInbox).one().applied_at is not None
    assert settings(device)["general"]["sync_bootstrap_pending"] is False


def test_numeric_wire_representations_are_not_financial_conflicts():
    from decimal import Decimal
    from core.sync.apply_hooks import payloads_differ
    assert not payloads_differ({"amount": -4}, {"amount": -4.0})
    assert not payloads_differ({"amount": "4.00"}, {"amount": Decimal("4")})
    assert payloads_differ({"amount": 4.01}, {"amount": Decimal("4")})
    assert payloads_differ({"phone": "00123"}, {"phone": "123"})
    assert payloads_differ({"active": False}, {"active": 0})


@pytest.mark.parametrize("response", [
    {"status": "success"},
    {"status": "success", "applied": 2},
    {"status": "success", "applied": 0, "deferred": [{"entity": "customers", "row_id": 999999}]},
])
def test_unverifiable_push_ack_preserves_payload_and_records_recovery_action(device, monkeypatch, response):
    import httpx
    from database.models import SyncLog, SyncQueue
    provision(device)
    customer = Customer(business_id=device.bid, name="Unacknowledged sale party")
    device.db.add(customer)
    device.db.commit()
    queued = device.db.query(SyncQueue).filter_by(entity="customers").one()
    original_payload = queued.payload
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, json=response))
    worker._sync_business_impl(device.db, device.owner, force=True)
    device.db.expire_all()
    queued = device.db.get(SyncQueue, queued.id)
    assert queued.synced_at is None
    assert queued.payload == original_payload
    assert "acknowledgement could not be verified" in queued.error
    assert "Update cloud/device" in queued.error
    assert device.db.query(SyncLog).filter(SyncLog.status == "failed").count() == 1


@pytest.mark.parametrize("cloud_outcome", ["accepted", "deferred", "unavailable"])
def test_concurrent_local_edit_does_not_inherit_older_push_result(device, monkeypatch, cloud_outcome):
    import httpx
    import json
    from database.models import SyncQueue
    provision(device)
    token = sync_disabled_var.set(True)
    try:
        customer = Customer(business_id=device.bid, name="Already synchronized")
        device.db.add(customer)
        device.db.commit()
    finally:
        sync_disabled_var.reset(token)
    customer.name = "First pending update"
    device.db.commit()
    queued = device.db.query(SyncQueue).filter_by(entity="customers").one()
    queue_id, customer_id = queued.id, customer.id
    sent = []
    def reply(url, **kwargs):
        sent.extend(kwargs["json"]["changes"])
        with device.sessions() as other:
            changed = other.get(Customer, customer_id)
            changed.name = "Second edit while push is in flight"
            other.commit()
            assert other.query(SyncQueue).filter_by(entity="customers").one().id == queue_id
        if cloud_outcome == "unavailable":
            return httpx.Response(503, json={"detail": "Temporary outage"})
        if cloud_outcome == "deferred":
            return httpx.Response(200, json={"status": "success", "applied": 0, "received": 1,
                "deferred": [{"entity": "customers", "row_id": customer_id}]})
        return httpx.Response(200, json={"status": "success", "applied": 1, "received": 1})
    monkeypatch.setattr(httpx, "post", reply)
    worker._sync_business_impl(device.db, device.owner, force=True)
    device.db.expire_all()
    queued = device.db.get(SyncQueue, queue_id)
    assert sent[0]["payload"]["name"] == "First pending update"
    assert json.loads(queued.payload)["name"] == "Second edit while push is in flight"
    assert queued.synced_at is None
    assert queued.attempts == 0 and queued.next_attempt_at is None
    assert queued.error is None


def test_retry_requested_during_push_is_not_overwritten_by_older_ack(device, monkeypatch):
    import httpx
    from database.models import SyncQueue
    provision(device)
    device.db.add(Customer(business_id=device.bid, name="Retry this update"))
    device.db.commit()
    queued = device.db.query(SyncQueue).filter_by(entity="customers").one()
    queued.attempts, queued.error = 2, "Previous attempt failed"
    device.db.commit()
    queue_id = queued.id
    def reply(url, **kwargs):
        with device.sessions() as other:
            retried = other.get(SyncQueue, queue_id)
            retried.attempts, retried.error, retried.next_attempt_at = 0, None, None
            other.commit()
        return httpx.Response(200, json={"status": "success", "applied": 1})
    monkeypatch.setattr(httpx, "post", reply)
    worker._sync_business_impl(device.db, device.owner, force=True)
    device.db.expire_all()
    queued = device.db.get(SyncQueue, queue_id)
    assert queued.synced_at is None
    assert queued.attempts == 0 and queued.error is None and queued.next_attempt_at is None


def test_delete_during_push_remains_pending_until_its_own_ack(device, monkeypatch):
    import httpx
    from database.models import SyncQueue, SyncTombstone
    provision(device)
    customer = Customer(business_id=device.bid, name="Remove after pending update")
    device.db.add(customer)
    device.db.commit()
    customer_id = customer.id
    operations = []
    def reply(url, **kwargs):
        changes = kwargs["json"]["changes"]
        operations.extend(change["operation"] for change in changes)
        if len(operations) == 1:
            with device.sessions() as other:
                other.delete(other.get(Customer, customer_id))
                other.commit()
        return httpx.Response(200, json={"status": "success", "applied": len(changes)})
    monkeypatch.setattr(httpx, "post", reply)
    worker._sync_business_impl(device.db, device.owner, force=True)
    device.db.expire_all()
    pending = device.db.query(SyncQueue).filter(SyncQueue.synced_at.is_(None)).all()
    assert [row.operation for row in pending] == ["DELETE"]
    assert device.db.query(SyncTombstone).one().needs_upload is True
    worker._sync_business_impl(device.db, device.owner, force=True)
    device.db.expire_all()
    assert operations == ["INSERT", "DELETE"]
    assert device.db.query(SyncQueue).filter(SyncQueue.synced_at.is_(None)).count() == 0
    assert device.db.query(SyncTombstone).one().needs_upload is False


def test_pending_delete_deduplication_uses_entity_and_uid(isolated_db):
    import json
    from core.sync.tombstones import queue_pending_deletes, record_delete
    from database.models import SyncQueue
    db = isolated_db
    stamp = utc_now()
    for entity in ("customers", "products"):
        record_delete(db, 7, entity, "uid-reused-across-entities", stamp, needs_upload=True)
    db.add(SyncQueue(business_id=7, entity="customers", entity_id=90, operation="DELETE",
                     payload=json.dumps({"uid": "uid-reused-across-entities"}), created_at=stamp))
    db.commit()
    assert queue_pending_deletes(db, 7) == 1
    assert {row.entity for row in db.query(SyncQueue)} == {"customers", "products"}


@pytest.mark.parametrize("changed", ["product_id", "product_name", "godown_id", "batch_no"])
def test_accepted_stock_movement_cannot_be_moved_to_another_bucket(isolated_db, changed):
    from database.models import Godown
    db = isolated_db
    old = utc_now() - timedelta(days=1)
    products = [Product(business_id=7, uid=f"bucket-product-{index}", name=f"Bucket product {index}")
                for index in range(2)]
    godown = Godown(business_id=7, uid="different-godown", name="Different godown")
    db.add_all(products + [godown])
    db.flush()
    movement = StockLedger(business_id=7, uid="fixed-bucket-movement", product_id=products[0].id,
                            product_name=products[0].name, movement_type="opening", qty_delta=7,
                            updated_at=old)
    inventory = Inventory(business_id=7, product_id=products[0].id, product_name=products[0].name, stock=7)
    db.add_all([movement, inventory])
    db.commit()
    payload = {"uid": movement.uid, "business_id": 7, "product_id_uid": products[0].uid,
               "product_name": products[0].name, "movement_type": "opening", "qty_delta": 7,
               "updated_at": utc_now().isoformat()}
    if changed == "product_id":
        payload["product_id_uid"] = products[1].uid
    elif changed == "godown_id":
        payload["godown_id_uid"] = godown.uid
    else:
        payload[changed] = "Changed bucket"
    with pytest.raises(ValueError, match="Immutable stock movement bucket"):
        worker._apply_pulled_row(db, 7, "stock_ledger", StockLedger, payload)
    assert movement.product_id == products[0].id and movement.product_name == products[0].name
    assert movement.godown_id is None and movement.batch_no is None
    assert inventory.stock == 7


def test_stock_quantity_version_review_still_reconciles_the_same_bucket(isolated_db):
    db = isolated_db
    old = utc_now() - timedelta(days=1)
    movement = StockLedger(business_id=7, uid="same-bucket-quantity", product_name="Loose rice",
                            movement_type="opening", qty_delta=7, updated_at=old)
    inventory = Inventory(business_id=7, product_name="Loose rice", stock=7)
    db.add_all([movement, inventory])
    db.commit()
    outcome = worker._apply_pulled_row(db, 7, "stock_ledger", StockLedger, {
        "uid": movement.uid, "business_id": 42, "product_name": "Loose rice",
        "qty_delta": 8, "updated_at": utc_now().isoformat(),
    })
    db.commit()
    assert outcome.status == "applied" and outcome.conflicts == 1
    assert movement.qty_delta == 8 and inventory.stock == 8


def test_historical_feed_event_never_serializes_a_new_tenants_current_row(isolated_db):
    from fastapi import HTTPException
    from database.change_feed import pull_feed
    db = isolated_db
    customer = Customer(business_id=7, uid="reassigned-current-row", name="Original tenant's row")
    db.add(customer)
    db.commit()
    # Model a legacy/raw-SQL ownership corruption after A's event was captured.
    db.execute(text("UPDATE customers SET business_id=42,name=:name WHERE uid=:uid"),
               {"name": "Other tenant's private current data", "uid": customer.uid})
    db.commit()
    db.expire_all()
    with pytest.raises(HTTPException) as refusal:
        pull_feed(db, 7, None, 100)
    assert refusal.value.status_code == 409
    assert "ownership changed" in refusal.value.detail
    result = pull_feed(db, 42, None, 100)
    assert result["changes"]["customers"][0]["name"] == "Other tenant's private current data"
