import os
import sys

# Set test environment database to a temporary file and mock api keys
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

# Clean up any leftover databases from previous runs before importing main_groq
for db_path in ["test_bizassist.db", "backend/test_bizassist.db"]:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

# Ensure backend folder is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main_groq import app
from services.query_router import classify
from services.auth import hash_password, verify_password

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

def test_query_classification():
    # Direct database queries
    assert classify("how many invoices")[0] == "DIRECT"
    assert classify("total revenue")[0] == "DIRECT"
    assert classify("who is overdue")[0] == "DIRECT"
    assert classify("low stock")[0] == "DIRECT"
    assert classify("medicines expiring")[0] == "DIRECT"
    assert classify("dashboard overview")[0] == "DIRECT"

    # AI reasoning queries
    assert classify("what business strategy should I adopt?")[0] == "AI"
    assert classify("how can I increase my sales?")[0] == "AI"
    assert classify("who is my most reliable supplier?")[0] == "AI"

def test_password_hashing():
    pwd = "mysecretpassword"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_unauthenticated_access():
    # Protected endpoints should return 401 Unauthorized
    protected_endpoints = [
        "/admin/businesses",
        "/dashboard-summary",
        "/database",
        "/top-customers",
        "/payments",
        "/clients",
        "/uploads"
    ]
    for endpoint in protected_endpoints:
        response = client.get(endpoint)
        assert response.status_code == 401

def test_auth_flow():
    # Login with seeded test users (see main_groq.py run_migrations_and_seed)
    response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["username"] == "pharmacy"
    assert data["business_name"] == "MediCare Pharmacy"

    # Invalid login
    response = client.post("/login", json={
        "username": "pharmacy",
        "password": "wrongpassword"
    })
    assert response.status_code == 401

    # Signup flow
    response = client.post("/signup", json={
        "username": "newuser",
        "password": "newpassword123",
        "business_name": "New Retail Shop"
    })
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["username"] == "newuser"
    assert data["business_name"] == "New Retail Shop"

    # Duplicate username signup
    response = client.post("/signup", json={
        "username": "newuser",
        "password": "anotherpassword",
        "business_name": "Another Shop"
    })
    assert response.status_code == 400

def test_authorized_endpoints():
    # First, authenticate to get a token
    login_response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify protected endpoints return 200
    response = client.get("/dashboard-summary", headers=headers)
    assert response.status_code == 200
    summary = response.json()
    assert "total_revenue" in summary
    assert "invoice_count" in summary
    assert "inventory_count" in summary

    response = client.get("/database", headers=headers)
    assert response.status_code == 200
    db_data = response.json()
    assert "invoices" in db_data
    assert "inventory" in db_data
    assert "uploads" in db_data

    response = client.get("/top-customers", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    response = client.get("/payments", headers=headers)
    assert response.status_code == 200
    payments = response.json()
    assert "payments" in payments
    assert "invoice_dues" in payments

    response = client.get("/clients", headers=headers)
    assert response.status_code == 200
    clients_data = response.json()
    assert "clients" in clients_data

@patch("main_groq.client.chat.completions.create")
def test_ask_ai_flow(mock_chat_create):
    # Mock LLM API response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Mocked LLM answer about sales strategy."))
    ]
    mock_chat_create.return_value = mock_response

    # Login to get valid session
    login_response = client.post("/login", json={
        "username": "pharmacy",
        "password": "pharmacy123"
    })
    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # DIRECT path ask
    response = client.post("/ask", json={"message": "how many invoices"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["source"] == "db"

    # AI path ask
    response = client.post("/ask", json={"message": "which strategy should I use?"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ai"
    assert "Mocked LLM answer" in data["response"]
