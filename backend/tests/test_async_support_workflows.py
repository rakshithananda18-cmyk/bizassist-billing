"""Support uploads keep bounds, tenant ownership and retry evidence under faults."""
import asyncio
import io
import json
import tarfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers
from starlette.requests import Request

from database import db as database
from database.models import Base, ClientLogArchive, User, UserFeedback
from routes import feedback, telemetry
from services import log_uploader, sync_worker
from services.realtime import RealtimeManager


IDENTITY = {"id": 71, "user_id": 71, "username": "support-owner", "role": "enterprise",
            "public_id": "SUPPORT-BIZ"}


def upload(data=b"support archive", **changes):
    options = {"filename": "support.tar.gz", "file": io.BytesIO(data),
               "headers": Headers({"content-type": "application/gzip"})}
    options.update(changes)
    return UploadFile(**options)


@pytest.mark.anyio
async def test_support_archive_streams_to_its_exact_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "_MAX_FEEDBACK_UPLOAD_BYTES", 8)
    monkeypatch.setattr(feedback, "_UPLOAD_CHUNK_BYTES", 3)
    target = tmp_path / "accepted.tar.gz"
    await feedback._store_bounded_log_upload(upload(b"12345678"), target)
    assert target.read_bytes() == b"12345678"


@pytest.mark.anyio
async def test_oversize_support_archive_removes_its_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "_MAX_FEEDBACK_UPLOAD_BYTES", 8)
    monkeypatch.setattr(feedback, "_UPLOAD_CHUNK_BYTES", 3)
    target = tmp_path / "oversize.tar.gz"
    with pytest.raises(HTTPException) as error:
        await feedback._store_bounded_log_upload(upload(b"123456789"), target)
    assert error.value.status_code == 413
    assert not target.exists()


@pytest.mark.anyio
async def test_exclusive_creation_cannot_remove_an_existing_archive(tmp_path):
    target = tmp_path / "existing.tar.gz"
    target.write_bytes(b"previous evidence")
    with pytest.raises(FileExistsError):
        await feedback._store_bounded_log_upload(upload(), target)
    assert target.read_bytes() == b"previous evidence"


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [OSError("upload disconnected"), asyncio.CancelledError()])
async def test_failed_or_cancelled_upload_cleans_partial_evidence(tmp_path, failure):
    class Interrupted:
        first = True

        async def read(self, size):
            if self.first:
                self.first = False
                return b"first chunk"
            raise failure

    target = tmp_path / "interrupted.tar.gz"
    with pytest.raises(type(failure)):
        await feedback._store_bounded_log_upload(Interrupted(), target)
    assert not target.exists()


@pytest.fixture
def local_support(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(database, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(sync_worker, "_get_cloud_token", lambda bid: "scoped-test-token" if bid == 71 else None)
    monkeypatch.setattr(sync_worker, "CLOUD_URL", "https://support-cloud.example")
    original_client = httpx.AsyncClient
    calls = []

    def install_response(status=200, failure=None):
        def respond(request):
            calls.append(request)
            if failure:
                raise failure
            return httpx.Response(status, text="cloud response")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original_client(
            transport=httpx.MockTransport(respond), **kw))

    install_response()
    return SimpleNamespace(root=tmp_path, calls=calls, install_response=install_response)


@pytest.mark.anyio
async def test_local_feedback_uses_async_form_request_bound_to_cloud_credential(local_support):
    result = await feedback.submit_merchant_feedback("Please help", False, None, IDENTITY)
    assert result["ok"]
    request = local_support.calls[0]
    assert str(request.url) == "https://support-cloud.example/feedback/submit"
    assert request.headers["authorization"] == "Bearer scoped-test-token"
    assert request.content == b"message=Please+help&attach_logs=false"


@pytest.mark.anyio
async def test_successful_feedback_upload_deletes_only_its_sent_archive(local_support, monkeypatch):
    archive = local_support.root / "sent.tar.gz"
    archive.write_bytes(b"business support bytes")
    other = local_support.root / "other-business.tar.gz"
    other.write_bytes(b"do not delete")
    monkeypatch.setattr(log_uploader, "archive_logs", lambda bid: str(archive))
    await feedback.submit_merchant_feedback("Help", True, None, IDENTITY)
    assert b"business support bytes" in local_support.calls[0].content
    assert not archive.exists()
    assert other.read_bytes() == b"do not delete"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403, 413, 429, 503])
async def test_cloud_rejection_preserves_unsent_archive_and_status(local_support, monkeypatch, status):
    archive = local_support.root / "retry.tar.gz"
    archive.write_bytes(b"retry evidence")
    monkeypatch.setattr(log_uploader, "archive_logs", lambda bid: str(archive))
    local_support.install_response(status=status)
    with pytest.raises(HTTPException) as error:
        await feedback.submit_merchant_feedback("Help", True, None, IDENTITY)
    assert error.value.status_code == (502 if status in {401, 403} else status)
    assert not error.value.headers
    assert archive.read_bytes() == b"retry evidence"


@pytest.mark.anyio
async def test_network_failure_preserves_archive_without_exposing_network_details(local_support, monkeypatch):
    archive = local_support.root / "offline.tar.gz"
    archive.write_bytes(b"offline evidence")
    monkeypatch.setattr(log_uploader, "archive_logs", lambda bid: str(archive))
    local_support.install_response(failure=httpx.ConnectError("private server details"))
    with pytest.raises(HTTPException) as error:
        await feedback.submit_merchant_feedback("Help", True, None, IDENTITY)
    assert error.value.status_code == 503
    assert "private server" not in error.value.detail
    assert archive.read_bytes() == b"offline evidence"


@pytest.mark.anyio
async def test_local_oversize_archive_is_not_uploaded(local_support, monkeypatch):
    archive = local_support.root / "too-big.tar.gz"
    archive.write_bytes(b"123456789")
    monkeypatch.setattr(feedback, "_MAX_FEEDBACK_UPLOAD_BYTES", 8)
    monkeypatch.setattr(log_uploader, "archive_logs", lambda bid: str(archive))
    with pytest.raises(HTTPException) as error:
        await feedback.submit_merchant_feedback("Help", True, None, IDENTITY)
    assert error.value.status_code == 413
    assert local_support.calls == []
    assert archive.exists()


@pytest.mark.anyio
async def test_missing_cloud_identity_does_not_send_feedback(local_support, monkeypatch):
    monkeypatch.setattr(sync_worker, "_get_cloud_token", lambda bid: None)
    with pytest.raises(HTTPException) as error:
        await feedback.submit_merchant_feedback("Help", False, None, IDENTITY)
    assert error.value.status_code == 400
    assert local_support.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("message,file,status", [
    (" ", None, 422), ("x" * 8001, None, 413),
    ("help", {"filename": "private.txt"}, 415),
    ("help", {"headers": Headers({"content-type": "text/html"})}, 415),
    ("help", {"headers": Headers({"content-length": "bad"})}, 400),
    ("help", {"headers": Headers({"content-length": str(5 * 1024 * 1024 + 1)})}, 413),
])
async def test_invalid_feedback_fails_before_any_cloud_call(local_support, message, file, status):
    with pytest.raises(HTTPException) as error:
        await feedback.submit_merchant_feedback(message, False, upload(**file) if file else None, IDENTITY)
    assert error.value.status_code == status
    assert local_support.calls == []


@pytest.fixture
def cloud_support(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = create_engine(f"sqlite:///{(tmp_path / 'test_support.db').as_posix()}")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    guard = database.sync_disabled_var.set(True)
    with sessions() as db:
        db.add(User(id=71, username="support-owner", password="synthetic", role="enterprise", public_id="SUPPORT-BIZ"))
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", sessions)
    # Use the real relational persistence path with an isolated local DB; RLS
    # enforcement is separately covered by the PostgreSQL runtime suites.
    monkeypatch.setattr(database, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    yield SimpleNamespace(sessions=sessions, root=tmp_path)
    database.sync_disabled_var.reset(guard)
    engine.dispose()


@pytest.mark.anyio
async def test_cloud_feedback_persists_only_its_owned_archive_and_removes_staging(cloud_support):
    await feedback.submit_merchant_feedback("Scheduled daily diagnostic log upload", False, upload(), IDENTITY)
    with cloud_support.sessions() as db:
        row = db.query(UserFeedback).one()
        archive = db.query(ClientLogArchive).one()
        assert (row.business_id, archive.business_id, archive.feedback_id) == (71, 71, row.id)
        assert archive.content == b"support archive"
        assert archive.kind == "daily"
        assert not (cloud_support.root / row.log_file_path).exists()


@pytest.mark.anyio
async def test_cloud_feedback_without_attachment_does_not_create_an_archive(cloud_support):
    await feedback.submit_merchant_feedback("Question", False, None, IDENTITY)
    with cloud_support.sessions() as db:
        assert db.query(UserFeedback).one().log_file_path is None
        assert db.query(ClientLogArchive).count() == 0


@pytest.mark.anyio
async def test_diagnostic_download_on_shared_device_excludes_other_businesses(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOG_FILE", raising=False)
    monkeypatch.setattr(feedback, "_on_cloud_db", lambda: False)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "bizassist.log").write_text(
        "10:00:00 INFO [BizId=-] unknown login input\n"
        "10:00:01 INFO [BizId=SUPPORT-BIZ] owner's event\n"
        "10:00:02 INFO [BizId=OTHER-BIZ] private other event\n", encoding="utf-8")
    response = feedback.download_diagnostics_logs(IDENTITY)
    content = b"".join([part async for part in response.body_iterator])
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        text = archive.extractfile("bizassist.log").read().decode()
    assert "owner's event" in text
    assert "unknown login" not in text and "private other" not in text


@pytest.mark.anyio
async def test_empty_diagnostics_is_an_explanatory_archive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOG_FILE", raising=False)
    monkeypatch.setattr(feedback, "_on_cloud_db", lambda: False)
    response = feedback.download_diagnostics_logs(IDENTITY)
    content = b"".join([part async for part in response.body_iterator])
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        assert archive.getnames() == ["README.txt"]
        assert "No matching diagnostic" in archive.extractfile("README.txt").read().decode()


def request(body):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/api/telemetry/log", "headers": []}, receive)


@pytest.mark.anyio
async def test_telemetry_writes_valid_json_lines_without_forging_log_records(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(telemetry, "TELEMETRY_ENABLED", True)
    monkeypatch.setattr(telemetry, "_bound_cloud_bizid", lambda auth: "SUPPORT-BIZ")
    saved = []
    monkeypatch.setattr(telemetry, "_persist_records_to_db", lambda rows: saved.extend(rows) or len(rows))
    body = {"source": "frontend", "device_id": "device", "events": [{"event": "failure\nFORGED", "level": "error"}]}
    result = await telemetry.ingest_telemetry(request(body), authorization="Bearer synthetic")
    assert result["accepted"] == 1
    global_lines = (tmp_path / "logs/telemetry.jsonl").read_text().splitlines()
    tenant_lines = (tmp_path / "logs/businesses/SUPPORT-BIZ/telemetry.jsonl").read_text().splitlines()
    assert len(global_lines) == 1 and global_lines == tenant_lines
    assert json.loads(global_lines[0])["event"] == "failure\nFORGED"
    assert saved[0]["bizid"] == "SUPPORT-BIZ"
    assert "failure\\nFORGED" in caplog.text


@pytest.mark.anyio
async def test_relay_import_binds_claims_and_tolerates_a_readonly_log_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(telemetry, "TELEMETRY_ENABLED", True)
    monkeypatch.setattr(telemetry, "_bound_cloud_bizid", lambda auth: "SUPPORT-BIZ")
    monkeypatch.setattr(telemetry, "_persist_records_to_db", lambda rows: len(rows))

    async def denied(*args, **kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(telemetry.anyio, "open_file", denied)
    body = {"records": [{"event": "ok", "device_id": "one", "bizid": "SUPPORT-BIZ"}, {"event": "missing device"}]}
    result = await telemetry.import_telemetry(request(body), authorization="Bearer synthetic")
    assert result["accepted"] == 1
    with pytest.raises(HTTPException) as error:
        await telemetry.import_telemetry(request({"records": [{"event": "bad", "device_id": "one", "bizid": "OTHER"}]}),
                                         authorization="Bearer synthetic")
    assert error.value.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("fail", [False, True])
async def test_realtime_retains_background_relay_until_completion(monkeypatch, fail):
    manager = RealtimeManager()
    started, finish = asyncio.Event(), asyncio.Event()

    async def relay(*args):
        started.set()
        await finish.wait()
        if fail:
            raise RuntimeError("synthetic relay fault")

    monkeypatch.setattr(manager, "_relay_to_cloud", relay)
    await manager.broadcast(71, {"type": "pos.cart_update"})
    await started.wait()
    assert len(manager._relay_tasks) == 1
    task = next(iter(manager._relay_tasks))
    finish.set()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert manager._relay_tasks == set()
