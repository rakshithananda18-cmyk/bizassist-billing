import os
import sys
import uuid
import json
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Customer, Product, Invoice, SyncQueue, SyncLog, ConflictLog, User
from services.sync_worker import run_hybrid_sync, trigger_sync_run

client = TestClient(app)

def _signup(business_name):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"], "username": uname}

def test_sync_lifecycle():
    # 1. Sign up test business (local)
    local_user = _signup("Local POS Sync Shop")
    
    # 2. Toggle to Hybrid mode
    r_settings = client.put("/settings", headers=local_user["headers"], json={
        "general": {"hosting_mode": "hybrid", "sync_interval": 10}
    })
    assert r_settings.status_code == 200
    
    # 3. Create a Customer directly. Trigger hook should write to SyncQueue
    db = SessionLocal()
    try:
        cust = Customer(
            business_id=local_user["bid"],
            name="Bob Sync Tester",
            phone="9999999999",
            updated_at=datetime.utcnow()
        )
        db.add(cust)
        db.commit()
        cust_id = cust.id
    finally:
        db.close()

    # 4. Assert SyncQueue has a pending record for customers
    db = SessionLocal()
    try:
        pending_cust = (
            db.query(SyncQueue)
            .filter(
                SyncQueue.business_id == local_user["bid"],
                SyncQueue.entity == "customers",
                SyncQueue.synced_at.is_(None)
            )
            .all()
        )
        assert len(pending_cust) == 1
        assert pending_cust[0].entity == "customers"
        assert pending_cust[0].entity_id == cust_id
        assert pending_cust[0].operation == "INSERT"
    finally:
        db.close()

    # 5. Check local queue-depth endpoint
    r_depth = client.get("/api/sync/queue-depth", headers=local_user["headers"])
    assert r_depth.status_code == 200, r_depth.text
    depth_data = r_depth.json()
    # 2 items: 1 for settings update (users table), 1 for customer
    assert depth_data["pending_count"] == 2

    # 7. Extract the local customer change and push to cloud push endpoint
    db = SessionLocal()
    try:
        queue_item = (
            db.query(SyncQueue)
            .filter(
                SyncQueue.business_id == local_user["bid"],
                SyncQueue.entity == "customers",
                SyncQueue.synced_at.is_(None)
            )
            .first()
        )
        payload_dict = json.loads(queue_item.payload)
        entity = queue_item.entity
        entity_id = queue_item.entity_id
        operation = queue_item.operation
        created_at_iso = queue_item.created_at.isoformat()
        
        # To simulate the cloud space not having this customer yet, we temporarily delete it from the shared DB
        cust = db.query(Customer).filter(Customer.id == cust_id).first()
        if cust:
            # Disable sync hooks temporarily so deleting this doesn't queue a delete operation
            from database.db import sync_disabled_var
            token = sync_disabled_var.set(True)
            try:
                db.delete(cust)
                db.commit()
            finally:
                sync_disabled_var.reset(token)
    finally:
        db.close()

    push_body = {
        "changes": [{
            "entity": entity,
            "entity_id": entity_id,
            "operation": operation,
            "payload": payload_dict,
            "created_at": created_at_iso
        }]
    }

    r_push = client.post("/api/sync/push", headers=local_user["headers"], json=push_body)
    assert r_push.status_code == 200, r_push.text
    assert r_push.json()["applied"] == 1

    # Verify customer exists in cloud
    db = SessionLocal()
    try:
        cloud_cust = (
            db.query(Customer)
            .filter(Customer.business_id == local_user["bid"], Customer.name == "Bob Sync Tester")
            .first()
        )
        assert cloud_cust is not None
        assert cloud_cust.phone == "9999999999"
    finally:
        db.close()

    # 8. Test LWW conflict on cloud: update cloud customer to make it newer
    db = SessionLocal()
    try:
        cloud_cust = (
            db.query(Customer)
            .filter(Customer.business_id == local_user["bid"], Customer.name == "Bob Sync Tester")
            .first()
        )
        # Disable sync hooks so this manual simulated cloud write isn't queued locally
        from database.db import sync_disabled_var
        token = sync_disabled_var.set(True)
        try:
            cloud_cust.phone = "1111111111"
            cloud_cust.updated_at = datetime.utcnow() + timedelta(hours=1) # force future cloud write
            db.commit()
        finally:
            sync_disabled_var.reset(token)
    finally:
        db.close()

    # Attempt to push older local update (same bob, phone="2222222222" but older updated_at)
    payload_dict["phone"] = "2222222222"
    payload_dict["updated_at"] = (datetime.utcnow() - timedelta(hours=1)).isoformat()

    push_body_conflict = {
        "changes": [{
            "entity": "customers",
            "entity_id": cust_id,
            "operation": "UPDATE",
            "payload": payload_dict,
            "created_at": datetime.utcnow().isoformat()
        }]
    }

    r_push_conflict = client.post("/api/sync/push", headers=local_user["headers"], json=push_body_conflict)
    assert r_push_conflict.status_code == 200, r_push_conflict.text
    # Should skip application since cloud version is newer
    assert r_push_conflict.json()["applied"] == 0

    # Verify cloud customer retained newer phone and a conflict log was written
    db = SessionLocal()
    try:
        cloud_cust_final = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cloud_cust_final.phone == "1111111111"  # cloud phone wins
        
        conflict = db.query(ConflictLog).filter(ConflictLog.business_id == local_user["bid"]).first()
        assert conflict is not None
        assert conflict.entity == "customers"
        assert conflict.resolution == "cloud_won"
    finally:
        db.close()

    # 9. Test GET /api/sync/pull endpoint
    r_pull = client.get(
        "/api/sync/pull",
        headers=local_user["headers"],
        params={"last_sync_at": (datetime.utcnow() - timedelta(minutes=5)).isoformat()}
    )
    assert r_pull.status_code == 200, r_pull.text
    pull_data = r_pull.json()
    assert "customers" in pull_data["changes"]
    assert len(pull_data["changes"]["customers"]) == 1
    assert pull_data["changes"]["customers"][0]["phone"] == "1111111111"


def test_sync_push_rejects_append_only_delete():
    owner = _signup("Append Only Sync Shop")
    db = SessionLocal()
    try:
        inv = Invoice(
            business_id=owner["bid"],
            invoice_id=f"SYNC-DEL-{uuid.uuid4().hex[:6]}",
            customer="Blocked Delete Customer",
            invoice_date="2026-07-02",
            amount=100.0,
            total_amount=100.0,
            status="Pending",
        )
        db.add(inv)
        db.commit()
        invoice_id = inv.id
    finally:
        db.close()

    delete_body = {
        "changes": [{
            "entity": "invoices",
            "entity_id": invoice_id,
            "operation": "DELETE",
            "payload": {"id": invoice_id, "business_id": owner["bid"]},
            "created_at": datetime.utcnow().isoformat(),
        }]
    }

    resp = client.post("/api/sync/push", headers=owner["headers"], json=delete_body)
    assert resp.status_code == 422, resp.text
    assert "append-only" in resp.json()["detail"].lower()

    db = SessionLocal()
    try:
        still_there = (
            db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.business_id == owner["bid"])
            .first()
        )
        assert still_there is not None
        assert still_there.invoice_id.startswith("SYNC-DEL-")
    finally:
        db.close()
