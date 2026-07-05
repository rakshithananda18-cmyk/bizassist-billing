"""
tests/test_signup_phone.py
==========================
A phone number given at registration must land on the profile.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app

client = TestClient(app)


def test_signup_phone_lands_on_profile():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!",
        "business_name": "Phone Co", "phone": "9494747419",
    })
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    prof = client.get("/profile", headers=headers)
    assert prof.status_code == 200, prof.text
    assert prof.json().get("phone") == "9494747419"


def test_signup_without_phone_is_fine():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "No Phone Co",
    })
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/profile", headers=headers).json().get("phone") in (None, "")
