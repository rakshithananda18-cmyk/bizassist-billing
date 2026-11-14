"""Real installation-level diagnostics delivery, consent and retention scenarios."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import db as database
from database.models import Base, RevokedSession, SpentTicket, User
from services import sync_policy, sync_worker, telemetry_relay as relay
from services.dates import utc_now


@pytest.fixture
def installation(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(sync_worker, "SessionLocal", sessions)
    monkeypatch.setattr(sync_worker, "engine", engine)
    monkeypatch.setattr(sync_worker, "_TOKEN_FILE", tmp_path / "cloud_sync_tokens.json")
    monkeypatch.setattr(sync_worker, "_TOKEN_STORE_LAST_STATE", None)
    for name in ("_REFRESH_BACKOFF", "_REFRESH_FAILURES", "_SELF_SIGNED_REJECTED",
                 "_PLAN_BLOCKED", "_PULL_AUTH_BLOCKED"):
        monkeypatch.setattr(sync_worker, name, {})
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setenv("TELEMETRY_RELAY", "1")
    log = tmp_path / "logs" / "telemetry.jsonl"
    log.parent.mkdir()
    monkeypatch.setattr(relay, "_TELEMETRY_FILE", log)
    monkeypatch.setattr(relay, "_OFFSET_FILE", log.parent / ".telemetry_relay_offset")
    monkeypatch.setattr(relay, "_BUSINESS_DIR", log.parent / "businesses")
    owners, tokens = {}, {}
    with sessions() as db:
        for name in ("first", "second", "local"):
            owner = User(username=f"diagnostics-{name}", password="synthetic", role="owner",
                         public_id=f"BA-DIAG-{name}", settings=json.dumps({"general": {
                             "hosting_mode": "local" if name == "local" else "hybrid",
                             "diagnostic_upload_enabled": True}}))
            db.add(owner)
            db.flush()
            owners[name] = owner.id
        db.commit()
    for name, bid in owners.items():
        tokens[name] = jwt.encode({"id": 1000 + bid, "user_id": 1000 + bid,
                                  "public_id": f"BA-DIAG-{name}", "role": "owner",
                                  "exp": utc_now() + timedelta(days=1)},
                                 "synthetic-cloud-key", algorithm="HS256")
        sync_worker.store_cloud_token(bid, tokens[name])
    try:
        yield SimpleNamespace(sessions=sessions, owners=owners, tokens=tokens, log=log)
    finally:
        engine.dispose()


def _event(name, event="invoice.changed", **extra):
    return {"bizid": f"BA-DIAG-{name}", "event": event, **extra}


def _write(log, records, suffix="", newline="\n"):
    body = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records) + suffix
    log.write_text(body.replace("\n", newline), encoding="utf-8", newline="")
    return log.read_bytes()


class _Response:
    def __init__(self, status=202):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_batches_keep_business_credentials_separate_and_resume_complete_unicode_lines(installation, monkeypatch, newline):
    delivered = []

    def send(request, timeout):
        delivered.append((request.get_header("Authorization"), json.loads(request.data)))
        assert timeout == 15
        return _Response()

    monkeypatch.setattr(relay.urllib.request, "urlopen", send)
    records = [_event("first", f"invoice-{i}-₹") for i in range(401)]
    records += [_event("second"), {"event": "unattributed"},
                _event("first", relayed_at="already-imported")]
    prefix = _write(installation.log, records, newline=newline)
    with installation.log.open("a", encoding="utf-8", newline="") as stream:
        stream.write(f'{newline}not-json{newline}' + '{"bizid":"BA-DIAG-first","event":"partial-₹"')
    relay.run_telemetry_relay()

    assert [len(body["records"]) for _, body in delivered] == [400, 1, 1]
    for auth, body in delivered:
        business = body["records"][0]["bizid"].removeprefix("BA-DIAG-")
        assert auth == f"Bearer {installation.tokens[business]}"
        assert {row["bizid"] for row in body["records"]} == {f"BA-DIAG-{business}"}
        assert body["relay_device"].startswith("local-")
    assert relay._read_offset() == len(prefix) + len(f"{newline}not-json{newline}".encode())
    relay.run_telemetry_relay()
    assert len(delivered) == 3, "an incomplete trailing record must remain pending"
    with installation.log.open("a", encoding="utf-8", newline="") as stream:
        stream.write("}" + newline)
    relay.run_telemetry_relay()
    assert delivered[-1][1]["records"] == [_event("first", "partial-₹")]
    assert relay._read_offset() == installation.log.stat().st_size
    relay.run_telemetry_relay()
    assert len(delivered) == 4, "a fully acknowledged file must not be sent again"


@pytest.mark.parametrize("failure", [503, "offline"])
def test_failed_business_batch_holds_shared_cursor_until_every_business_is_accepted(installation, monkeypatch, failure):
    _write(installation.log, [_event("first"), _event("second")])
    sent = []

    def fail_second(request, **kwargs):
        records = json.loads(request.data)["records"]
        sent.append(records)
        if records[0]["bizid"] == "BA-DIAG-second":
            if failure == "offline":
                raise OSError("synthetic disconnected network")
            return _Response(failure)
        return _Response()

    monkeypatch.setattr(relay.urllib.request, "urlopen", fail_second)
    relay.run_telemetry_relay()
    assert len(sent) == 2
    assert relay._read_offset() == 0, "partial delivery cannot acknowledge unsent diagnostics"
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: _Response())
    relay.run_telemetry_relay()
    assert relay._read_offset() == installation.log.stat().st_size


def test_consent_changed_after_authorization_prevents_network_and_preserves_pending_events(installation, monkeypatch):
    _write(installation.log, [_event("first")])
    policy = sync_policy.cloud_egress_allowed
    calls = []

    def revoke_after_check(bid, **kwargs):
        allowed = policy(bid, **kwargs)
        calls.append(bid)
        if len(calls) == 2:
            with installation.sessions() as db:
                owner = db.get(User, bid)
                value = json.loads(owner.settings)
                value["general"]["hosting_mode"] = "local"
                owner.settings = json.dumps(value)
                db.commit()
        return allowed

    monkeypatch.setattr(sync_policy, "cloud_egress_allowed", revoke_after_check)
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("revoked diagnostics consent sent data"))
    relay.run_telemetry_relay()
    assert len(calls) == 3
    assert relay._read_offset() == 0
    assert sync_worker._load_token_map()[str(installation.owners["first"])] == installation.tokens["first"]


@pytest.mark.parametrize("records", [
    [_event("first"), _event("second")], [_event("local")],
    [{"bizid": "BA-NOT-REGISTERED"}], [{"bizid": None}], [{"bizid": ""}],
])
def test_unbound_mixed_or_local_only_batches_never_leave_installation(installation, monkeypatch, records):
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unconsented batch sent"))
    assert relay._post_import(records, installation.tokens["first"]) is False


@pytest.mark.parametrize("saved_offset", ["corrupted", "99999999"])
def test_rotated_file_and_corrupt_cursor_replay_instead_of_losing_new_events(installation, monkeypatch, saved_offset):
    _write(installation.log, [_event("first")])
    relay._OFFSET_FILE.write_text(saved_offset)
    sent = []
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda request, **kwargs: sent.append(request) or _Response())
    monkeypatch.setattr("platform.node", lambda: (_ for _ in ()).throw(OSError("hostname unavailable")))
    relay.run_telemetry_relay()
    assert len(sent) == 1
    assert json.loads(sent[0].data)["relay_device"] == "local-unknown"
    assert relay._read_offset() == installation.log.stat().st_size


def test_cursor_write_failure_retries_already_accepted_events_without_skipping(installation, monkeypatch):
    _write(installation.log, [_event("first")])
    original_write = Path.write_text
    sent = []

    def unavailable(path, *args, **kwargs):
        if path == relay._OFFSET_FILE:
            raise OSError("synthetic full disk")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", unavailable)
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda request, **kwargs: sent.append(request) or _Response())
    relay.run_telemetry_relay()
    assert relay._read_offset() == 0
    relay.run_telemetry_relay()
    assert len(sent) == 2
    monkeypatch.setattr(Path, "write_text", original_write)
    relay.run_telemetry_relay()
    assert relay._read_offset() == installation.log.stat().st_size


def test_retention_keeps_recent_events_and_auth_grace_period_without_relaying_old_bytes(installation, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    _write(installation.log, [_event("first", received_at=stale), _event("first", received_at=recent)])
    with installation.log.open("a", encoding="utf-8") as stream:
        stream.write("invalid-old-record\n")
    business_log = relay._BUSINESS_DIR / "BA-DIAG-first" / "telemetry.jsonl"
    business_log.parent.mkdir(parents=True)
    _write(business_log, [_event("first", received_at=stale), _event("first", received_at=recent)])
    with installation.sessions() as db:
        db.add_all([SpentTicket(digest="expired", expires_at=utc_now() - timedelta(hours=2)),
                    SpentTicket(digest="grace", expires_at=utc_now() - timedelta(minutes=30)),
                    RevokedSession(sid="expired", expires_at=utc_now() - timedelta(hours=2)),
                    RevokedSession(sid="fresh", expires_at=utc_now() + timedelta(hours=1))])
        db.commit()
    monkeypatch.setenv("TELEMETRY_RETENTION_DAYS", "invalid-use-default")
    relay.run_telemetry_retention()
    assert json.loads(installation.log.read_text())["received_at"] == recent
    assert json.loads(business_log.read_text())["received_at"] == recent
    assert relay._read_offset() == installation.log.stat().st_size
    with installation.sessions() as db:
        assert db.get(SpentTicket, "expired") is None
        assert db.get(SpentTicket, "grace") is not None
        assert db.get(RevokedSession, "expired") is None
        assert db.get(RevokedSession, "fresh") is not None
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("retention replayed acknowledged diagnostics"))
    relay.run_telemetry_relay()


def test_retention_rewrite_failure_keeps_original_events(installation, monkeypatch):
    body = _write(installation.log, [_event("first", received_at="2000-01-01")])
    monkeypatch.setattr(Path, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk unavailable")))
    assert relay._trim_jsonl(installation.log, "2020-01-01") == 0
    assert installation.log.read_bytes() == body


def test_database_failure_holds_cursor_and_does_not_guess_diagnostic_identity(installation, monkeypatch):
    _write(installation.log, [_event("first")])
    monkeypatch.setattr(database, "SessionLocal", lambda: (_ for _ in ()).throw(OSError("database unavailable")))
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("identity lookup failure sent data"))
    relay.run_telemetry_relay()
    assert relay._read_offset() == 0


def test_already_relayed_and_malformed_lines_are_consumed_without_import_loops(installation, monkeypatch):
    _write(installation.log, [_event("first", relayed_at="already-delivered")], suffix="not-json\n\n")
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("diagnostics loop was relayed"))
    relay.run_telemetry_relay()
    assert relay._read_offset() == installation.log.stat().st_size


def test_unreadable_diagnostics_preserve_offset_and_do_not_report_success(installation, monkeypatch):
    _write(installation.log, [_event("first")])
    original_open = Path.open

    def denied(path, *args, **kwargs):
        if path == installation.log:
            raise OSError("synthetic unreadable diagnostics")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unreadable diagnostics sent"))
    relay.run_telemetry_relay()
    assert relay._read_offset() == 0
    assert relay._trim_jsonl(installation.log, "2020-01-01") == 0


def test_auth_retention_database_failure_does_not_prevent_local_log_retention(installation, monkeypatch):
    _write(installation.log, [_event("first", received_at="2000-01-01")])
    monkeypatch.setattr(database, "SessionLocal", lambda: (_ for _ in ()).throw(OSError("database unavailable")))
    relay.run_telemetry_retention()
    assert installation.log.read_bytes() == b""
    assert relay._read_offset() == 0


@pytest.mark.parametrize("cloud,enabled", [(True, True), (False, False)])
def test_relay_never_starts_on_cloud_or_when_disabled(installation, monkeypatch, cloud, enabled):
    _write(installation.log, [_event("first")])
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test" if cloud else "sqlite:///test.db")
    monkeypatch.setenv("TELEMETRY_RELAY", "1" if enabled else "0")
    monkeypatch.setattr(relay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("disabled relay sent data"))
    relay.run_telemetry_relay()
    assert not relay._OFFSET_FILE.exists()
