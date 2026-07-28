"""Regression tests for the 2026-07-28 P0 tenant and money hardening."""
import json
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main_groq import app
from database.db import SessionLocal
from database.models import Customer, Invoice, InvoiceLineItem, Product, User
from core.billing import commands as billing
from database.sync_map import resolve_parent_fk_uids
from services.auth import resolve_business_id_in_db
from routes.sync_profile import ProfilePushRequest, sync_profile_push
from routes.sync_staff import StaffPushRequest, StaffRecord, sync_staff_push


client = TestClient(app)


def _signup(label: str):
    username = f"p0_{uuid.uuid4().hex[:10]}"
    response = client.post("/signup", json={
        "username": username,
        "password": "P0TestPass123!",
        "business_name": label,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['token']}"}


def test_cloud_recovery_routes_are_not_exposed(monkeypatch):
    import routes.auth as auth_routes

    monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud")
    response = client.post("/api/auth/reconcile_password", json={
        "username": "someone", "password": "NotARecoveryProof1!", "public_id": "BA-PUBLIC",
    })
    assert response.status_code == 404


def test_bizid_resolves_to_this_database_owner_id_and_unknown_bizid_fails_closed():
    owner_a, _headers_a = _signup("BizID Alpha")
    owner_b, _headers_b = _signup("BizID Bravo")
    db = SessionLocal()
    try:
        # Pretend this is a local token: its numeric id is unrelated to the
        # cloud record, but its BizID is the shared business identity.
        cross_db_token = {
            "id": owner_b["id"], "user_id": owner_b["id"],
            "username": owner_a["username"], "public_id": owner_a["public_id"],
        }
        assert resolve_business_id_in_db(cross_db_token, db) == owner_a["id"]

        with pytest.raises(HTTPException) as unknown:
            resolve_business_id_in_db({
                "id": owner_b["id"], "username": owner_a["username"],
                "public_id": "BA-NOT-LINKED",
            }, db)
        assert unknown.value.status_code == 403
    finally:
        db.close()


def test_profile_and_staff_sync_use_bizid_not_foreign_numeric_id():
    owner_a, _headers_a = _signup("BizID Control Alpha")
    owner_b, _headers_b = _signup("BizID Control Bravo")
    db = SessionLocal()
    try:
        cross_db_owner_token = {
            "id": owner_b["id"], "user_id": owner_b["id"],
            "username": owner_a["username"], "public_id": owner_a["public_id"],
            "role": "owner",
        }
        sync_profile_push(
            ProfilePushRequest(business_name="Alpha profile through BizID"),
            current_user=cross_db_owner_token, db=db,
        )
        result = sync_staff_push(
            StaffPushRequest(staff=[StaffRecord(
                staff_login_name=f"counter_{uuid.uuid4().hex[:6]}",
                internal_username=f"sync_{uuid.uuid4().hex[:8]}",
                hashed_password="$2b$12$not-a-real-hash-but-never-verified-here",
            )]),
            current_user=cross_db_owner_token, db=db,
        )
        assert result["upserted"] == 1
        assert db.query(User).filter(User.id == owner_a["id"]).one().business_name == "Alpha profile through BizID"
        assert db.query(User).filter(User.parent_business_id == owner_a["id"]).count() == 1
        assert db.query(User).filter(User.parent_business_id == owner_b["id"]).count() == 0
    finally:
        db.close()


def test_staff_session_cannot_use_owner_sync_control_plane():
    owner, owner_headers = _signup("Owner Sync Control")
    staff_name = f"cash_{uuid.uuid4().hex[:8]}"
    create = client.post("/staff", headers=owner_headers, json={
        "username": staff_name, "password": "StaffPass123!", "role": "cashier",
    })
    assert create.status_code in (200, 201), create.text

    staff_login = client.post("/login", json={"username": staff_name, "password": "StaffPass123!"})
    assert staff_login.status_code == 200, staff_login.text
    staff_headers = {"Authorization": f"Bearer {staff_login.json()['token']}"}

    response = client.post("/api/sync/cloud-token", headers=staff_headers, json={"token": "not-accepted"})
    assert response.status_code == 403
    response = client.post("/api/sync/staff-push", headers=staff_headers, json={"staff": []})
    assert response.status_code == 403
    response = client.post("/api/sync/profile-push", headers=staff_headers, json={"business_name": "Hijack"})
    assert response.status_code == 403
    response = client.get("/api/data-transfer/export", headers=staff_headers)
    assert response.status_code == 403


def test_generic_sync_rejects_cloud_authoritative_entities():
    _owner, headers = _signup("Pull Only Guard")
    response = client.post("/api/sync/push", headers=headers, json={
        "changes": [{
            "entity": "b2b_connections", "entity_id": 1, "operation": "INSERT",
            "payload": {"uid": str(uuid.uuid4())}, "created_at": datetime.utcnow().isoformat(),
        }],
    })
    assert response.status_code == 422, response.text


def test_generic_sync_cannot_update_another_business_row():
    owner_a, headers_a = _signup("Sync Alpha")
    owner_b, _headers_b = _signup("Sync Bravo")
    db = SessionLocal()
    try:
        victim = Customer(business_id=owner_b["id"], name="Bravo customer", phone="9999999999")
        db.add(victim)
        db.commit()
        db.refresh(victim)
        payload = {
            "id": victim.id,
            "uid": victim.uid,
            "business_id": owner_a["id"],
            "name": "attempted overwrite",
            "updated_at": datetime.utcnow().isoformat(),
        }
        victim_id = victim.id
    finally:
        db.close()

    response = client.post("/api/sync/push", headers=headers_a, json={
        "changes": [{
            "entity": "customers", "entity_id": victim_id, "operation": "UPDATE",
            "payload": payload, "created_at": datetime.utcnow().isoformat(),
        }],
    })
    assert response.status_code == 403, response.text

    db = SessionLocal()
    try:
        assert db.query(Customer).filter(Customer.id == victim_id).one().name == "Bravo customer"
    finally:
        db.close()


def test_child_parent_uid_must_belong_to_the_authenticated_business():
    owner_a, _headers_a = _signup("Child Alpha")
    owner_b, _headers_b = _signup("Child Bravo")
    db = SessionLocal()
    try:
        foreign_invoice = Invoice(
            business_id=owner_b["id"], invoice_id=f"B-{uuid.uuid4().hex[:8]}",
            customer="Bravo", amount=1, total_amount=1, status="Paid",
        )
        db.add(foreign_invoice)
        db.commit()
        data = {"invoice_uid": foreign_invoice.uid, "invoice_id": foreign_invoice.id}
        assert resolve_parent_fk_uids(
            db, __import__("database.models", fromlist=["InvoiceLineItem"]).InvoiceLineItem,
            data, business_id=owner_a["id"], log_prefix="test",
        ) is True
    finally:
        db.close()


def test_import_clears_a_foreign_tenant_product_reference():
    owner_a, headers_a = _signup("Import Link Alpha")
    owner_b, _headers_b = _signup("Import Link Bravo")
    db = SessionLocal()
    try:
        invoice = Invoice(
            business_id=owner_a["id"], invoice_id=f"A-{uuid.uuid4().hex[:8]}",
            customer="Alpha", amount=10, total_amount=10, status="Paid",
        )
        foreign_product = Product(business_id=owner_b["id"], name="Bravo-only product")
        db.add_all([invoice, foreign_product])
        db.commit()
        db.refresh(invoice)
        db.refresh(foreign_product)
        invoice_id, product_id = invoice.id, foreign_product.id
    finally:
        db.close()

    product_name = f"Imported {uuid.uuid4().hex[:8]}"
    response = client.post("/api/data-transfer/import", headers=headers_a, json={
        "tables": {"invoice_line_items": [{
            "id": 999001, "invoice_id": invoice_id, "product_id": product_id,
            "product_name": product_name, "quantity": 1, "unit_price": 10,
        }]},
    })
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        imported = db.query(InvoiceLineItem).filter(
            InvoiceLineItem.invoice_id == invoice_id,
            InvoiceLineItem.product_name == product_name,
        ).one()
        assert imported.product_id is None
    finally:
        db.close()


@pytest.mark.parametrize("line", [
    {"quantity": -1, "unit_price": 100},
    {"quantity": 0, "unit_price": 100},
    {"quantity": float("nan"), "unit_price": 100},
    {"quantity": 1, "unit_price": -100},
    {"quantity": 1, "unit_price": float("inf")},
])
def test_sale_math_rejects_non_finite_or_non_positive_money_inputs(line):
    with pytest.raises(ValueError):
        billing._compute_line(line, None, intra=True, tax_inclusive=False)


def test_import_refuses_unknown_tables_and_unsafe_pk_mode():
    _owner, headers = _signup("Import Guard")
    unknown = client.post("/api/data-transfer/import", headers=headers, json={
        "tables": {"users": [], "sqlite_master": []},
    })
    assert unknown.status_code == 422

    unsafe = client.post("/api/data-transfer/import?remap_ids=false", headers=headers, json={"tables": {}})
    assert unsafe.status_code == 422
