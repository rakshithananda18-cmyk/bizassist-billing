"""
tests/test_profile_is_premium.py  (audit T8)
============================================
The premium flag must be exposed on /profile so the frontend can gate the
cloud-sync nudges and the web "local-only" notice. New accounts default to
free (is_premium == False); flipping the column is reflected on the next read.
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
from database.db import SessionLocal
from database.models import User

client = TestClient(app)


def _signup():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Premium Co",
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return uname, {"Authorization": f"Bearer {b['token']}"}


def test_profile_exposes_is_premium_default_false():
    _, headers = _signup()
    r = client.get("/profile", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "is_premium" in body, "profile must expose is_premium for gating"
    assert body["is_premium"] is False, "new accounts default to free tier"


def test_profile_reflects_premium_when_set():
    uname, headers = _signup()
    # Flip the flag directly (simulating an upgrade / admin grant).
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        assert u is not None
        u.is_premium = True
        db.commit()
    finally:
        db.close()

    r = client.get("/profile", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_premium"] is True
