"""C-7 — a Postgres trigger's RAISE EXCEPTION must reject ONE ROW, not the batch.

WHY THIS FILE EXISTS
--------------------
The line-item overfill guard is installed in two dialects
(`database/migration.py::_install_overfill_guard`):

  · SQLite   — `SELECT RAISE(ABORT, …)`  → sqlite3.IntegrityError
  · Postgres — `RAISE EXCEPTION …`       → SQLSTATE P0001,
               psycopg2.errors.RaiseException ⊂ psycopg2.InternalError

`routes/sync.py::push_changes` caught only `IntegrityError`. So on SQLite —
which is what every test and every developer machine runs — a guard-refused row
was acked and reported in `rejected`, exactly as designed. On the cloud the very
same guard raised a class the handler did not name, the exception escaped the
per-row SAVEPOINT to the batch-level `except Exception`, and the endpoint
answered **500 for the whole batch**. The device cannot ack a 500, so it re-sent
the identical batch every cycle, for ever: a poisoned outbox that no amount of
retrying could drain. Observed live 2026-08-03 on biz 133.

The dialect asymmetry is the whole finding. A test that only proves the SQLite
path works proves nothing about the path that broke, so both cases here inject
the *Postgres* failure shape directly and run on any dialect.

THE SECOND TEST IS THE IMPORTANT ONE
------------------------------------
The obvious fix — `except (IntegrityError, InternalError)` — is wrong, and
quietly worse than the bug. On Postgres, once a transaction is genuinely
aborted, EVERY subsequent statement raises 25P02 `InFailedSqlTransaction`,
which is also an `InternalError`. A blanket catch would file every remaining row
in the batch as "rejected by the cloud" and ack them — silently discarding real
sales because the connection was sick. Only SQLSTATE class P0 (a PL/pgSQL RAISE,
i.e. a deliberate row-level refusal) may be acked; everything else must still
blow the batch up so the device retries it.
"""
import os
import sys
import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import InternalError

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient        # noqa: E402
from main_groq import app                        # noqa: E402
from routes import sync as sync_route            # noqa: E402

client = TestClient(app)


class _FakePgError(Exception):
    """Stand-in for psycopg2.errors.RaiseException / InFailedSqlTransaction.

    The handler classifies on `pgcode` alone, which is the only attribute of the
    real DBAPI error it reads — so this is the whole contract, not a partial
    mock. Importing psycopg2 to build the genuine article would make the test
    require a driver that a SQLite-only machine has no reason to install.
    """
    def __init__(self, pgcode: str, message: str):
        super().__init__(message)
        self.pgcode = pgcode


def _signup(business_name):
    uname = f"c7_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}


def _customer_push_body(bid):
    """One INSERT of a customer that does not exist yet, so the handler's
    dedupe-by-uid branch finds nothing and must take the REJECT path."""
    now = datetime.utcnow().isoformat()
    return {"changes": [{
        "entity": "customers",
        "entity_id": 987654,
        "operation": "INSERT",
        "created_at": now,
        "payload": {
            "uid": str(uuid.uuid4()),
            "business_id": bid,
            "name": f"C7 Guard {uuid.uuid4().hex[:6]}",
            "phone": f"9{uuid.uuid4().int % 10**9:09d}",
            "updated_at": now,
            "created_at": now,
        },
    }]}


def _raise_from_inside_the_savepoint(monkeypatch, exc):
    """Make the row fail the way the trigger does: from inside the per-row
    SAVEPOINT, after the row has been flushed. `run_post_apply` is the last
    thing that runs in that block and is reached through the module attribute,
    so patching it reproduces the failure shape without needing a real trigger
    on a dialect that cannot express one."""
    def _boom(*a, **kw):
        raise exc
    monkeypatch.setattr(sync_route._apply_hooks, "run_post_apply", _boom)


def test_pg_trigger_raise_rejects_the_row_not_the_batch(monkeypatch):
    """P0001 → 200, the row lands in `rejected`, and it is ACKED (M-13).

    RED ON REVERT: with `except IntegrityError` alone this returns 500 and the
    outbox never drains.
    """
    owner = _signup("C7 Overfill Shop")
    body = _customer_push_body(owner["bid"])

    _raise_from_inside_the_savepoint(monkeypatch, InternalError(
        "INSERT INTO invoice_line_items ...", {},
        _FakePgError("P0001", "overfill guard: line items for invoices 821 would "
                              "total 1240.00, exceeding the billed amount 1116.00"),
    ))

    r = client.post("/api/sync/push", headers=owner["headers"], json=body)
    assert r.status_code == 200, f"trigger RAISE must not 500 the batch: {r.text}"

    data = r.json()
    assert len(data["rejected"]) == 1, data
    assert "overfill guard" in data["rejected"][0]["reason"]
    # Acked so the outbox drains — the same trade the SAVEPOINT already makes.
    assert data["applied"] == 1, data
    assert data["received"] == 1


def test_aborted_transaction_is_not_acked_as_a_rejection(monkeypatch):
    """25P02 → still fatal. A sick connection must NOT be read as the cloud
    refusing rows, or the rest of the batch is thrown away instead of retried.

    RED if the fix is widened to a blanket `except (IntegrityError,
    InternalError)`.
    """
    owner = _signup("C7 Aborted Txn Shop")
    body = _customer_push_body(owner["bid"])

    _raise_from_inside_the_savepoint(monkeypatch, InternalError(
        "INSERT INTO customers ...", {},
        _FakePgError("25P02", "current transaction is aborted, commands ignored "
                              "until end of transaction block"),
    ))

    r = client.post("/api/sync/push", headers=owner["headers"], json=body)
    assert r.status_code == 500, (
        "an aborted transaction is an infrastructure failure, not a row-level "
        f"refusal — the device must retry, not ack: {r.text}"
    )


def test_dbapi_error_without_a_pgcode_is_not_acked(monkeypatch):
    """SQLite raises InternalError with no `pgcode` at all. Absent is not P0 —
    it must stay fatal rather than default into the ack path."""
    owner = _signup("C7 No Pgcode Shop")
    body = _customer_push_body(owner["bid"])

    _raise_from_inside_the_savepoint(monkeypatch, InternalError(
        "INSERT INTO customers ...", {}, Exception("driver went sideways"),
    ))

    r = client.post("/api/sync/push", headers=owner["headers"], json=body)
    assert r.status_code == 500, r.text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
