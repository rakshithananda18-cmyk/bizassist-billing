"""
tests/test_local_only_stays_local.py — "Local only" sends nothing to the cloud
================================================================================
Register promises a Local only business "Nothing goes to the cloud". The sync
queue keeps that promise (test_hosting_mode_gate.py), but three side doors did
not, for any business holding a cloud token — and the desktop mints one at
sign-up and at every online sign-in, whatever the mode:

  * the profile push (services/immediate_sync.py),
  * the staff push, password hashes included (core/api/staff.py),
  * the nightly log upload (services/log_uploader.py), which also sent the
    WHOLE log: every business on the computer and every sign-in typed — a
    password typed into the username box too.

Also pinned: a failed sign-in for a username no account has is not logged by
name. A password in the username box is almost never a real username.
"""
import io
import json
import logging
import os
import sys
import tarfile
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from database.db import SessionLocal
from database.models import User
from main_groq import app

client = TestClient(app)


class _RunNow:
    """threading.Thread stand-in: the fire-and-forget push runs inline."""

    def __init__(self, target=None, daemon=None, **_):
        self._target = target

    def start(self):
        self._target()


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _owner(mode):
    """A real owner (via /signup) with hosting_mode `mode` (None = no settings)."""
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": uname, "password": "TestPass123!",
                                     "business_name": "Sri Lakshmi Medicals"})
    assert r.status_code == 200, r.text
    bid, token = r.json()["id"], r.json()["token"]
    with SessionLocal() as s:
        u = s.query(User).filter(User.id == bid).first()
        u.settings = json.dumps({"general": {"hosting_mode": mode}}) if mode else None
        s.commit()
        return {"id": bid, "username": uname, "public_id": u.public_id,
                "headers": {"Authorization": f"Bearer {token}"}}


def _staff_of(owner_id):
    with SessionLocal() as s:
        st = User(username=f"own_{uuid.uuid4().hex[:8]}", password="x", business_name="Sri Lakshmi Medicals",
                  role="cashier", parent_business_id=owner_id)
        s.add(st)
        s.commit()
        return st.id


# ── the one rule ────────────────────────────────────────────────────────────

class TestSyncsToCloud:

    def test_only_local_plus_cloud_counts(self):
        from services.immediate_sync import syncs_to_cloud
        assert syncs_to_cloud(_owner("hybrid")["id"]) is True
        assert syncs_to_cloud(_owner("local")["id"]) is False
        assert syncs_to_cloud(_owner("cloud")["id"]) is False
        assert syncs_to_cloud(_owner(None)["id"]) is False, "no settings means no consent"
        assert syncs_to_cloud(987654321) is False

    def test_staff_follow_their_owner(self):
        from services.immediate_sync import syncs_to_cloud
        assert syncs_to_cloud(_staff_of(_owner("hybrid")["id"])) is True
        assert syncs_to_cloud(_staff_of(_owner("local")["id"])) is False


# ── profile and staff pushes ────────────────────────────────────────────────

@pytest.mark.parametrize("mode, sent", [("hybrid", True), ("local", False)])
def test_profile_push_only_for_local_plus_cloud(mode, sent):
    owner = _owner(mode)
    with patch("services.immediate_sync._IS_LOCAL", True), \
         patch("services.immediate_sync.threading.Thread", _RunNow), \
         patch("services.sync_worker._get_cloud_token", return_value="cloud-token"), \
         patch("httpx.post", return_value=MagicMock(status_code=200)) as post:
        from services.immediate_sync import push_profile_to_cloud
        push_profile_to_cloud(owner["id"], {"gstin": "29ABCDE1234F1Z5"})
    assert post.called is sent


@pytest.mark.parametrize("mode, sent", [("hybrid", True), ("local", False)])
def test_staff_push_only_for_local_plus_cloud(mode, sent):
    owner = _owner(mode)
    with patch("core.api.staff.threading.Thread", _RunNow), \
         patch("services.sync_worker._get_cloud_token", return_value="cloud-token"), \
         patch("httpx.post", return_value=MagicMock(status_code=200, json=lambda: {})) as post:
        from core.api.staff import _push_staff_to_cloud
        _push_staff_to_cloud(owner["id"], [{"staff_login_name": "counter1", "hashed_password": "$2b$..."}])
    assert post.called is sent


# ── the nightly log upload ──────────────────────────────────────────────────

def test_filter_keeps_only_this_business_and_its_tracebacks():
    from services.log_uploader import filter_log_for
    lines = [
        "10:00:00 INFO  app                    [BizId=-] [BOOT] started\n",
        "10:00:01 INFO  auth                   [BizId=-] [AUTH] Failed login for an unknown username\n",
        "10:00:02 INFO  invoices               [BizId=BA-AAAAAA] invoice INV-1 created\n",
        "10:00:03 ERROR sync                   [BizId=BA-AAAAAA] push failed\n",
        "Traceback (most recent call last):\n",
        "  File \"x.py\", line 1\n",
        "10:00:04 INFO  invoices               [BizId=BA-BBBBBB] other business's invoice\n",
        "Traceback for the other business\n",
    ]
    assert filter_log_for("BA-AAAAAA", lines) == lines[2:6]


def _tar_log(data: bytes) -> str:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        assert t.getnames() == ["bizassist.log"], "only this business's log lines - no admin audit"
        return t.extractfile("bizassist.log").read().decode()


def test_daily_upload_sends_only_local_plus_cloud_and_only_their_lines(tmp_path, monkeypatch):
    hybrid, local = _owner("hybrid"), _owner("local")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs" / "backups").mkdir(parents=True)
    (tmp_path / "logs" / "bizassist.log").write_text(
        "09:00:00 INFO  auth                   [BizId=-] [AUTH] Login attempt...\n"
        f"09:00:01 INFO  invoices               [BizId={hybrid['public_id']}] hybrid invoice\n"
        f"09:00:02 INFO  invoices               [BizId={local['public_id']}] local invoice\n",
        encoding="utf-8")
    (tmp_path / "logs" / "admin_audit.jsonl").write_text('{"action": "grant_pro"}\n')
    legacy = tmp_path / "logs" / "backups" / f"logs_biz_{hybrid['public_id']}_20261023_180000.tar.gz"
    legacy.write_bytes(b"whole log of every business")

    sent = []

    def fake_post(url, data=None, files=None, headers=None, timeout=None):
        sent.append((headers["Authorization"], _tar_log(files["file"][1].read())))
        return MagicMock(status_code=200)

    tokens = {hybrid["id"]: "tok-hybrid", local["id"]: "tok-local"}
    with patch("services.log_uploader._get_cloud_token", side_effect=lambda bid: tokens.get(bid)), \
         patch("services.log_uploader.httpx.post", side_effect=fake_post):
        from services.log_uploader import run_daily_log_upload
        run_daily_log_upload()

    assert not legacy.exists(), "a whole-log archive is deleted, never sent"
    assert len(sent) == 1, "the Local only business holds a token but must send nothing"
    auth, body = sent[0]
    assert auth == "Bearer tok-hybrid"
    assert "hybrid invoice" in body
    assert "local invoice" not in body and "Login attempt" not in body
    assert os.listdir(tmp_path / "logs" / "backups") == [], "sent archives are removed"


# ── what the log says about a failed sign-in ────────────────────────────────

def test_failed_sign_in_logs_a_name_only_when_an_account_has_it():
    owner = _owner("local")
    typed = f"Pw{uuid.uuid4().hex[:9]}!"           # what a password in the username box looks like
    log = logging.getLogger("bizassist.auth")
    cap, level = _Lines(), log.level
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    try:
        assert client.post("/login", json={"username": typed, "password": "x"}).status_code == 401
        assert client.post("/login", json={"username": owner["username"], "password": "Wrong123x!"}).status_code == 401
    finally:
        log.removeHandler(cap)
        log.setLevel(level)
    text = "\n".join(cap.lines)
    assert typed not in text
    assert "Failed login for an unknown username" in text
    assert f"Failed login for username '{owner['username']}'" in text


# ── "Download logs" ─────────────────────────────────────────────────────────

class TestDiagnosticsLogDownload:
    """On the cloud the server log covers every customer, so it was a data
    leak that any signed-in user could download it from Settings."""

    def _cashier_headers(self, owner):
        uname = f"own_{uuid.uuid4().hex[:8]}"
        r = client.post("/staff", headers=owner["headers"],
                        json={"username": uname, "password": "Password123!", "role": "cashier"})
        assert r.status_code == 201, r.text
        login = client.post("/login", json={"username": uname, "password": "Password123!"})
        return {"Authorization": f"Bearer {login.json()['token']}"}

    def test_desktop_owner_can_download_staff_cannot(self):
        owner = _owner("local")
        assert client.get("/diagnostics/logs", headers=owner["headers"]).status_code == 200
        assert client.get("/diagnostics/logs", headers=self._cashier_headers(owner)).status_code == 403

    def test_on_the_cloud_only_the_platform_admin_can(self):
        from database.db import engine
        from routes.auth import create_access_token
        owner, admin = _owner("local"), _owner("local")
        with SessionLocal() as s:
            u = s.query(User).filter(User.id == admin["id"]).first()
            u.role = "admin"
            s.commit()
            admin_token = create_access_token({
                "id": u.id, "user_id": u.id, "username": u.username, "public_id": u.public_id,
                "role": "admin", "tv": u.token_version or 0,
            })
        # Only the route's own question "is this the cloud?" is answered yes:
        # relabelling the whole engine as Postgres sends sign-in down
        # Postgres-only paths on this SQLite test database.
        with patch("routes.feedback._on_cloud_db", return_value=True):
            r = client.get("/diagnostics/logs", headers=owner["headers"])
            assert r.status_code == 403
            assert "only the platform admin" in r.json()["detail"]
            assert client.get("/diagnostics/logs",
                              headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
