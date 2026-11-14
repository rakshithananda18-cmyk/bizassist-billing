"""Device setup uses verified cloud identity, never remote numeric IDs."""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from database.db import Base, sync_disabled_var
from database.models import (User, Customer, TableAlteration, SyncDeviceNamespace,
                             SyncTombstone, SyncFeedClock, SyncFeedEvent)
from core.models import DocumentSequence
from core.sync.device_series import allocate_namespace, installation_id, local_series, local_counter_number
from routes import auth, device_auth, sync


@pytest.fixture
def device(tmp_path, monkeypatch):
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth, "_DB_MODE", "local")
    monkeypatch.setattr(device_auth, "_rate_limit", lambda request: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[m.__table__ for m in (
        User, Customer, TableAlteration, DocumentSequence, SyncDeviceNamespace,
        SyncTombstone, SyncFeedClock, SyncFeedEvent)])
    guard = sync_disabled_var.set(True)
    db = sessionmaker(bind=engine)()
    documents = {"/profile": {"id": 990001, "public_id": "CLOUD-VERIFIED-BIZ",
        "username": "cloud-owner", "email": "owner@example.test", "role": "enterprise",
        "business_name": "Verified shop"}, "/settings": {"subscription": {"plan": "pro"}},
        "/api/sync/bootstrap-state": {"has_business_data": True}}
    calls, stored = [], []
    def verify(path, token):
        assert token == "synthetic-cloud-proof"
        calls.append(path)
        return documents[path]
    monkeypatch.setattr(sync, "_read_verified_cloud_document", verify)
    from services import sync_worker
    monkeypatch.setattr(sync_worker, "store_cloud_token", lambda bid, token: stored.append((bid, token)))
    yield db, documents, calls, stored
    db.close()
    sync_disabled_var.reset(guard)
    engine.dispose()


def bridge():
    return device_auth.CloudSessionRequest(token="synthetic-cloud-proof", password="Synthetic-offline-password")


def request():
    return Request({"type": "http", "method": "POST", "path": "/api/auth/device/cloud-session",
                    "headers": [], "client": ("127.0.0.1", 12000)})


def test_verified_new_owner_is_mirrored_pending_with_local_session(device):
    db, documents, calls, stored = device
    result = device_auth.cloud_session(bridge(), request(), authorization=None, db=db)
    owner = db.query(User).one()
    assert owner.id != documents["/profile"]["id"]
    assert owner.public_id == "CLOUD-VERIFIED-BIZ"
    assert owner.password != bridge().password
    settings = json.loads(owner.settings)
    assert settings["general"] == {"hosting_mode": "local", "sync_bootstrap_pending": True}
    assert calls == ["/profile", "/settings", "/api/sync/bootstrap-state"]
    assert stored == [(owner.id, "synthetic-cloud-proof")]
    assert result["token"] and result["id"] == owner.id and result["db_mode"] == "local"


def test_authoritatively_empty_registration_can_start_local_without_paid_restore(device):
    db, documents, _, _ = device
    documents["/settings"]["subscription"]["plan"] = "free"
    documents["/api/sync/bootstrap-state"]["has_business_data"] = False
    body = bridge()
    body.local_only = True
    device_auth.cloud_session(body, request(), authorization=None, db=db)
    from core.sync.readiness import assert_financial_ready
    assert_financial_ready(db, db.query(User).one().id)
    assert auth._session_claims(db.query(User).one(), sid="synthetic")["local_only"] is True


def test_new_mirror_keeps_verified_business_profile_but_not_other_device_consent(device):
    db, documents, _, _ = device
    documents["/profile"].update(gstin="synthetic-gstin", address="Verified address", counter_prefix="OW",
        state_code="29", upi_vpa="synthetic@example")
    documents["/settings"].update(general={"app_zoom": 95, "device_invoice_namespace": "OLD",
        "device_installation_id": "old-installation", "sync_local_only_explicit": True,
        "diagnostic_upload_enabled": True}, inventory={"batch_tracking": True})
    device_auth.cloud_session(bridge(), request(), authorization=None, db=db)
    owner = db.query(User).one()
    assert owner.gstin == "synthetic-gstin" and owner.address == "Verified address"
    assert owner.state_code == "29" and owner.counter_prefix == "OW" and owner.upi_vpa == "synthetic@example"
    settings = json.loads(owner.settings)
    assert settings["inventory"]["batch_tracking"] is True and settings["general"]["app_zoom"] == 95
    assert not {"device_invoice_namespace", "device_installation_id", "sync_local_only_explicit",
                "diagnostic_upload_enabled"}.intersection(settings["general"])


def test_empty_attestation_is_tenant_scoped_and_detects_existing_data(device, monkeypatch):
    db, _, _, _ = device
    db.add(User(id=7, username="empty-owner", public_id="EMPTY-BIZ", password="synthetic"))
    db.add(User(id=8, username="other-owner", public_id="OTHER-BIZ", password="synthetic"))
    db.add(Customer(business_id=8, name="Other tenant"))
    db.commit()
    monkeypatch.setattr(sync, "_MODEL_MAP", {"customers": Customer})
    identity = {"id": 7, "user_id": 7, "username": "empty-owner", "public_id": "EMPTY-BIZ", "role": "enterprise"}
    assert sync.bootstrap_state(identity, db) == {"has_business_data": False}
    db.add(Customer(business_id=7, name="Existing customer"))
    db.commit()
    assert sync.bootstrap_state(identity, db) == {"has_business_data": True}


@pytest.mark.parametrize("collision", ["username", "email", "staff-identity"])
def test_unrelated_local_identity_is_never_adopted_or_rekeyed(device, collision):
    db, documents, calls, stored = device
    db.add(User(id=7, public_id="LOCAL-OTHER-BIZ", username="CLOUD-OWNER" if collision == "username" else "unrelated",
        email="owner@example.test" if collision == "email" else "other@example.test",
        password="original-hash", role="cashier" if collision == "staff-identity" else "enterprise"))
    if collision == "staff-identity":
        documents["/profile"]["public_id"] = "LOCAL-OTHER-BIZ"
    db.commit()
    with pytest.raises(HTTPException) as error:
        device_auth.cloud_session(bridge(), request(), authorization=None, db=db)
    assert error.value.status_code == 409
    assert db.query(User).count() == 1
    assert db.get(User, 7).public_id == "LOCAL-OTHER-BIZ"
    assert db.get(User, 7).password == "original-hash" and not stored


def test_existing_owner_retains_local_profile_password_and_explicit_consent(device):
    db, _, calls, _ = device
    owner = User(id=7, public_id="CLOUD-VERIFIED-BIZ", username="cloud-owner", password="original-hash",
        business_name="Local edited shop", role="enterprise", settings=json.dumps({"general": {
            "hosting_mode": "local", "sync_local_only_explicit": True}}))
    db.add(owner)
    db.commit()
    result = device_auth.cloud_session(bridge(), request(), authorization=None, db=db)
    assert result["id"] == 7
    assert owner.password == "original-hash" and owner.business_name == "Local edited shop"
    assert json.loads(owner.settings)["general"]["sync_local_only_explicit"] is True
    assert auth._session_claims(owner, sid="synthetic")["local_only"] is True
    assert calls == ["/profile"]


def test_staff_cloud_session_cannot_provision_owner(device):
    db, documents, _, stored = device
    documents["/profile"]["role"] = "cashier"
    with pytest.raises(HTTPException) as error:
        device_auth.cloud_session(bridge(), request(), authorization=None, db=db)
    assert error.value.status_code == 403
    assert db.query(User).count() == 0 and not stored


def test_device_namespace_is_stable_distinct_and_shared_by_lan_clients(device):
    db, _, _, _ = device
    first, second = str(uuid4()), str(uuid4())
    one = allocate_namespace(db, 7, first)
    assert allocate_namespace(db, 7, first) == one
    two = allocate_namespace(db, 7, second)
    assert two != one and len(one) == 3
    db.add(User(id=7, username="local-owner", role="enterprise", password="synthetic",
        settings=json.dumps({"general": {"hosting_mode": "hybrid", "device_invoice_namespace": one}})))
    db.commit()
    assert local_series(db, 7, "LCL-OW") == f"LCL-OW-{one}"
    assert local_series(db, 7, f"LCL-OW-{one}") == f"LCL-OW-{one}"
    # A draft created before the setup refresh is scoped before issuance.
    assert local_counter_number(db, 7, "LCL-OW-0001", f"LCL-OW-{one}") == f"LCL-OW-{one}-0001"
    assert local_counter_number(db, 7, f"LCL-OW-{one}-0001", f"LCL-OW-{one}") == f"LCL-OW-{one}-0001"
    # Imported historical documents retain the number that was already issued.
    assert local_counter_number(db, 7, "OLD-0001", None) == "OLD-0001"
    registered_installation = installation_id()
    from services.process_lock import data_path
    assert data_path("installation_id").read_text(encoding="utf-8").strip() == registered_installation
    assert installation_id() == registered_installation


def test_unregistered_hybrid_device_cannot_issue_in_colliding_series(device):
    db, _, _, _ = device
    db.add(User(id=7, username="unregistered", password="synthetic", settings='{"general":{"hosting_mode":"hybrid"}}'))
    db.commit()
    with pytest.raises(HTTPException) as error:
        local_series(db, 7, "LCL-OW")
    assert error.value.status_code == 409
    assert error.value.headers["X-Sync-State"] == "device-registration"


def test_h6_upgrade_is_idempotent_and_backfills_absent_historical_deletion(device):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    db, _, _, _ = device
    db.add(User(id=7, username="migration-owner", password="synthetic"))
    db.add(SyncFeedEvent(business_id=7, revision=1, entity="customers", row_uid="previously-deleted",
        operation="DELETE", payload='{"uid":"previously-deleted"}'))
    db.commit()
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "h6_sync_reliability.py"
    spec = importlib.util.spec_from_file_location("h6_sync_reliability", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.get_bind().begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert "sync_device_namespaces" in inspect(connection).get_table_names()
    db.expire_all()
    assert db.query(SyncTombstone).filter_by(row_uid="previously-deleted").count() == 1
