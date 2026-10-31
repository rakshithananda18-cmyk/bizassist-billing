"""Prove bootstrap migration/auth under a non-superuser schema operator.

Only TS_SCHEMA_ADMIN_DATABASE_URL on a loopback PostgreSQL fixture is accepted.
The fixture administrator creates a fresh test DB and generated test roles;
every application migration then runs as NOSUPERUSER BYPASSRLS CREATEROLE.
No developer dotenv, provider connection or credential output is used.
"""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import secrets
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    started = time.monotonic()
    admin_url = make_url(os.environ.get("TS_SCHEMA_ADMIN_DATABASE_URL", ""))
    if (admin_url.get_backend_name() != "postgresql" or
            admin_url.host not in {"localhost", "127.0.0.1", "::1"} or
            admin_url.database != "postgres" and "test" not in (admin_url.database or "").lower()):
        raise RuntimeError("An explicitly configured disposable loopback PostgreSQL fixture is required")
    nonce = uuid.uuid4().hex[:10]
    operator, runtime = "schema_operator_" + nonce, "tenant_runtime_" + nonce
    operator_password, runtime_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    database, shadow = "nonsuper_security_" + nonce + "_test", "bootstrap_creation_" + nonce
    checks = []
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with admin_engine.connect() as conn:
        conn.exec_driver_sql(f'CREATE ROLE "{operator}" LOGIN NOSUPERUSER BYPASSRLS CREATEROLE PASSWORD \'{operator_password}\'')
        conn.exec_driver_sql(f'CREATE ROLE "{runtime}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD \'{runtime_password}\'')
        # The bootstrap is cluster-global. Preserve prior fixture databases if
        # it exists: model exactly the ADMIN-but-no-SET membership a PG16 role
        # creator receives. If absent, production install creates it itself.
        existing = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='bizassist_bootstrap'")).scalar()
        if existing:
            conn.exec_driver_sql(f'GRANT bizassist_bootstrap TO "{operator}" WITH ADMIN TRUE, INHERIT FALSE, SET FALSE')
        conn.exec_driver_sql(f'CREATE DATABASE "{database}" OWNER "{operator}"')
    admin_engine.dispose()
    operator_url = admin_url.set(database=database, username=operator, password=operator_password)
    runtime_url = admin_url.set(database=database, username=runtime, password=runtime_password)
    os.environ.update(
        DATABASE_URL=operator_url.render_as_string(hide_password=False),
        BIZASSIST_TEST_DATABASE_URL=operator_url.render_as_string(hide_password=False),
        BIZASSIST_TESTING="1", BIZASSIST_RUNTIME_DB_ROLE=runtime,
        BIZASSIST_TRADE_DB_ROLE="", BIZASSIST_ADMIN_DB_ROLE="",
        DATABASE_TRADE_SERVICE_URL="", ADMIN_SERVICE_URL="",
        JWT_SECRET="synthetic-local-proof-secret-0123456789abcdef",
        GROQ_API_KEY="mock", TELEMETRY_ENABLED="0", SENTRY_DSN="", CHAT_MEMORY_ENABLED="0",
    )
    import dotenv
    dotenv.load_dotenv = lambda *_a, **_kw: False
    operator_engine = create_engine(operator_url, poolclass=NullPool)
    with operator_engine.begin() as conn:
        facts = conn.execute(text("SELECT rolsuper,rolbypassrls,rolcreaterole FROM pg_roles WHERE rolname=current_user")).one()
        assert tuple(facts) == (False, True, True)
        # Exercise CREATE ROLE NOLOGIN BYPASSRLS as this non-superuser even when
        # the shared fixture bootstrap already exists. No shared role is renamed.
        conn.exec_driver_sql(f'CREATE ROLE "{shadow}" NOLOGIN BYPASSRLS')
        conn.exec_driver_sql(f'DROP ROLE "{shadow}"')
    checks.append("non-superuser BYPASSRLS CREATEROLE operator creates NOLOGIN BYPASSRLS role")

    from alembic.config import Config
    from alembic import command
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    command.upgrade(config, "head")
    checks.append("fresh complete historical Alembic upgrade under non-superuser operator")
    command.upgrade(config, "head")
    checks.append("retry complete Alembic upgrade is idempotent")
    from database.security import install_security, authenticate_identity, public_invoice_tenant, subject_version
    from database.models import User, Invoice
    from services.auth import hash_password
    for _ in range(2):
        with operator_engine.begin() as conn:
            install_security(conn, runtime)
    checks.append("explicit repeated CREATE OR REPLACE after bootstrap ownership transfer")

    with operator_engine.connect() as conn:
        assert conn.execute(text("SELECT pg_has_role(current_user,'bizassist_bootstrap','SET')")).scalar()
        assert conn.execute(text("SELECT pg_has_role(current_user,'bizassist_bootstrap','USAGE')")).scalar()
        assert not conn.execute(text("SELECT has_schema_privilege('bizassist_bootstrap','public','CREATE')")).scalar()
        assert conn.execute(text("SELECT has_schema_privilege('bizassist_bootstrap','public','USAGE')")).scalar()
        owners = conn.execute(text("""SELECT DISTINCT r.rolname FROM pg_proc p
            JOIN pg_roles r ON r.oid=p.proowner WHERE p.proname IN
            ('bizassist_auth_subject','bizassist_live_subject','bizassist_username_taken','bizassist_public_subject',
             'bizassist_owner_ids','bizassist_public_id_taken','bizassist_network_state','bizassist_trade_policy','bizassist_trade_lock_actor')""")).scalars().all()
        assert owners == ["bizassist_bootstrap"]
        assert conn.execute(text("""SELECT EXISTS(SELECT 1 FROM pg_proc p
            CROSS JOIN LATERAL aclexplode(p.proacl) a JOIN pg_roles r ON r.oid=a.grantee
            WHERE p.proname='bizassist_auth_subject' AND r.rolname=current_user AND a.privilege_type='EXECUTE')""")).scalar()
        assert not conn.execute(text("""SELECT EXISTS(SELECT 1 FROM pg_proc p
            CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.proname='bizassist_auth_subject'
            AND a.grantee=0 AND a.privilege_type='EXECUTE')""")).scalar()
    checks.append("operator SET/inherited owner rights and explicit EXECUTE persist; bootstrap CREATE revoked; PUBLIC EXECUTE absent")

    password = "SyntheticProofPass123!"
    with Session(operator_engine) as db:
        owner = User(username="owner_" + nonce, password=hash_password(password), role="enterprise",
                     public_id="OWNER-" + nonce, settings='{"general":{"hosting_mode":"cloud"}}')
        other = User(username="other_" + nonce, password=hash_password(password), role="enterprise", public_id="OTHER-" + nonce)
        db.add_all([owner, other])
        db.flush()
        owner_id, other_id = owner.id, other.id
        staff = User(username="counter_" + nonce, staff_login_name="counter", password=hash_password(password),
                     parent_business_id=owner_id, role="cashier")
        invoice = Invoice(business_id=owner_id, invoice_id="PROOF-" + nonce, amount=0, total_amount=0,
                          status="Pending", invoice_date="2026-10-31", uid_token="public_" + nonce)
        db.add_all([staff, invoice])
        db.commit()
        # A deployment still using its legacy privileged operator can invoke
        # the fixed bootstrap helpers after PUBLIC EXECUTE has been revoked.
        assert db.execute(text("SELECT bizassist_username_taken(:u)"), {"u": owner.username}).scalar()
    checks.append("legacy non-superuser operator invokes fixed bootstrap helper after installation")

    runtime_engine = create_engine(runtime_url, poolclass=NullPool)
    with Session(runtime_engine) as db:
        facts = db.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        assert tuple(facts) == (False, False)
        assert not db.execute(text("SELECT pg_has_role(current_user,'bizassist_bootstrap','MEMBER')")).scalar()
        assert not db.execute(text("SELECT pg_has_role(current_user,:o,'MEMBER')"), {"o": operator}).scalar()
        assert not db.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE')")).scalar()
        assert db.query(User).count() == 0
        assert authenticate_identity(db, "owner_" + nonce, "wrong") is None
        authenticated = authenticate_identity(db, "owner_" + nonce, password)
        assert authenticated.id == owner_id
        assert db.get(User, other_id) is None
        assert subject_version(db, owner_id) == (0,)
    checks.append("constrained runtime has no privileged memberships/CREATE and authenticates only its tenant")
    with Session(runtime_engine) as db:
        staff = authenticate_identity(db, "counter", password, "owner_" + nonce)
        assert staff.parent_business_id == owner_id
    checks.append("constrained runtime staff login works via narrow bootstrap")
    with Session(runtime_engine) as db:
        assert public_invoice_tenant(db, "public_" + nonce) == owner_id
        assert db.query(Invoice).filter(Invoice.uid_token == "public_" + nonce).one().business_id == owner_id
    checks.append("public invoice token binds its constrained tenant without global SELECT")
    runtime_engine.dispose()
    operator_engine.dispose()
    report = {"executed_at": datetime.now(timezone.utc).isoformat(), "engine": "PostgreSQL 16 disposable loopback fixture",
              "schema_operator": "NOSUPERUSER BYPASSRLS CREATEROLE", "existing_shared_bootstrap_preserved": bool(existing),
              "passed": len(checks), "failed": 0, "seconds": round(time.monotonic() - started, 2),
              "checks": checks, "production_access": False}
    destination = os.environ.get("TS_SECURITY_PROOF_OUTPUT")
    if destination:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
