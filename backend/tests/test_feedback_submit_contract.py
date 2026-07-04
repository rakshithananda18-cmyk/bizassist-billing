"""
tests/test_feedback_submit_contract.py  (audit T1, backend half)
================================================================
Guards the support-feedback endpoint contract that the frontend depends on
(Support.jsx posts multipart form fields `message` + `attach_logs`). The
original bug was a doubled URL on the CLIENT (authFetch already prepends
API_BASE); this test locks the SERVER contract so the endpoint stays reachable
and parses the form the client sends.

Note: on a local (sqlite) backend, /feedback/submit forwards to the cloud and
returns 400 "Cloud integration is not enabled" when no cloud token exists —
that is the expected local path and still proves the route + form parsing work
(as opposed to 404 route-missing or 422 form-mismatch).
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


def _signup():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Support Co",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_feedback_submit_requires_auth():
    r = client.post("/feedback/submit", data={"message": "hi", "attach_logs": "false"})
    assert r.status_code in (401, 403), r.text


def test_feedback_submit_accepts_form_contract():
    headers = _signup()
    r = client.post(
        "/feedback/submit",
        headers=headers,
        data={"message": "Something broke", "attach_logs": "false"},
    )
    # Route exists (not 404) and form parsed (not 422). On sqlite it reaches the
    # cloud-forward branch and returns 400 "Cloud integration is not enabled".
    assert r.status_code not in (404, 422), r.text
    assert r.status_code in (200, 400), r.text
    if r.status_code == 400:
        assert "cloud" in (r.json().get("detail", "").lower())
