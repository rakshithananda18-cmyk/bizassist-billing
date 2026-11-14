"""Bound repair-tool filesystem access and parse database/HTTP targets as data.

Operators may select another trusted filesystem root with
BIZASSIST_OPERATIONS_ROOT. Faulty CLI arguments cannot expand that boundary.
"""
import ipaddress
import os
from pathlib import Path
import sqlite3
from urllib.parse import parse_qsl, unquote, urlsplit


def operational_path(value, *, existing=False, directory=False):
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\0" in raw or raw.startswith("-"):
        raise ValueError("A local filesystem path is required")
    candidate = Path(raw).expanduser()
    if ".." in candidate.parts:
        raise ValueError("Parent-directory traversal is not allowed")
    root = Path(os.environ.get("BIZASSIST_OPERATIONS_ROOT") or Path(__file__).resolve().parents[2]).expanduser().resolve(strict=True)
    resolved = candidate.resolve(strict=existing)
    if not resolved.is_relative_to(root) or resolved == root and not directory:
        raise ValueError("Path is outside BIZASSIST_OPERATIONS_ROOT; explicitly select the trusted operations directory")
    if existing and not (resolved.is_dir() if directory else resolved.is_file()):
        raise ValueError("The selected path is not the required local file/directory")
    return resolved


def open_export(value):
    """Create private evidence once; never follow a link or overwrite a backup."""
    target = operational_path(value)
    if not target.parent.is_dir():
        raise ValueError("The export directory must already exist")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def sqlite_connection(value, *, readonly=True):
    path = operational_path(value, existing=True)
    if readonly:
        # as_uri percent-encodes '?'/'#' so filename contents cannot append
        # connection options or turn read-only inspection into a writable open.
        return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    return sqlite3.connect(str(path), uri=False)


def postgres_parameters(value):
    """Use explicit libpq keyword values; URL query fields cannot override identity."""
    parsed = urlsplit(value.replace("postgresql+psycopg2://", "postgresql://", 1))
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or parsed.fragment:
        raise ValueError("A PostgreSQL URL with an explicit server is required")
    port = parsed.port or 5432
    if not 0 < port < 65536:
        raise ValueError("Invalid PostgreSQL port")
    dbname = unquote(parsed.path.lstrip("/"))
    if not dbname or "/" in dbname:
        raise ValueError("One PostgreSQL database name is required")
    allowed = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name",
               "options", "channel_binding", "keepalives", "keepalives_idle", "keepalives_interval", "keepalives_count"}
    params = {"host": parsed.hostname, "port": port, "dbname": dbname}
    if parsed.username is not None:
        params["user"] = unquote(parsed.username)
    if parsed.password is not None:
        params["password"] = unquote(parsed.password)
    for key, entry in parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True):
        if key not in allowed or key in params or "\0" in entry:
            raise ValueError("Unsupported or repeated PostgreSQL connection option")
        params[key] = entry
    if any("\0" in entry for entry in params.values() if isinstance(entry, str)):
        raise ValueError("Invalid PostgreSQL connection value")
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = parsed.hostname.lower() == "localhost"
    if not local and params.get("sslmode", "require") not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("Remote PostgreSQL inspection requires TLS")
    if not local:
        params.setdefault("sslmode", "require")
    return params


def database_target(value):
    if value.startswith(("postgresql://", "postgres://", "postgresql+psycopg2://")):
        postgres_parameters(value)
        return value
    return str(operational_path(value, existing=True))


def migration_origin(value):
    """Migration bearer tokens may go only to configured origins or loopback."""
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Migration endpoints must be plain HTTP(S) origins without credentials or URL parameters")
    if parsed.port is not None and not 0 < parsed.port < 65536:
        raise ValueError("Invalid migration server port")
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = parsed.hostname.lower() == "localhost"
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    allowed = {entry.strip().rstrip("/") for entry in os.environ.get("BIZASSIST_MIGRATION_ORIGINS", "").split(",") if entry.strip()}
    allowed.add("https://staterbill-api-1076771386585.asia-south1.run.app")
    if not local and (parsed.scheme != "https" or origin not in allowed):
        raise ValueError("Remote migration origin must be HTTPS and explicitly listed in BIZASSIST_MIGRATION_ORIGINS")
    return origin
