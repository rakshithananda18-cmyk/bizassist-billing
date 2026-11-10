"""Explicit platform-administration authority, separate from tenant HTTP SQL.

Only admin route dependencies open these sessions, after bearer authentication.
The ordinary HTTP role has neither membership nor SET ROLE rights in this role.
"""
from contextlib import contextmanager
import os
import re

from fastapi import Depends, HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from database.db import get_db
from services.auth import get_active_user

_ENGINES = {}


def _privileged(db):
    if db.bind.dialect.name != "postgresql":
        return True
    row = db.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).first()
    return bool(row and any(row))


def _check_admin(connection, payload, *, lock=False):
    """Recheck database authority, never just the JWT's historical role claim."""
    try:
        uid = int(payload.get("user_id") or payload["id"])
        owner = int(payload["id"])
        version = int(payload.get("tv", 0) or 0)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "Invalid administration session")
    suffix = " FOR SHARE" if lock and connection.dialect.name == "postgresql" else ""
    subject = connection.execute(text(
        "SELECT id,parent_business_id,role,COALESCE(token_version,0) FROM users WHERE id=:id" + suffix
    ), {"id": uid}).first()
    if subject is None or subject[0] != owner or subject[1] is not None or subject[2] != "admin":
        raise HTTPException(403, "Active platform-admin authentication required")
    if subject[3] != version:
        raise HTTPException(401, "Administration session was revoked")


@contextmanager
def admin_session(db, payload):
    """Yield global authority only after verifying an authenticated live admin.

    Transaction-start validation also covers route helpers that commit an audit
    row before starting the actual operation. The row share lock serializes an
    operation against a concurrent role demotion or token-version revocation.
    """
    from services.admin_service import _admin_api_enabled
    if not _admin_api_enabled():
        raise HTTPException(404, "Not found")
    from database.security import bind_tenant
    try:
        subject = int(payload.get("user_id") or payload["id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "Invalid administration session")
    bind_tenant(db, subject)
    _check_admin(db.connection(), payload)
    if _privileged(db):
        yield db
        return
    url = os.environ.get("ADMIN_SERVICE_URL", "").strip()
    if not url:
        raise HTTPException(503, "Platform administration service is not configured")
    from sqlalchemy.engine import make_url
    runtime_url, service_url = make_url(str(db.bind.url)), make_url(url)
    if (service_url.get_backend_name() != "postgresql" or
            (runtime_url.host, runtime_url.port or 5432, runtime_url.database) !=
            (service_url.host, service_url.port or 5432, service_url.database)):
        raise HTTPException(503, "Administration service must use the application database")
    if url not in _ENGINES:
        _ENGINES[url] = create_engine(url, pool_pre_ping=True)
    service = Session(_ENGINES[url])

    @event.listens_for(service, "after_begin")
    def authorize_transaction(_session, _transaction, connection):
        role = connection.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).first()
        if role is None or role[0] or not role[1]:
            raise HTTPException(503, "Administration service requires its dedicated non-superuser role")
        _check_admin(connection, payload, lock=True)

    try:
        # Opening a transaction performs the privileged-side check before any
        # global ORM query can run. No service session escapes this dependency.
        service.connection()
        service.info.update(business_id=subject, admin_authorized=subject)
        yield service
    except Exception:
        service.rollback()
        raise
    finally:
        service.close()


def get_admin_db(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    with admin_session(db, current_user) as service:
        yield service


def install_admin_role(connection, role):
    """Migration-only grants for known Billing tables and Field cleanup.

    No schema creation, role membership, grant option or TRUNCATE privilege is
    granted. Unknown future tables need explicit migration/provisioning review.
    """
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", role):
        raise ValueError("Invalid administration service database role")
    facts = connection.execute(text("SELECT rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname=:r"), {"r": role}).first()
    if facts is None or facts[0] or not facts[1] or not facts[2]:
        raise ValueError("Administration role must be LOGIN NOSUPERUSER BYPASSRLS with a separate credential")
    from database.db import Base
    from services.field_business_cleanup import DELETE_ORDER
    present = set(inspect(connection).get_table_names())
    quoted = '"' + role + '"'
    connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {quoted}")
    for table in sorted(set(Base.metadata.tables) & present):
        # Feed source triggers alone own publication. Admin operators can
        # inspect it, but cannot invent or erase replication revisions.
        privileges = "SELECT" if table in {"sync_feed_clock", "sync_feed_events"} else "SELECT,INSERT,UPDATE,DELETE"
        connection.exec_driver_sql(f'GRANT {privileges} ON "{table}" TO {quoted}')
        serial = connection.execute(text("SELECT pg_get_serial_sequence(:t,'id')"), {"t": table}).scalar() if "id" in Base.metadata.tables[table].c else None
        if serial:
            # PostgreSQL returns an already qualified, quoted identifier.
            connection.exec_driver_sql(f"GRANT USAGE,SELECT ON SEQUENCE {serial} TO {quoted}")
    for table in sorted(set(DELETE_ORDER) & present):
        connection.exec_driver_sql(f'GRANT SELECT,DELETE ON "{table}" TO {quoted}')
