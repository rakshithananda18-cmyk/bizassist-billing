"""
tests/test_sync_queue_backoff.py
================================
The outbox's two missing properties, both of which `sync_inbox` already had:

  1. DEDUP — a pending row could be queued again and again. Measured on the
     local DB 2026-08-04: 31 pending rows, 13 distinct targets, three of them
     holding seven copies each. The drain window is `ORDER BY id LIMIT 100`, so
     unbounded duplication ends with the window full of copies and that business
     syncing nothing.

  2. BACKOFF — a DEFERRED row correctly keeps `synced_at = NULL` (M-20: a
     deferral is not a rejection), and was therefore re-sent every cycle
     forever, with no counter and no delay.
"""
import os
import sys
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from sqlalchemy import create_engine, text

from database.migration import _ensure_sync_queue_dedup_index
from database.models import SyncQueue
from services.sync_worker import (_push_backoff, _PUSH_BACKOFF_MAX_SEC,
                                  _PUSH_BACKOFF_BASE_SEC)

# RUNS ON POSTGRES TOO, and that is the point.
#
# `_ensure_sync_queue_dedup_index` emits DIFFERENT SQL per dialect — the
# correlated payload UPDATE uses `IS NOT DISTINCT FROM` on Postgres and
# `IFNULL(...)` on SQLite. A SQLite-only pass proves nothing about the branch
# that will actually run against the cloud, and this function DELETEs from the
# outbox: the table holding writes that have not been delivered yet. That is
# the finding-17 shape (`ADD COLUMN ... DATETIME` passing on SQLite, crashing
# Postgres), so it is tested the way C-8 says to test it.
#
# On Postgres the table is built in a throwaway schema and `search_path` points
# at it, so the unqualified `sync_queue` in the migration resolves there and no
# other suite sharing the CI database can see these rows — or lose its own to
# the dedup DELETE.
_PG_URL = os.environ.get("BIZASSIST_TEST_DATABASE_URL", "")
_SCHEMA = "sync_queue_backoff_test"


@pytest.fixture
def conn(tmp_path):
    on_pg = _PG_URL.startswith(("postgresql://", "postgres://"))
    engine = create_engine(_PG_URL if on_pg else f"sqlite:///{tmp_path/'q.db'}")
    with engine.connect() as c:
        if on_pg:
            c.execute(text(f'DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE'))
            c.execute(text(f'CREATE SCHEMA {_SCHEMA}'))
            c.execute(text(f'SET search_path TO {_SCHEMA}'))
            c.commit()
        # Built from the MODEL, not a hand-written copy, so the test also fails
        # if the declared schema and what the migration expects drift apart.
        SyncQueue.__table__.create(c)
        c.commit()
        try:
            yield c
        finally:
            if on_pg:
                c.rollback()
                c.execute(text(f'DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE'))
                c.commit()


def _ts(s):
    """'2026-08-03 15:28:25' -> datetime. Postgres will not take the string for
    a TIMESTAMP column via a bound parameter, and SQLite is happy either way."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _same_instant(value, s):
    """Compare across dialects: SQLite hands back a string, Postgres a datetime."""
    return str(value)[:19] == s


def _q(conn, bid, entity, eid, op, payload, created, synced=None):
    conn.execute(text(
        "INSERT INTO sync_queue (business_id,entity,entity_id,operation,payload,created_at,synced_at) "
        "VALUES (:b,:e,:i,:o,:p,:c,:s)"),
        {"b": bid, "e": entity, "i": eid, "o": op, "p": payload,
         "c": _ts(created), "s": _ts(synced) if synced else None})
    conn.commit()


def test_dedup_keeps_oldest_row_with_newest_payload(conn):
    # The exact observed shape: one target, queued three times across a day.
    _q(conn, 126, "invoice_line_items", 75, "INSERT", '{"v":1}', "2026-08-03 15:28:25")
    _q(conn, 126, "invoice_line_items", 75, "INSERT", '{"v":2}', "2026-08-04 02:00:00")
    _q(conn, 126, "invoice_line_items", 75, "INSERT", '{"v":3}', "2026-08-04 08:39:37")

    _ensure_sync_queue_dedup_index(conn)

    rows = conn.execute(text(
        "SELECT id, created_at, payload FROM sync_queue WHERE synced_at IS NULL")).fetchall()
    assert len(rows) == 1
    # OLDEST created_at survives — it is the only evidence of how long this has
    # been stuck, which is what any "pending too long" rule reads.
    assert _same_instant(rows[0][1], "2026-08-03 15:28:25")
    # ...carrying the NEWEST payload, so keeping the old row is not stale state.
    assert rows[0][2] == '{"v":3}'


def test_dedup_does_not_touch_history_or_distinct_targets(conn):
    _q(conn, 126, "invoices", 5, "INSERT", "{}", "2026-08-01 10:00:00", synced="2026-08-01 10:01:00")
    _q(conn, 126, "invoices", 5, "INSERT", "{}", "2026-08-02 10:00:00", synced="2026-08-02 10:01:00")
    _q(conn, 126, "invoices", 5, "UPDATE", "{}", "2026-08-03 10:00:00")   # different op
    _q(conn, 133, "invoices", 5, "INSERT", "{}", "2026-08-03 10:00:00")   # different business

    _ensure_sync_queue_dedup_index(conn)

    assert conn.execute(text("SELECT COUNT(*) FROM sync_queue")).scalar() == 4


def test_index_blocks_a_second_pending_copy(conn):
    _q(conn, 126, "invoice_payments", 6, "INSERT", "{}", "2026-08-03 15:28:26")
    _ensure_sync_queue_dedup_index(conn)

    with pytest.raises(Exception):
        _q(conn, 126, "invoice_payments", 6, "INSERT", "{}", "2026-08-04 09:00:00")


def test_backoff_grows_and_is_capped():
    assert _push_backoff(1).total_seconds() == _PUSH_BACKOFF_BASE_SEC
    assert _push_backoff(2).total_seconds() == _PUSH_BACKOFF_BASE_SEC * 2
    assert _push_backoff(3).total_seconds() == _PUSH_BACKOFF_BASE_SEC * 4
    # Monotonic, and never unbounded.
    prev = 0
    for n in range(1, 40):
        cur = _push_backoff(n).total_seconds()
        assert cur >= prev
        assert cur <= _PUSH_BACKOFF_MAX_SEC
        prev = cur
    # Still retries forever at the cap — a parent can always still arrive, and a
    # row that gave up permanently is a lost write.
    assert _push_backoff(999).total_seconds() == _PUSH_BACKOFF_MAX_SEC
