"""Repair-tool boundaries and protocol compatibility use synthetic files only."""
import base64
import os
from pathlib import Path
import runpy
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from scripts import _safe_io as safe
from services import totp
from routes import discovery


@pytest.fixture
def operations(tmp_path, monkeypatch):
    root = tmp_path / "authorized"
    root.mkdir()
    monkeypatch.setenv("BIZASSIST_OPERATIONS_ROOT", str(root))
    return root


def test_export_is_private_and_cannot_overwrite_existing_evidence(operations):
    target = operations / "audit.json"
    with safe.open_export(target) as output:
        output.write("original evidence")
    with pytest.raises(FileExistsError):
        safe.open_export(target)
    assert target.read_text() == "original evidence"
    if os.name != "nt":
        assert target.stat().st_mode & 0o077 == 0


def test_export_cannot_escape_trusted_operations_directory(operations):
    for value in (operations.parent / "outside.json", operations / ".." / "outside.json", "--help", "bad\0name"):
        with pytest.raises((ValueError, OSError)):
            safe.open_export(value)
    assert not (operations.parent / "outside.json").exists()


def test_existing_file_and_directory_kinds_are_checked(operations):
    file = operations / "data.txt"
    file.write_text("data")
    assert safe.operational_path(operations, existing=True, directory=True) == operations
    with pytest.raises(ValueError):
        safe.operational_path(file, existing=True, directory=True)
    with pytest.raises(ValueError):
        safe.operational_path(operations, existing=True)
    with pytest.raises(FileNotFoundError):
        safe.operational_path(operations / "missing", existing=True)


def test_readonly_sqlite_encodes_filename_delimiters_and_denies_writes(operations):
    target = operations / "space # db.sqlite"
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE proof(value TEXT)")
        db.execute("INSERT INTO proof VALUES ('kept')")
    with safe.sqlite_connection(target) as db:
        assert db.execute("SELECT value FROM proof").fetchone() == ("kept",)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM proof")
    with safe.sqlite_connection(target, readonly=False) as db:
        db.execute("INSERT INTO proof VALUES ('authorized write')")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT COUNT(*) FROM proof").fetchone()[0] == 2


def test_sqlite_cannot_interpret_a_supplied_connection_uri(operations):
    with pytest.raises((ValueError, OSError)):
        safe.sqlite_connection("file:///etc/passwd?mode=rw")
    with pytest.raises((ValueError, OSError)):
        safe.database_target("--apply")


def test_postgres_credentials_are_keyword_data_and_cannot_override_server():
    args = safe.postgres_parameters("postgresql://postgres:isolated-fixture-only%40ss%3Bhost%3Devil@db.example:6543/books?sslmode=require")
    assert args == {"host": "db.example", "port": 6543, "dbname": "books", "user": "postgres",
                    "password": "isolated-fixture-only@ss;host=evil", "sslmode": "require"}


@pytest.mark.parametrize("target", [
    "postgresql://postgres:isolated-fixture-only@db.example/books?host=other.example",
    "postgresql://postgres:isolated-fixture-only@db.example/books?sslmode=require&sslmode=disable",
    "postgresql://postgres:isolated-fixture-only@db.example/books?sslmode=disable",
    "postgresql://postgres:isolated-fixture-only@db.example/books?password=other",
    "postgresql://postgres:isolated-fixture-only@db.example/books#extra",
    "postgresql://postgres:isolated-fixture-only@db.example/",
    "postgresql://postgres:isolated-fixture-only@db.example/a/b",
    "postgresql://postgres:isolated-fixture-only@db.example:99999/books",
    "postgresql://postgres:isolated-fixture-only%00bad@db.example/books",
    "https://db.example/books",
])
def test_postgres_rejects_ambiguous_or_insecure_connection_options(target):
    with pytest.raises(ValueError):
        safe.postgres_parameters(target)


def test_local_postgres_can_use_a_development_socket_without_tls():
    assert safe.postgres_parameters("postgresql://postgres:isolated-fixture-only@127.0.0.1/books?sslmode=disable")["sslmode"] == "disable"
    assert safe.postgres_parameters("postgresql://postgres:isolated-fixture-only@db.example/books")["sslmode"] == "require"


def test_compat_rejects_unknown_database_protocol_without_echoing_credentials():
    from scripts import _dbcompat as adapter
    with pytest.raises(SystemExit) as rejected:
        adapter.connect("https://postgres:isolated-fixture-only@db.example/books")
    assert "Unsupported database URL protocol" in str(rejected.value)
    assert "isolated-fixture-only" not in str(rejected.value)


def test_actual_postgres_adapter_passes_keywords_instead_of_an_interpreted_dsn(monkeypatch):
    from scripts import _dbcompat as adapter
    received = []
    monkeypatch.setitem(sys.modules, "psycopg2", SimpleNamespace(connect=lambda **kwargs: received.append(kwargs) or SimpleNamespace()))
    adapter._connect_postgres("postgresql://postgres:isolated-fixture-only%3Bhost%3Devil@db.example/books", readonly=False)
    assert received == [{"host": "db.example", "port": 5432, "dbname": "books", "user": "postgres",
                         "password": "isolated-fixture-only;host=evil", "sslmode": "require"}]


@pytest.mark.parametrize("target", [
    "http://169.254.169.254", "https://unknown.example", "file:///tmp/data", "http://public.example",
    "https://user:password@allowed.example", "https://allowed.example/path", "https://allowed.example?redirect=evil",
])
def test_migration_refuses_untrusted_origins_before_any_request(target, monkeypatch):
    monkeypatch.setenv("BIZASSIST_MIGRATION_ORIGINS", "https://allowed.example")
    with pytest.raises(ValueError):
        safe.migration_origin(target)


def test_migration_allows_explicit_https_origin_and_loopback(monkeypatch):
    monkeypatch.setenv("BIZASSIST_MIGRATION_ORIGINS", "https://allowed.example")
    assert safe.migration_origin("https://allowed.example/") == "https://allowed.example"
    assert safe.migration_origin("http://127.0.0.1:8001") == "http://127.0.0.1:8001"


def test_actual_migration_export_refuses_redirects(monkeypatch):
    from scripts import migrate_clean_ids as migration
    monkeypatch.setenv("BIZASSIST_MIGRATION_ORIGINS", "https://allowed.example")
    calls = []
    def response(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(ok=True, json=lambda: {"tables": {}})
    monkeypatch.setattr(migration.requests, "get", response)
    assert migration._export("https://allowed.example", "synthetic-token") == {"tables": {}}
    assert calls[0][0] == "https://allowed.example/api/data-transfer/export"
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("host,scheme,expected", [
    ("192.168.88.9", "http", "http://192.168.88.9:8001"),
    ("192.168.88.9", "https", "https://192.168.88.9:8001"),
    ("::1", "https", "https://[::1]:8001"),
])
def test_discovery_describes_the_actual_lan_protocol(host, scheme, expected):
    assert discovery._backend_url(host, 8001, scheme) == expected


@pytest.mark.parametrize("host,port,scheme", [
    ("8.8.8.8", 8001, "http"), ("public.example", 8001, "https"),
    ("192.168.88.9", 0, "http"), ("192.168.88.9", 8001, "file"),
])
def test_discovery_does_not_advertise_public_or_non_http_services(host, port, scheme):
    with pytest.raises(ValueError):
        discovery._backend_url(host, port, scheme)


@pytest.mark.parametrize("bind_host,expected", [(None, "127.0.0.1"), ("0.0.0.0", "0.0.0.0")])
def test_server_defaults_local_but_preserves_explicit_cloud_listener(monkeypatch, bind_host, expected):
    calls = []
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: calls.append(kwargs)))
    monkeypatch.setenv("PORT", "8080")
    if bind_host is None:
        monkeypatch.delenv("BIND_HOST", raising=False)
    else:
        monkeypatch.setenv("BIND_HOST", bind_host)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "serve.py"), run_name="__main__")
    assert len(calls) == 1
    assert calls[0]["host"] == expected and calls[0]["port"] == 8080


@pytest.mark.parametrize("timestamp,expected", [
    (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130"),
])
def test_totp_preserves_published_rfc6238_sha1_vectors(monkeypatch, timestamp, expected):
    # RFC6238 Appendix B, SHA1 column. These are public protocol test vectors.
    secret = base64.b32encode(b"12345678901234567890").decode("ascii")
    monkeypatch.setattr(totp, "DIGITS", 8)
    assert totp.current_code(secret, at=timestamp) == expected
