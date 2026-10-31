"""Cloud polls and migration diagnostics must not consume/guess extra resources."""
import logging

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import TimeoutError as DatabasePoolTimeout

from database.db import Base
from database.models import AlertConfig, User, _serialize_orm_obj
from database.migration import _backfill_null_business_ids
from core.accounting.settlement_models import (
    SupplierPayment, CustomerRefund, CustomerCreditAllocation,
)
from routes.alerts import list_notifications
from routes.data_transfer import _existing_tables, _fetch_table


def test_notifications_and_transfer_reuse_a_single_checked_out_connection(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'test_small_pool.db'}",
        poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=0.05,
    )
    try:
        Base.metadata.create_all(eng)
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE ft_item_requests (business_id INTEGER, status TEXT)"))
            conn.execute(text("INSERT INTO ft_item_requests VALUES (1, 'pending'), (2, 'pending')"))
        with Session(eng) as db:
            db.add(User(id=1, username="pool_owner", password="unused-test-hash",
                        public_id="BA-POOL-TEST", role="enterprise", business_name="Pool fixture"))
            db.add(AlertConfig(business_id=1, active=False))
            db.commit()
            db.execute(text("SELECT 1"))  # request already owns the only connection
            assert eng.pool.checkedout() == 1
            body = list_notifications(
                current_user={"id": 1, "username": "pool_owner", "public_id": "BA-POOL-TEST"},
                db=db,
            )
            field = [item for item in body["items"] if item["kind"] == "field_requests"]
            assert len(field) == 1 and field[0]["count"] == 1
            assert "users" in _existing_tables(db)
            assert _fetch_table(db, "customers", 1) == []
            assert eng.pool.checkedout() == 1
        assert eng.pool.checkedout() == 0
    finally:
        eng.dispose()


def test_startup_reports_unowned_rows_without_assigning_business_two(tmp_path, caplog):
    eng = create_engine(f"sqlite:///{tmp_path / 'test_unowned.db'}")
    statements = []
    try:
        with eng.begin() as conn:
            for table in ("invoices", "inventory", "payments", "uploaded_files"):
                conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, business_id INTEGER)"))
                conn.execute(text(f"INSERT INTO {table} VALUES (1, NULL), (2, 42)"))
        event.listen(eng, "before_cursor_execute", lambda _c, _cur, sql, *_: statements.append(sql))
        with eng.begin() as conn, caplog.at_level(logging.ERROR):
            _backfill_null_business_ids(conn)
            for table in ("invoices", "inventory", "payments", "uploaded_files"):
                assert conn.execute(text(f"SELECT business_id FROM {table} ORDER BY id")).all() == [(None,), (42,)]
        assert not any(sql.lstrip().upper().startswith("UPDATE") for sql in statements)
        assert caplog.text.count("unowned rows; left unchanged") == 4
    finally:
        eng.dispose()


@pytest.mark.parametrize("model", [SupplierPayment, CustomerRefund, CustomerCreditAllocation])
def test_settlement_sync_keeps_actor_name_without_exporting_local_user_id(model):
    row = model(operator_id=711, operator_name="Original receipt operator")
    payload = _serialize_orm_obj(row)
    assert "operator_id" not in payload
    assert payload["operator_name"] == "Original receipt operator"


@pytest.mark.parametrize("error,expected_status", [
    (DatabasePoolTimeout("private database connection detail"), 503),
    (RuntimeError("private database connection detail"), 500),
])
def test_http_database_failures_do_not_expose_connection_details(error, expected_status):
    from fastapi.testclient import TestClient
    from database.db import get_db
    from main_groq import app
    from services.auth import get_active_user

    def broken_db():
        raise error
        yield  # retain the dependency's generator contract

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = broken_db
    app.dependency_overrides[get_active_user] = lambda: {"id": 1, "username": "pool_owner"}
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/profile")
        assert response.status_code == expected_status
        assert "private database connection detail" not in response.text
        if expected_status == 503:
            assert response.headers["retry-after"] == "5"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
