"""Corrected production invariants: no wall-clock acknowledgments or lost intent.

SQLite runs by default. TS_RUNTIME_TEST_DATABASE_URL opts into a disposable
full-schema NOSUPERUSER/NOBYPASSRLS database provisioned by the PG runner.
"""
import os
import json
import uuid
import threading
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import Session, sessionmaker
from fastapi import HTTPException

from database.db import Base, SessionLocal, sync_disabled_var, _set_postgres_tenant_guc
from database.models import User, Customer, SyncFeedEvent, SyncControlOutbox, utc_now
from database.security import allocate_owner_id, bind_tenant, authenticate_identity, service_owner_ids
from services.auth import hash_password, _current_token_version, clear_token_version_cache
from routes.sync import pull_changes
from services import control_outbox as control
from routes.sync_staff import StaffRecord, StaffPushRequest, sync_staff_push


@pytest.fixture
def tenant():
    pg = bool(os.environ.get("TS_RUNTIME_TEST_DATABASE_URL"))
    engine = create_engine(os.environ["TS_RUNTIME_TEST_DATABASE_URL"]) if pg else create_engine("sqlite:///:memory:")
    factory = sessionmaker(bind=engine)
    if pg:
        event.listen(factory, "after_begin", _set_postgres_tenant_guc)
    else:
        Base.metadata.create_all(engine)
    db = factory()
    bid = allocate_owner_id(db)
    owner = User(id=bid, username="v2_" + uuid.uuid4().hex, password=hash_password("ReviewPass123!"), public_id="REVIEW-" + uuid.uuid4().hex,
                 role="enterprise", settings=json.dumps({"general": {"hosting_mode": "hybrid"}}))
    db.add(owner)
    db.commit()
    bid = owner.id
    bind_tenant(db, bid)
    identity = {"id": bid, "user_id": bid, "username": owner.username, "public_id": owner.public_id, "role": owner.role}
    yield db, identity, factory
    db.rollback()
    db.close()
    engine.dispose()


def pull(db, identity, cursor=None, limit=2):
    return pull_changes(current_user=identity, db=db, protocol=2, cursor=cursor, limit=limit)


def test_feed_delivers_ties_raw_sql_and_backdated_commit(tenant):
    db, identity, _ = tenant
    stamp = utc_now() - timedelta(days=10)
    for i in range(5):
        db.add(Customer(business_id=identity["id"], name=f"tie-{i}", updated_at=stamp))
    db.commit()
    cursor, seen = None, set()
    for _ in range(20):
        page = pull(db, identity, cursor)
        seen.update(r["name"] for r in page["changes"].get("customers", []))
        cursor = page["cursor"]
        if not page["has_more"]:
            break
    assert seen == {f"tie-{i}" for i in range(5)}
    db.execute(text("INSERT INTO customers(business_id,uid,name,updated_at) VALUES(:b,:u,'late raw write',:t)"),
               {"b": identity["id"], "u": str(uuid.uuid4()), "t": stamp})
    db.commit()
    late = pull(db, identity, cursor)
    assert "late raw write" in [r["name"] for r in late["changes"].get("customers", [])]


def test_legacy_incremental_peer_gets_explicit_upgrade_hold(tenant):
    db, identity, _ = tenant
    with pytest.raises(HTTPException) as e:
        pull_changes(current_user=identity, db=db, limit=2)
    assert e.value.status_code == 426


def test_intent_composes_with_caller_rollback(tenant):
    db, identity, _ = tenant
    owner = db.get(User, identity["id"])
    owner.business_name = "must rollback"
    control.enqueue_control_event(db, owner.id, "profile_update", {"business_name": "must rollback"})
    db.rollback()
    assert db.get(User, owner.id).business_name is None
    assert db.query(SyncControlOutbox).filter_by(business_id=owner.id).count() == 0


def test_receiver_ack_is_atomic_contiguous_and_retry_idempotent(tenant):
    db, identity, _ = tenant
    staff = User(parent_business_id=identity["id"], username="counter_" + uuid.uuid4().hex, staff_login_name="counter", role="cashier", password="old", token_version=0)
    db.add(staff)
    db.commit()
    rec = StaffRecord(staff_login_name="counter", internal_username=staff.username, hashed_password="new", role="cashier")
    req = StaffPushRequest(staff=[rec], event_id=uuid.uuid4().hex, source_id="test-device", source_revision=1, business_public_id=identity["public_id"])
    sync_staff_push(req, current_user=identity, db=db)
    assert db.get(User, staff.id).token_version == 1
    assert sync_staff_push(req, current_user=identity, db=db)["replayed"]
    assert db.get(User, staff.id).token_version == 1
    req.event_id, req.source_revision = uuid.uuid4().hex, 3
    with pytest.raises(HTTPException) as e:
        sync_staff_push(req, current_user=identity, db=db)
    assert e.value.status_code == 409
    db.rollback()
    req.source_revision, req.staff[0].deleted = 2, True
    sync_staff_push(req, current_user=identity, db=db)
    assert db.get(User, staff.id) is None


def test_fifo_backoff_never_sends_successor_before_predecessor(tenant):
    db, identity, _ = tenant
    first = control.enqueue_control_event(db, identity["id"], "profile_update", {"business_name": "old"})
    control.enqueue_control_event(db, identity["id"], "profile_update", {"business_name": "new"})
    db.commit()
    sends = []
    def offline(_url, **kw):
        sends.append(kw["json"])
        return SimpleNamespace(status_code=503, text="offline")
    with patch.object(control, "_IS_LOCAL", True), patch.object(control, "is_hybrid_cloud", return_value=True), patch("services.sync_worker._get_cloud_token", return_value="fake"), patch("httpx.post", offline):
        assert control.flush_control_outbox(db, identity["id"])["failed"] == 1
        control.flush_control_outbox(db, identity["id"])
    assert len(sends) == 1 and sends[0]["business_name"] == "old"
    assert sends[0]["source_revision"] == 1 and sends[0]["event_id"] == first.event_id


def test_identity_change_quarantines_pending_event(tenant):
    db, identity, _ = tenant
    control.enqueue_control_event(db, identity["id"], "profile_update", {"business_name": "old"})
    db.commit()
    db.get(User, identity["id"]).public_id = "NEW-" + uuid.uuid4().hex
    db.commit()
    with patch.object(control, "_IS_LOCAL", True), patch.object(control, "is_hybrid_cloud", return_value=True), patch("httpx.post") as send:
        control.flush_control_outbox(db, identity["id"])
    assert not send.called
    assert db.query(SyncControlOutbox).filter_by(business_id=identity["id"], status="pending").count() == 0


def test_live_subject_denies_retired_identity_with_warm_version_cache(tenant):
    db, identity, _ = tenant
    from database.security import subject_version
    assert subject_version(db, identity["id"]) is not None
    owner = db.get(User, identity["id"])
    owner.role = "deleted"
    db.commit()
    assert subject_version(db, identity["id"]) is None


def test_real_constrained_role_bootstrap_and_tenant_isolation(tenant):
    db, identity, _ = tenant
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Disposable Postgres role test")
    db.rollback()
    db.info.clear()
    assert db.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar() is False
    assert db.query(User).all() == []
    subject = authenticate_identity(db, identity["username"], "ReviewPass123!")
    assert subject.id == identity["id"]
    assert identity["id"] in service_owner_ids(db)
    with pytest.raises(Exception):
        db.execute(text("CREATE TABLE forbidden_runtime_ddl(id integer)"))
    db.rollback()
    bind_tenant(db, identity["id"])
    with pytest.raises(Exception):
        db.add(Customer(business_id=identity["id"] + 900000, name="cross tenant"))
        db.flush()
    db.rollback()


def test_postgres_transactions_cannot_publish_later_revision_first(tenant):
    db, identity, factory = tenant
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Commit visibility requires concurrent Postgres transactions")
    baseline = pull(db, identity, limit=1000)["cursor"]
    a, b = factory(), factory()
    bind_tenant(a, identity["id"])
    a.add(Customer(business_id=identity["id"], name="first uncommitted", updated_at=utc_now() - timedelta(days=30)))
    a.flush()
    ready, finished, errors = threading.Event(), threading.Event(), []
    def second():
        try:
            bind_tenant(b, identity["id"])
            ready.set()
            b.add(Customer(business_id=identity["id"], name="second concurrent"))
            b.commit()
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            finished.set()
    thread = threading.Thread(target=second)
    thread.start()
    assert ready.wait(5)
    assert not finished.wait(.2), "Later writer must wait for the business clock transaction"
    assert pull(db, identity, baseline, 1000)["changes"] == {}
    a.commit()
    thread.join(10)
    assert finished.is_set() and not errors
    names = [r["name"] for r in pull(db, identity, baseline, 1000)["changes"]["customers"]]
    assert {"first uncommitted", "second concurrent"} <= set(names)
    a.close()
    b.close()


def test_real_role_signup_login_staff_paid_gate_and_public_share(tenant):
    db, _identity, factory = tenant
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Full-schema constrained-role application smoke")
    from routes.auth import signup, SignupRequest, login, LoginRequest, staff_login, StaffLoginRequest
    from core.api.staff import create_staff, CreateStaff
    from services.auth import require_plan
    from database.models import Invoice
    from routes.public import get_public_invoice
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    username = "role_smoke_" + uuid.uuid4().hex
    phone = "9" + str(uuid.uuid4().int % 1000000000).zfill(9)
    created = signup(SignupRequest(username=username, password="ReviewPass123!", business_name="Isolated role smoke", phone=phone), db=db)
    db.close()

    db = factory()
    signed = login(LoginRequest(username=username, password="ReviewPass123!"), request=request, db=db)
    identity = dict(signed, user_id=signed["id"])
    assert signed["id"] == created["id"]
    # Plan guard opens its own SessionLocal; the live global factory is also
    # constrained and inherits/sets the signed tenant before looking up settings.
    assert require_plan(force_enforcement=True)(identity)["id"] == created["id"]
    counter = "counter_" + uuid.uuid4().hex[:8]
    staff_phone = "9" + str(uuid.uuid4().int % 1000000000).zfill(9)
    create_staff(CreateStaff(username=counter, password="ReviewPass123!", phone=staff_phone), current_user=identity, db=db)
    db.close()
    db = factory()
    staff = staff_login(StaffLoginRequest(owner_username=username, staff_login_name=counter, password="ReviewPass123!"), request=request, db=db)
    assert staff["id"] == created["id"] and staff["role"] == "cashier"
    token = uuid.uuid4().hex
    invoice = Invoice(business_id=created["id"], invoice_id="SMOKE-" + uuid.uuid4().hex[:8], customer="Audit customer", total_amount=0, uid_token=token)
    db.add(invoice)
    db.commit()
    db.close()
    db = factory()
    payload = get_public_invoice(token, db=db)
    assert payload is not None
    db.close()


def test_real_role_b2b_flow_and_service_privacy(tenant):
    db, buyer, factory = tenant
    if db.bind.dialect.name != "postgresql" or not os.environ.get("DATABASE_TRADE_SERVICE_URL"):
        pytest.skip("Explicit disposable trade-service role required")
    from database.models import Product, Invoice, PurchaseInvoice, TableAlteration, StockLedger
    from core.connection.service import request_connection, approve_connection
    from core.order.service import get_supplier_catalog, create_order, transition_order_status
    from core.stock.ledger import record_movement
    from database.trade_service import business_profile, trade_session
    seller_db = factory()
    seller_id = allocate_owner_id(seller_db)
    seller = User(id=seller_id, username="trade_seller_" + uuid.uuid4().hex, password=hash_password("ReviewPass123!"),
        public_id="SELLER-" + uuid.uuid4().hex, business_name="Private seller", role="enterprise", address="Partner address",
        settings=json.dumps({"general": {"hosting_mode": "cloud"}, "transactions": {"round_off_enabled": False, "prevent_negative_stock": True}, "totp": {"secret": "SYNTHETIC_PRIVATE_SENTINEL"}}))
    seller_db.add(seller)
    seller_db.flush()
    product = Product(business_id=seller_id, name="Allowed item", category="Visible", selling_price=10.25, cost_price=3.17, is_active=True, track_inventory=True, unit="Nos")
    hidden = Product(business_id=seller_id, name="Hidden item", category="Private", selling_price=50, is_active=True)
    seller_db.add_all([product, hidden])
    seller_db.flush()
    record_movement(seller_db, business_id=seller_id, product_id=product.id, product_name=product.name, qty_delta=10, movement_type="opening", reference_type="review")
    seller_db.commit()
    seller_bizid, product_id, hidden_id = seller.public_id, product.id, hidden.id
    directory = business_profile(db, bizid=seller_bizid)
    assert directory.address is None and not hasattr(directory, "password") and not hasattr(directory, "settings")
    conn = request_connection(db, buyer["id"], seller_bizid, "buyer")
    conn_id = conn.id
    seller_db.rollback()
    bind_tenant(seller_db, seller_id)
    conn = approve_connection(seller_db, seller_id, conn_id)
    conn.catalog_category = "Visible"
    seller_db.commit()
    db.rollback()
    bind_tenant(db, buyer["id"])
    directory = business_profile(db, bizid=seller_bizid)
    assert directory.address == "Partner address" and not hasattr(directory, "settings")
    catalog = get_supplier_catalog(db, buyer["id"], seller_id)
    assert {p["product_id"] for p in catalog} == {product_id}
    assert all("cost_price" not in p and "settings" not in p for p in catalog)
    with pytest.raises((ValueError, PermissionError, HTTPException)):
        create_order(db, buyer["id"], seller_id, [{"product_id": hidden_id, "quantity": 1}])
    order = create_order(db, buyer["id"], seller_id, [{"product_id": product_id, "quantity": 2}])
    order_id = order.id
    assert len(order.line_items) == 1
    for status in ("accepted", "packed", "dispatched", "completed"):
        seller_db.rollback()
        bind_tenant(seller_db, seller_id)
        order = transition_order_status(seller_db, seller_id, order_id, status)
    db.rollback()
    bind_tenant(db, buyer["id"])
    purchase = db.query(PurchaseInvoice).filter_by(business_id=buyer["id"]).filter(PurchaseInvoice.uid == __import__("core.order.service", fromlist=["b2b_purchase_invoice_uid"]).b2b_purchase_invoice_uid(order)).one()
    assert purchase.total_amount == pytest.approx(20.50)
    # Buyer private purchase/product/stock audit rows belong to buyer, even
    # though the authenticated actor completing the order was the seller.
    seller_db.rollback()
    bind_tenant(seller_db, seller_id)
    assert seller_db.query(TableAlteration).filter(TableAlteration.business_id == seller_id, TableAlteration.table_name == "purchase_invoices").count() == 0
    assert db.query(TableAlteration).filter(TableAlteration.business_id == buyer["id"], TableAlteration.table_name == "purchase_invoices").count() >= 1
    assert seller_db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == buyer["id"]).count() == 0
    with pytest.raises(HTTPException) as e:
        with trade_session(db, actor_id=seller_id, operation="transition_order", order_id=order_id):
            pass
    assert e.value.status_code == 403
    service_engine = create_engine(os.environ["DATABASE_TRADE_SERVICE_URL"])
    with service_engine.connect() as c:
        with pytest.raises(Exception):
            c.execute(text("SELECT password,settings FROM users LIMIT 1"))
        c.rollback()
    service_engine.dispose()
    seller_db.close()


def test_real_role_platform_admin_and_campaign_authority(tenant, monkeypatch):
    db, owner, factory = tenant
    if db.bind.dialect.name != "postgresql" or not os.environ.get("ADMIN_SERVICE_URL"):
        pytest.skip("Explicit disposable platform-admin service role required")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from database.db import get_db
    from database.admin_service import admin_session
    from routes.admin import router as admin_router
    from routes.campaigns import router as campaign_router
    from services.auth import create_access_token
    from services.field_business_cleanup import purge_field_business

    monkeypatch.setenv("ADMIN_API_ENABLED", "1")
    schema_engine = create_engine(os.environ["TS_ADMIN_TEST_DATABASE_URL"])
    with Session(schema_engine) as schema:
        admin = User(username="platform_" + uuid.uuid4().hex, password=hash_password("ReviewPass123!"),
            public_id="ADMIN-" + uuid.uuid4().hex, role="admin", token_version=0)
        schema.add(admin)
        schema.commit()
        payload = {"id": admin.id, "user_id": admin.id, "username": admin.username, "role": "admin", "tv": 0}
        schema.execute(text("INSERT INTO ft_settings(business_id) VALUES(:b)"), {"b": owner["id"]})
        schema.commit()

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(campaign_router)

    def runtime_db():
        with factory() as request_db:
            yield request_db

    app.dependency_overrides[get_db] = runtime_db
    headers = {"Authorization": "Bearer " + create_access_token(payload)}
    owner_headers = {"Authorization": "Bearer " + create_access_token(dict(owner, tv=0))}
    with TestClient(app) as client:
        fleet = client.get("/admin/businesses", headers=headers)
        assert fleet.status_code == 200, fleet.text
        assert owner["id"] in {b["id"] for b in fleet.json()}
        audience = client.post("/admin/campaigns/preview-audience", headers=headers,
            json={"audience": {"bizids": [owner["public_id"]]}})
        assert audience.status_code == 200, audience.text
        assert audience.json()["matched"] == 1
        assert audience.json()["sample"][0]["business_id"] == owner["id"]
        assert client.get("/admin/businesses", headers=owner_headers).status_code == 403
        # A signed stale role claim cannot substitute for current DB authority.
        forged_role = create_access_token(dict(owner, tv=0, role="admin"))
        assert client.get("/admin/businesses", headers={"Authorization": "Bearer " + forged_role}).status_code == 403
        with patch.dict(os.environ, {"ADMIN_SERVICE_URL": ""}):
            assert client.get("/admin/businesses", headers=headers).status_code == 503

    # Administrative cleanup has full reference visibility, but a tenant cannot
    # obtain that same authority. No real messages, embeddings or disk purges run.
    with admin_session(db, payload) as service:
        assert purge_field_business(service, owner["id"])["ft_settings"] == 1
        service.commit()
        with schema_engine.begin() as connection:
            connection.execute(text("UPDATE users SET token_version=1 WHERE id=:id"), {"id": payload["id"]})
        # Audit helpers can commit; the next service transaction must recheck TV.
        with pytest.raises(HTTPException) as revoked:
            service.query(User).count()
        assert revoked.value.status_code == 401
    with TestClient(app) as client:
        assert client.get("/admin/businesses", headers=headers).status_code == 401
    with db.connection().begin_nested():
        assert db.execute(text("SELECT pg_has_role(current_user,:r,'MEMBER')"), {"r": "bizassist_platform_test"}).scalar() is False
        assert db.execute(text("SELECT pg_has_role(current_user,:r,'MEMBER')"), {"r": "bizassist_trade_test"}).scalar() is False
    schema_engine.dispose()
