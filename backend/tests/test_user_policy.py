import os
import sys
import uuid
import pytest
from fastapi.testclient import TestClient

# Ensure backend path is in sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from main_groq import app

client = TestClient(app)

def test_signup_policy_blocks_test_prefixes_on_non_test_db(monkeypatch):
    # Simulate running on a production/development database (without "test" in the URL)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./prod_bizassist.db")
    
    # Try to signup with test prefixes
    test_prefixes = ["own_", "test_", "idem_", "pull_", "u_", "o_", "biz_test_", "rec_"]
    
    for prefix in test_prefixes:
        uname = f"{prefix}{uuid.uuid4().hex[:6]}"
        resp = client.post("/signup", json={
            "username": uname,
            "password": "TestPassword123!",
            "business_name": "Test Company"
        })
        # Must be blocked on non-test DB
        assert resp.status_code == 400
        assert "Test user registration is not allowed on this database" in resp.json()["detail"]

def test_signup_policy_allows_test_prefixes_on_test_db(monkeypatch):
    # Ensure DATABASE_URL has "test" in it (default test database)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_bizassist.db")
    
    # Sign up should go through (or fail with database constraints/existing, but not blocked by the prefix policy)
    uname = f"biz_test_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": uname,
        "password": "TestPassword123!",
        "business_name": "Test Company"
    })
    # If the user creation goes through, it will return 200
    assert resp.status_code == 200
    assert resp.json()["username"] == uname
