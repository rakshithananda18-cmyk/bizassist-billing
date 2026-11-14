"""Security boundaries for support archives, local secrets and log records."""
import gzip
import json
import os
import stat
import sys
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import TelemetryEvent
from database import db as database
from database.models import Base
from server_entry import _write_private_secret
from services import telemetry_maintenance as maintenance
from services.dates import utc_now
from services.log_safety import log_value


def test_untrusted_diagnostic_text_cannot_forge_log_records_or_terminal_commands():
    hostile = "merchant\r\nFORGED ADMIN\x1b[2J\u2028second record\u2029third"
    safe = log_value(hostile)
    assert safe == r"merchant\r\nFORGED ADMIN\x1b[2J\u2028second record\u2029third"
    assert not any(control in safe for control in ("\r", "\n", "\x1b", "\u2028", "\u2029"))
    assert log_value(12345) == "12345"


@pytest.mark.parametrize("name", ["jwt-secret", "jwt-secret.dpapi"])
def test_private_secret_replacement_is_atomic_and_leaves_only_the_selected_file(tmp_path, name):
    _write_private_secret(tmp_path, name, b"first synthetic secret")
    _write_private_secret(tmp_path, name, b"replacement synthetic secret")
    target = tmp_path / name
    assert target.read_bytes() == b"replacement synthetic secret"
    assert list(tmp_path.iterdir()) == [target]
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["../outside-secret", "other-name", "jwt-secret/child", "/tmp/jwt-secret"])
def test_secret_filename_is_fixed_before_any_file_is_created(tmp_path, name):
    with pytest.raises(ValueError, match="Unsupported secret filename"):
        _write_private_secret(tmp_path, name, b"synthetic secret")
    assert list(tmp_path.iterdir()) == []


def test_failed_secret_replace_preserves_previous_value_and_removes_temporary_file(tmp_path, monkeypatch):
    original = tmp_path / "jwt-secret"
    original.write_bytes(b"old synthetic value")
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("synthetic full disk")))
    with pytest.raises(OSError, match="synthetic full disk"):
        _write_private_secret(tmp_path, "jwt-secret", b"new synthetic value")
    assert original.read_bytes() == b"old synthetic value"
    assert list(tmp_path.iterdir()) == [original]


def test_secret_target_symlink_cannot_overwrite_another_file(tmp_path):
    secret_dir = tmp_path / "installation"
    secret_dir.mkdir()
    outside = tmp_path / "unrelated-file"
    outside.write_bytes(b"must survive")
    target = secret_dir / "jwt-secret"
    try:
        target.symlink_to(outside)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account cannot create symlinks; Linux CI exercises this boundary")
        raise
    with pytest.raises(OSError, match="symlink"):
        _write_private_secret(secret_dir, "jwt-secret", b"hostile replacement")
    assert outside.read_bytes() == b"must survive"
    assert target.is_symlink()


@pytest.fixture
def archive_storage(monkeypatch):
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_BUCKET", "synthetic-diagnostics")
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_EXPECTED_OWNER", "123456789012")
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_PREFIX", "support/archives/")
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_ENDPOINT", "https://storage.example.invalid")
    uploads = []
    clients = []

    def client(service, **kwargs):
        clients.append((service, kwargs))
        return SimpleNamespace(put_object=lambda **request: uploads.append(request))

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    return SimpleNamespace(uploads=uploads, clients=clients)


def test_support_archive_upload_binds_expected_bucket_owner_and_preserves_exact_bytes(archive_storage):
    archive = gzip.compress(b'{"event":"synthetic diagnostic"}\n')
    assert maintenance.upload_archive_to_object_storage(archive, "diagnostics.jsonl.gz") is True
    assert archive_storage.clients == [("s3", {"endpoint_url": "https://storage.example.invalid"})]
    assert archive_storage.uploads == [{"Bucket": "synthetic-diagnostics", "Key": "support/archives/diagnostics.jsonl.gz",
                                        "Body": archive, "ExpectedBucketOwner": "123456789012", "ContentType": "application/gzip"}]


@pytest.mark.parametrize("owner", ["", "owner/other", "owner\r\nforged", "非ascii"])
def test_archive_upload_without_a_valid_bucket_identity_never_opens_a_client(archive_storage, monkeypatch, owner):
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_EXPECTED_OWNER", owner)
    assert maintenance.upload_archive_to_object_storage(b"synthetic", "diagnostics.gz") is False
    assert archive_storage.clients == []
    assert archive_storage.uploads == []


def test_unconfigured_storage_missing_sdk_and_failed_upload_remain_recoverable(archive_storage, monkeypatch):
    monkeypatch.delenv("TELEMETRY_ARCHIVE_S3_BUCKET")
    assert maintenance.upload_archive_to_object_storage(b"x", "diagnostics.gz") is False
    assert archive_storage.clients == []
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_BUCKET", "synthetic-diagnostics")
    monkeypatch.setitem(sys.modules, "boto3", None)
    assert maintenance.upload_archive_to_object_storage(b"x", "diagnostics.gz") is False
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic storage outage"))))
    assert maintenance.upload_archive_to_object_storage(b"x", "diagnostics.gz") is False


@pytest.fixture
def telemetry_db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "test_archive.db").as_posix())
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    try:
        yield sessions
    finally:
        engine.dispose()


def _insert_events(sessions, ages):
    with sessions() as db:
        for index, age in enumerate(ages):
            db.add(TelemetryEvent(received_at=utc_now() - timedelta(days=age), bizid="BA-ARCHIVE", device_id="synthetic-device",
                                  event=f"event-{index}", payload='{"safe":"snapshot"}' if index else "legacy-payload"))
        db.commit()


def test_archive_pagination_watermark_never_purges_rows_created_after_download(telemetry_db):
    _insert_events(telemetry_db, [2, 1])
    with telemetry_db() as db:
        data, filename, watermark = maintenance.build_archive(db, batch=1)
        records = [json.loads(line) for line in gzip.decompress(data).decode().splitlines()]
        assert [record["event"] for record in records] == ["event-0", "event-1"]
        assert records[0]["payload"] == "legacy-payload"
        assert records[1]["payload"] == {"safe": "snapshot"}
        assert filename.endswith(".jsonl.gz")
        db.add(TelemetryEvent(received_at=utc_now(), bizid="BA-ARCHIVE", device_id="synthetic-device", event="arrived-during-download"))
        db.commit()
        assert maintenance.purge_archived(db, watermark) == 2
        assert [row.event for row in db.query(TelemetryEvent)] == ["arrived-during-download"]
        assert maintenance.purge_archived(db, 0) == 0


def test_retention_and_size_guard_remove_oldest_rows_while_preserving_newest_diagnostics(telemetry_db, monkeypatch):
    _insert_events(telemetry_db, [60, 5, 4, 3, 2, 1])
    monkeypatch.setattr(maintenance, "RETENTION_DAYS", 30)
    monkeypatch.setattr(maintenance, "MAX_MB", 1)
    monkeypatch.setattr(maintenance, "table_size_bytes", lambda db: 2 * 1024 * 1024)
    monkeypatch.delenv("TELEMETRY_ARCHIVE_S3_BUCKET", raising=False)
    maintenance.run_telemetry_db_maintenance()
    with telemetry_db() as db:
        retained = db.query(TelemetryEvent).order_by(TelemetryEvent.received_at).all()
        assert [row.event for row in retained] == ["event-4", "event-5"]
        stats = maintenance.stats(db)
        assert stats["rows"] == 2
        assert stats["oldest"] == retained[0].received_at.isoformat()
        assert stats["newest"] == retained[-1].received_at.isoformat()


@pytest.mark.parametrize("upload_succeeds", [True, False])
def test_over_cap_archives_before_purging_and_keeps_new_arrivals_or_falls_back(telemetry_db, monkeypatch, upload_succeeds):
    _insert_events(telemetry_db, [5, 4, 3, 2, 1])
    monkeypatch.setattr(maintenance, "MAX_MB", 1)
    monkeypatch.setattr(maintenance, "table_size_bytes", lambda db: 2 * 1024 * 1024)
    monkeypatch.setenv("TELEMETRY_ARCHIVE_S3_BUCKET", "synthetic-diagnostics")
    snapshots = []

    def upload(data, filename):
        snapshots.extend(json.loads(line)["event"] for line in gzip.decompress(data).decode().splitlines())
        with telemetry_db() as newer:
            newer.add(TelemetryEvent(received_at=utc_now(), bizid="BA-ARCHIVE", device_id="synthetic-device", event="new-arrival"))
            newer.commit()
        return upload_succeeds

    monkeypatch.setattr(maintenance, "upload_archive_to_object_storage", upload)
    maintenance.run_telemetry_db_maintenance()
    assert snapshots == [f"event-{i}" for i in range(5)]
    with telemetry_db() as db:
        remaining = [row.event for row in db.query(TelemetryEvent).order_by(TelemetryEvent.received_at)]
        assert "new-arrival" in remaining
        assert remaining == (["new-arrival"] if upload_succeeds else ["event-3", "event-4", "new-arrival"])
