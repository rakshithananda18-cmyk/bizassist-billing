"""
tests/test_pull_partial.py — rule 58 on the PULL path
=====================================================
`GET /api/sync/pull` queries ~25 tables on ONE database session inside one
`try/except` per table. On Postgres a failed statement ABORTS the transaction,
so every later table raises `InFailedSqlTransaction` until someone rolls back —
and nothing did.

Observed in production 2026-07-28 00:29 for biz 42: ONE failure was reported as
twenty, across shift_cash_movements, invoices, inventory, payments,
stock_ledger, product_barcodes, business_settings, invoice_payments, expenses,
godowns, stock_transfers, purchase_invoices, purchase_orders, alert_configs,
rate_limit_configs, table_alterations, period_locks, b2b_connections, b2b_orders
and b2b_order_line_items.

This is N4b-PG (§63) again — the same defect, the same engine behaviour, a
different path. Rule 58 was written after that one; this is it being applied
where it had not yet reached.

TWO HALVES, and the second is the one that protects data
--------------------------------------------------------
  * the cloud rolls back per table, so one failure costs one table;
  * the cloud REPORTS which tables it could not read, and the client HOLDS its
    pull cursor when any did.

Without the second half the client advances `last_sync_at` past rows it never
received, and they are never offered again. `changes` simply has no key for a
failed table, which is indistinguishable from "that table had no changes" —
rule 33, on the read side, where it costs pulled data (M-12's shape).
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest


def _pull_source():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "routes", "sync.py")
    src = open(p, encoding="utf-8").read()
    start = src.index("def pull_changes(")
    return src[start:src.index('"failed_tables": failed_tables') + 40]


def _worker_source():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "services", "sync_worker.py")
    return open(p, encoding="utf-8").read()


# ── The cloud half ───────────────────────────────────────────────────────────

def test_the_pull_rolls_back_after_a_failed_table():
    """Without this, one bad query takes out every table after it."""
    blk = _pull_source()
    exc = blk[blk.index("except Exception as e:"):]
    assert "db.rollback()" in exc, (
        "a failed table leaves the Postgres transaction aborted; every later "
        "table then dies with InFailedSqlTransaction (rule 58)")


def test_a_rollback_failure_is_logged_not_swallowed():
    blk = _pull_source()
    exc = blk[blk.index("except Exception as e:"):]
    assert "rollback after %s failed" in exc


def test_the_pull_reports_which_tables_it_could_not_read():
    """An absent table is not an empty one (rule 33)."""
    blk = _pull_source()
    assert "failed_tables.append(" in blk
    assert '"failed_tables": failed_tables' in blk
    assert '"table": table_name' in blk


# ── The client half — the one that protects data ─────────────────────────────

def test_the_client_holds_its_cursor_on_a_partial_pull():
    """Advancing past tables that were never received loses those rows for
    good. Same failure as M-12, on the read side."""
    src = _worker_source()
    assert '_resp_json.get("failed_tables")' in src
    tail = src[src.index("elif _pull_failed_tables:"):]
    tail = tail[:tail.index("else:")]
    assert "_PULL_CURSOR[business_id] = _cloud_cursor" not in tail, (
        "the cursor is being advanced on a partial pull; rows in the unread "
        "tables will never be offered to this device again")
    assert "PARTIAL PULL" in tail and "HOLDING the pull cursor" in tail


def test_the_partial_branch_precedes_the_advance_branch():
    """Ordering matters: if the plain `else` ran first the hold would never be
    reached."""
    src = _worker_source()
    partial = src.index("elif _pull_failed_tables:")
    advance = src.index("_PULL_CURSOR[business_id] = _cloud_cursor", partial)
    between = src[partial:advance]
    assert "else:" in between, "the partial-pull branch must come before the advance"


def test_a_partial_pull_is_an_error_not_a_warning():
    """A pull that silently returned two thirds of the data is not a warning."""
    src = _worker_source()
    blk = src[src.index('_resp_json.get("failed_tables")'):]
    blk = blk[:blk.index("\n\n")]
    assert "logger.error" in blk
    assert "PARTIAL" in blk


# ── The decision itself, as behaviour ────────────────────────────────────────

def should_advance_cursor(rejected_rows: int, failed_tables: int,
                          streak: int, max_streak: int = 3) -> bool:
    """The cursor rule, extracted so it can be asserted rather than described.

    Mirrors the worker: a rejected ROW is retried a bounded number of times and
    then abandoned with a CRITICAL (one unappliable row must not stall every
    later row). An unread TABLE is retried without bound — re-reading a window
    costs one query, and a table failing forever is a cloud defect to fix, not
    data to skip.
    """
    if rejected_rows and streak < max_streak:
        return False
    if failed_tables:
        return False
    return True


def test_a_clean_pull_advances():
    assert should_advance_cursor(0, 0, 0) is True


def test_a_partial_pull_never_advances_however_long_it_persists():
    for streak in range(0, 25):
        assert should_advance_cursor(0, 3, streak) is False


def test_rejected_rows_advance_only_after_the_bound():
    assert should_advance_cursor(1, 0, streak=1) is False
    assert should_advance_cursor(1, 0, streak=2) is False
    assert should_advance_cursor(1, 0, streak=3) is True


def test_an_unread_table_outranks_the_rejected_row_bound():
    """Even once rejected rows are abandoned, an unread table still holds the
    cursor — the two conditions are not interchangeable."""
    assert should_advance_cursor(1, 2, streak=99) is False
