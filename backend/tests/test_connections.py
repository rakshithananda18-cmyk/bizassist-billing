import os
import sys

# Set test environment database to a temporary file
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"

# Clean up any leftover databases from previous runs before importing main_groq
for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

# Ensure backend folder is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from main_groq import app
from database.db import get_db, SessionLocal
from database.models import User, Product, Inventory
from core.models import B2BConnection, ConnectionCode, B2BOrder

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    # Clean up test database files at session end
    for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass

@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()

def get_auth_headers(username, password):
    resp = client.post("/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}

def test_signup_bizid_generation():
    username = "seller_test_1"
    resp = client.post("/signup", json={
        "username": username,
        "password": "SellerPassword123",
        "business_name": "Test Seller One"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    
    # Retrieve user from database to verify BizID format
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        assert user is not None
        assert user.public_id is not None
        assert user.public_id.startswith("BA-")
        assert len(user.public_id) == 9 # BA- + 6 crockford base32 chars
    finally:
        db.close()

def test_get_my_bizid():
    headers = get_auth_headers("seller_test_1", "SellerPassword123")
    resp = client.get("/bizid", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "public_id" in data
    assert data["public_id"].startswith("BA-")

def test_lookup_bizid():
    # Sign up another user
    client.post("/signup", json={
        "username": "buyer_test_1",
        "password": "BuyerPassword123",
        "business_name": "Test Buyer One"
    })
    
    # Get seller's BizID
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    
    seller_bizid_resp = client.get("/bizid", headers=headers_seller)
    seller_bizid = seller_bizid_resp.json()["public_id"]
    
    # Lookup seller's public profile as buyer
    resp = client.get(f"/bizid/{seller_bizid}", headers=headers_buyer)
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["public_id"] == seller_bizid
    assert profile["business_name"] == "Test Seller One"
    assert "accepts_orders" in profile
    # Verify no credentials or private attributes are returned
    assert "password" not in profile
    assert "role" not in profile
    assert "invoices" not in profile
    assert "inventory" not in profile

def test_connection_code_lifecycle():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    
    # Seller generates join code
    resp = client.post("/connections/code", headers=headers_seller)
    assert resp.status_code == 200
    code_data = resp.json()
    assert "code" in code_data
    assert "expires_at" in code_data
    code = code_data["code"]
    
    # Buyer redeems code
    redeem_resp = client.post("/connections/redeem", json={"code": code}, headers=headers_buyer)
    assert redeem_resp.status_code == 200
    conn_data = redeem_resp.json()
    assert conn_data["status"] == "accepted"
    assert conn_data["buyer_name"] == "Test Buyer One"
    assert conn_data["seller_name"] == "Test Seller One"
    
    # Double redemption should fail
    fail_resp = client.post("/connections/redeem", json={"code": code}, headers=headers_buyer)
    assert fail_resp.status_code == 400
    assert "already been used" in fail_resp.json()["detail"]
    
    # Redeeming for own business should fail
    resp_own = client.post("/connections/code", headers=headers_seller)
    own_code = resp_own.json()["code"]
    fail_own = client.post("/connections/redeem", json={"code": own_code}, headers=headers_seller)
    assert fail_own.status_code == 400
    assert "own business" in fail_own.json()["detail"]
    
    # Expired code should fail
    resp_exp = client.post("/connections/code", headers=headers_seller)
    exp_code = resp_exp.json()["code"]
    
    # Manually expire the code in the DB
    db = SessionLocal()
    try:
        db_code = db.query(ConnectionCode).filter(ConnectionCode.code == exp_code).first()
        db_code.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
        
    fail_exp = client.post("/connections/redeem", json={"code": exp_code}, headers=headers_buyer)
    assert fail_exp.status_code == 400
    assert "expired" in fail_exp.json()["detail"]

def test_direct_connection_via_bizid():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    
    # Get seller's BizID
    seller_bizid_resp = client.get("/bizid", headers=headers_seller)
    seller_bizid = seller_bizid_resp.json()["public_id"]
    
    # Connect buyer to seller using BizID
    connect_resp = client.post("/connections/connect", json={
        "bizid": seller_bizid,
        "connect_as": "buyer"
    }, headers=headers_buyer)
    assert connect_resp.status_code == 200
    conn_data = connect_resp.json()
    assert conn_data["status"] == "accepted"
    assert conn_data["buyer_name"] == "Test Buyer One"
    assert conn_data["seller_name"] == "Test Seller One"
    
    # Connecting to own business should fail
    resp_own = client.post("/connections/connect", json={
        "bizid": seller_bizid,
        "connect_as": "buyer"
    }, headers=headers_seller)
    assert resp_own.status_code == 400
    assert "own business" in resp_own.json()["detail"]
    
    # Connecting with invalid bizid should fail
    resp_invalid = client.post("/connections/connect", json={
        "bizid": "BA-INVALID",
        "connect_as": "buyer"
    }, headers=headers_buyer)
    assert resp_invalid.status_code == 400
    assert "not found" in resp_invalid.json()["detail"]

def test_list_connections():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    resp = client.get("/connections", headers=headers_seller)
    assert resp.status_code == 200
    data = resp.json()
    assert "as_seller" in data
    assert "as_buyer" in data
    assert len(data["as_seller"]) >= 1

def test_catalog_visibility_and_policy():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    
    db = SessionLocal()
    try:
        seller_user = db.query(User).filter(User.username == "seller_test_1").first()
        seller_id = seller_user.id
        seller_bizid = seller_user.public_id
        
        buyer_user = db.query(User).filter(User.username == "buyer_test_1").first()
        buyer_user_id = buyer_user.id
        
        # Setup catalog products for the seller
        p1 = Product(business_id=seller_id, name="Aspirin", selling_price=100.0, wholesale_price=80.0, distributor_price=70.0, category="Medicines", is_active=True)
        p2 = Product(business_id=seller_id, name="Soda", selling_price=50.0, category="Beverages", is_active=True)
        db.add(p1)
        db.add(p2)
        db.commit()
        
        # Setup inventory stock levels
        inv1 = Inventory(business_id=seller_id, product_id=p1.id, stock=15)
        inv2 = Inventory(business_id=seller_id, product_id=p2.id, stock=5)
        db.add(inv1)
        db.add(inv2)
        db.commit()
        
        # Get connection
        conn = db.query(B2BConnection).filter(
            B2BConnection.seller_business_id == seller_id,
            B2BConnection.buyer_business_id == buyer_user_id
        ).first()
        conn_id = conn.id
    finally:
        db.close()
        
    # Check default catalog (exact stock, no discount)
    catalog_resp = client.get(f"/catalog/{seller_bizid}", headers=headers_buyer)
    assert catalog_resp.status_code == 200
    items = catalog_resp.json()["items"]
    assert len(items) == 2
    aspirin = next(it for it in items if it["name"] == "Aspirin")
    soda = next(it for it in items if it["name"] == "Soda")
    assert aspirin["stock"] == 15
    assert soda["stock"] == 5
    assert aspirin["selling_price"] == 100.0
    
    # Update policy to: Stock visibility = band, discount = 10%, category = Medicines
    policy_resp = client.post(f"/connections/{conn_id}/policy", json={
        "price_tier": "wholesale",
        "discount_pct": 10.0,
        "credit_limit": 5000.0,
        "stock_visibility": "band",
        "catalog_category": "Medicines"
    }, headers=headers_seller)
    assert policy_resp.status_code == 200
    
    # Query catalog again
    catalog_resp = client.get(f"/catalog/{seller_bizid}", headers=headers_buyer)
    assert catalog_resp.status_code == 200
    items = catalog_resp.json()["items"]
    
    # Category filter applied (Beverages is excluded)
    assert len(items) == 1
    aspirin = items[0]
    assert aspirin["name"] == "Aspirin"
    # Band stock visibility applied (stock > 10 -> "In Stock")
    assert aspirin["stock"] == "In Stock"
    # 10% discount applied to wholesale price (80 * 0.9 = 72)
    assert aspirin["selling_price"] == 72.0

    # Test distributor tier
    client.post(f"/connections/{conn_id}/policy", json={
        "price_tier": "distributor",
        "discount_pct": 5.0,
        "credit_limit": 5000.0,
        "stock_visibility": "band",
        "catalog_category": "Medicines"
    }, headers=headers_seller)
    catalog_resp = client.get(f"/catalog/{seller_bizid}", headers=headers_buyer)
    items = catalog_resp.json()["items"]
    aspirin = items[0]
    # 5% discount applied to distributor price (70 * 0.95 = 66.5)
    assert aspirin["selling_price"] == 66.5

    # Test stock visibility = hidden
    client.post(f"/connections/{conn_id}/policy", json={
        "price_tier": "standard",
        "discount_pct": 0.0,
        "credit_limit": 0.0,
        "stock_visibility": "hidden",
        "catalog_category": None
    }, headers=headers_seller)
    
    catalog_resp = client.get(f"/catalog/{seller_bizid}", headers=headers_buyer)
    items = catalog_resp.json()["items"]
    aspirin = next(it for it in items if it["name"] == "Aspirin")
    assert aspirin["stock"] is None

def test_b2b_ordering():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    
    db = SessionLocal()
    try:
        seller_user = db.query(User).filter(User.username == "seller_test_1").first()
        seller_bizid = seller_user.public_id
        aspirin = db.query(Product).filter(Product.business_id == seller_user.id, Product.name == "Aspirin").first()
        aspirin_id = aspirin.id
    finally:
        db.close()
        
    # Place valid B2B order
    order_req = {
        "seller_bizid": seller_bizid,
        "items": [
            {"product_id": aspirin_id, "quantity": 5.0}
        ],
        "notes": "Please deliver tomorrow morning"
    }
    resp = client.post("/orders", json=order_req, headers=headers_buyer)
    assert resp.status_code == 200
    order_data = resp.json()
    assert order_data["status"] == "pending"
    assert order_data["seller_bizid"] == seller_bizid
    assert order_data["total_amount"] == 500.0 # 5 * 100
    assert len(order_data["items"]) == 1
    
    # Try invalid product
    order_req_invalid = {
        "seller_bizid": seller_bizid,
        "items": [
            {"product_id": 99999, "quantity": 1.0}
        ]
    }
    resp_fail = client.post("/orders", json=order_req_invalid, headers=headers_buyer)
    assert resp_fail.status_code == 400
    assert "not found in supplier catalogue" in resp_fail.json()["detail"]
    
    # Try negative quantity
    order_req_neg = {
        "seller_bizid": seller_bizid,
        "items": [
            {"product_id": aspirin_id, "quantity": -5.0}
        ]
    }
    resp_neg = client.post("/orders", json=order_req_neg, headers=headers_buyer)
    assert resp_neg.status_code == 400
    assert "greater than zero" in resp_neg.json()["detail"]

def test_order_status_transitions():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    
    # Place order first
    db = SessionLocal()
    try:
        seller_user = db.query(User).filter(User.username == "seller_test_1").first()
        seller_bizid = seller_user.public_id
        aspirin = db.query(Product).filter(Product.business_id == seller_user.id, Product.name == "Aspirin").first()
        aspirin_id = aspirin.id
    finally:
        db.close()
        
    order_resp = client.post("/orders", json={
        "seller_bizid": seller_bizid,
        "items": [{"product_id": aspirin_id, "quantity": 2.0}]
    }, headers=headers_buyer)
    order_id = order_resp.json()["id"]
    
    # Buyer tries to accept order -> fail
    accept_buyer_resp = client.post(f"/orders/{order_id}/status", json={"status": "accepted"}, headers=headers_buyer)
    assert accept_buyer_resp.status_code == 403
    assert "only cancel pending orders" in accept_buyer_resp.json()["detail"]
    
    # Seller accepts order -> success
    accept_seller_resp = client.post(f"/orders/{order_id}/status", json={"status": "accepted"}, headers=headers_seller)
    assert accept_seller_resp.status_code == 200
    assert accept_seller_resp.json()["status"] == "accepted"
    
    # Seller transitions to packed, dispatched -> success
    packed_resp = client.post(f"/orders/{order_id}/status", json={"status": "packed"}, headers=headers_seller)
    assert packed_resp.status_code == 200
    assert packed_resp.json()["status"] == "packed"
    
    # Buyer tries to cancel packed order -> fail
    cancel_fail = client.post(f"/orders/{order_id}/status", json={"status": "cancelled"}, headers=headers_buyer)
    assert cancel_fail.status_code == 400
    assert "after it is packed or shipped" in cancel_fail.json()["detail"]
    
    # Seller rejects order after packed (seller only rejects, never cancels)
    reject_fail = client.post(f"/orders/{order_id}/status", json={"status": "cancelled"}, headers=headers_seller)
    assert reject_fail.status_code == 403
    assert "Sellers reject orders; buyers cancel them" in reject_fail.json()["detail"]

def test_connection_revocation_and_scoping():
    headers_seller = get_auth_headers("seller_test_1", "SellerPassword123")
    headers_buyer = get_auth_headers("buyer_test_1", "BuyerPassword123")
    
    db = SessionLocal()
    try:
        seller_user = db.query(User).filter(User.username == "seller_test_1").first()
        seller_id = seller_user.id
        seller_bizid = seller_user.public_id
        buyer_user = db.query(User).filter(User.username == "buyer_test_1").first()
        
        conn = db.query(B2BConnection).filter(
            B2BConnection.seller_business_id == seller_id,
            B2BConnection.buyer_business_id == buyer_user.id
        ).first()
        conn_id = conn.id
    finally:
        db.close()
        
    # Revoke connection as buyer
    revoke_resp = client.post(f"/connections/{conn_id}/revoke", headers=headers_buyer)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"
    
    # Try browsing catalog now -> fail (403)
    cat_resp = client.get(f"/catalog/{seller_bizid}", headers=headers_buyer)
    assert cat_resp.status_code == 403
    assert "No active connection" in cat_resp.json()["detail"]
    
    # Try placing order -> fail (403)
    order_fail = client.post("/orders", json={
        "seller_bizid": seller_bizid,
        "items": [{"product_id": 1, "quantity": 1.0}]
    }, headers=headers_buyer)
    assert order_fail.status_code == 403
    assert "No active connection" in order_fail.json()["detail"]
