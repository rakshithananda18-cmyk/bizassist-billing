"""
tests/test_hosting_mode_gate.py — M-20a: the enqueue path never declines silently
=================================================================================
THE DEFECT
----------
`models._queue_change` gates every outbox write on
`users.settings.general.hosting_mode == "hybrid"`. Declining is CORRECT for a
local-only or cloud-only business — that is what the setting is for. Declining
SILENTLY was the defect: the block held four bare `return`s, so "this business
is deliberately not syncing" and "sync is broken" produced byte-identical
evidence, namely none.

WHAT IT COST, measured on the real database 2026-07-28
------------------------------------------------------
Business 7 wrote 42 syncable rows between 2026-07-12 16:20 and 2026-07-26 21:59
and queued NONE of them:

    invoices 6 · invoice_payments 11 · customers 1 · stock_ledger 21 ·
    register_shifts 3

Those three register_shifts are M-20's stranded parents. Every sale rung on them
sat deferred on the cloud because the shift they pointed at had never been
pushed. The whole incident starts here, and nothing logged a word of it.

Independently confirmed on business 8: after it was switched to hosting_mode
'local' it wrote 12 syncable rows, queued 0, and logged 0.

WHY THE MODE ITSELF CANNOT BE RECOVERED AFTER THE FACT
------------------------------------------------------
Flipping AWAY from hybrid is the one settings write this same gate refuses to
queue — by the time the after_update listener reads `settings`, the new value is
already there and it declines itself. So the flip leaves no trace in the outbox,
none in `updated_at` history (there is none), and none in the log. The line
these tests pin is the only trace there will ever be.

These tests run the REAL listener against a REAL sqlite database. No fakes, no
source-string matching.
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import database.models as M
from database.models import Base, Customer, User


# ── a real database with the real listeners attached ─────────────────────────

def _settings(mode):
    """The users.settings blob, shaped exactly as production stores it."""
    if mode is _ABSENT:
        return None
    return json.dumps({"general": {"hosting_mode": mode}})


_ABSENT = object()


@pytest.fixture
def db():
    # "test" in the filename: db.py's fail-closed guard requires it.
    #
    # BIZASSIST_TEST_TMPDIR exists because SQLite needs a real local filesystem:
    # on a network/bind mount it fails with "disk I/O error" on the first PRAGMA.
    # Unset (the normal case, including run_tests.bat) it uses the platform
    # default and this is a no-op.
    d = tempfile.mkdtemp(prefix="bizassist_gate_",
                         dir=os.environ.get("BIZASSIST_TEST_TMPDIR") or None)
    engine = create_engine(f"sqlite:///{d}/test_gate.db", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    yield s
    s.close()
    engine.dispose()
    shutil.rmtree(d, ignore_errors=True)


def make_business(db, bid, mode):
    """One owner user whose hosting_mode is `mode`."""
    db.execute(text(
        "INSERT INTO users (id, username, password, business_name, role, "
        "settings, parent_business_id, public_id) "
        "VALUES (:i, :n, 'x', 'B', 'owner', :s, NULL, :p)"),
        {"i": bid, "n": f"o{bid}@t.test", "s": _settings(mode),
         "p": str(uuid.uuid4())})
    db.commit()
    return bid


def write_syncable_row(db, bid):
    """A plain syncable INSERT — the thing that either lands in the outbox or
    does not."""
    c = Customer(business_id=bid, name="Cust", uid=str(uuid.uuid4()))
    db.add(c)
    db.commit()
    return c


def queued(db, bid):
    return db.execute(text(
        "SELECT entity, entity_id FROM sync_queue WHERE business_id = :b"),
        {"b": bid}).fetchall()


# ══════════════════════════════════════════════════════════════════════════════
# 1. THE GATE ITSELF — it must still gate
# ══════════════════════════════════════════════════════════════════════════════

def test_a_hybrid_business_queues_its_rows(db):
    """The control. If this fails the fix broke syncing outright."""
    make_business(db, 7, "hybrid")
    write_syncable_row(db, 7)
    assert len(queued(db, 7)) == 1


@pytest.mark.parametrize("mode", ["local", "cloud", None, "", "HYBRID", "hybrid "])
def test_a_non_hybrid_business_queues_nothing(db, mode):
    """Declining is correct and must stay correct — including for near-misses
    like 'HYBRID' and a trailing space, which are NOT hybrid."""
    make_business(db, 7, mode)
    write_syncable_row(db, 7)
    assert queued(db, 7) == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE FIX — it must never decline in silence
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mode", ["local", "cloud"])
def test_declining_for_hosting_mode_says_so(db, caplog, mode):
    """The single line that would have made M-20a a one-minute diagnosis
    instead of a fortnight-old 42-row hole."""
    M._NOT_HYBRID_SEEN.clear()
    make_business(db, 7, mode)
    with caplog.at_level(logging.INFO, logger="bizassist.sync_queue"):
        write_syncable_row(db, 7)
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs, "a syncable row was dropped from the outbox and NOTHING logged"
    joined = " ".join(msgs)
    assert "hosting_mode" in joined
    assert mode in joined, "the log must name the mode; 'not hybrid' alone does not say WHICH"
    assert "7" in joined, "the log must name the business"


def test_the_log_names_the_business_so_a_gap_can_be_scoped(db, caplog):
    """Two businesses, one syncing and one not, is the real situation. A message
    that did not name the business could not tell them apart."""
    M._NOT_HYBRID_SEEN.clear()
    make_business(db, 7, "hybrid")
    make_business(db, 8, "local")
    with caplog.at_level(logging.INFO, logger="bizassist.sync_queue"):
        write_syncable_row(db, 7)
        write_syncable_row(db, 8)
    assert len(queued(db, 7)) == 1
    assert queued(db, 8) == []
    said = " ".join(r.getMessage() for r in caplog.records
                    if "hosting_mode" in r.getMessage())
    assert "business_id=8" in said
    assert "business_id=7" not in said, "the syncing business must not be reported as skipped"


def test_a_business_with_no_settings_is_a_warning_not_a_shrug(db, caplog):
    """`settings` NULL means the mode is UNKNOWN, not 'local'. Guessing either
    way is wrong, so it is reported."""
    M._NOT_HYBRID_SEEN.clear()
    make_business(db, 7, _ABSENT)
    with caplog.at_level(logging.DEBUG, logger="bizassist.sync_queue"):
        write_syncable_row(db, 7)
    warn = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warn, "unknown hosting_mode dropped a row with no warning"
    assert "no settings" in " ".join(r.getMessage() for r in warn)


def test_unparseable_settings_are_reported_not_swallowed(db, caplog):
    """WAS a bare `except Exception: return`. Corrupt JSON silently disabled
    sync for the whole business."""
    M._NOT_HYBRID_SEEN.clear()
    make_business(db, 7, "hybrid")
    db.execute(text("UPDATE users SET settings = '{not json' WHERE id = 7"))
    db.commit()
    with caplog.at_level(logging.DEBUG, logger="bizassist.sync_queue"):
        write_syncable_row(db, 7)
    warn = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warn, "corrupt settings disabled sync and said nothing"
    assert "could not read hosting_mode" in " ".join(r.getMessage() for r in warn)


# ══════════════════════════════════════════════════════════════════════════════
# 3. THROTTLING — the log must be usable, not a flood
# ══════════════════════════════════════════════════════════════════════════════

def test_a_local_business_logs_once_per_table_not_once_per_row(db, caplog):
    """A local-only business declines on EVERY write. Unthrottled this buries
    the signal it exists to give, and someone turns the logger off."""
    M._NOT_HYBRID_SEEN.clear()
    make_business(db, 7, "local")
    with caplog.at_level(logging.INFO, logger="bizassist.sync_queue"):
        for _ in range(25):
            write_syncable_row(db, 7)
    hits = [r for r in caplog.records if "hosting_mode" in r.getMessage()]
    assert len(hits) == 1, f"expected 1 throttled line, got {len(hits)}"
    assert queued(db, 7) == []


def test_a_mode_change_is_reported_even_after_the_throttle_fired(db, caplog):
    """The throttle key includes the mode. A hybrid -> local flip mid-process is
    exactly the event worth knowing about, and must not be swallowed by an
    earlier entry for the same business and table."""
    M._NOT_HYBRID_SEEN.clear()
    make_business(db, 7, "cloud")
    with caplog.at_level(logging.INFO, logger="bizassist.sync_queue"):
        write_syncable_row(db, 7)
        db.execute(text("UPDATE users SET settings = :s WHERE id = 7"),
                   {"s": _settings("local")})
        db.commit()
        write_syncable_row(db, 7)
    modes = [m for m in ("cloud", "local")
             if any(m in r.getMessage() for r in caplog.records)]
    assert modes == ["cloud", "local"], f"both modes must be reported, got {modes}"


def test_the_throttle_set_is_bounded(db):
    """A key set that grows without limit is a memory leak in a process that
    runs for weeks."""
    M._NOT_HYBRID_SEEN.clear()
    for i in range(2100):
        M._note_not_hybrid(i, "invoices", "local")
    assert len(M._NOT_HYBRID_SEEN) <= 2001


def test_the_throttle_never_suppresses_the_first_report(db):
    """Whatever the bookkeeping does, the FIRST occurrence must always speak."""
    M._NOT_HYBRID_SEEN.clear()
    for i in range(3000):
        assert M._note_not_hybrid(i, "invoices", "local") is True, (
            f"business {i} was silently skipped by the throttle")


# ══════════════════════════════════════════════════════════════════════════════
# 4. THE HOLE IS REAL — rows written while non-hybrid never sync on their own
# ══════════════════════════════════════════════════════════════════════════════

def test_switching_to_hybrid_does_not_retroactively_queue_earlier_rows(db):
    """This is the property that turned a settings change into 42 lost rows.
    It is asserted, not lamented: the reconcile safety net exists BECAUSE this
    is true, and a future change that quietly "fixed" it would re-push history."""
    make_business(db, 7, "local")
    write_syncable_row(db, 7)
    write_syncable_row(db, 7)
    assert queued(db, 7) == []

    db.execute(text("UPDATE users SET settings = :s WHERE id = 7"),
               {"s": _settings("hybrid")})
    db.commit()
    write_syncable_row(db, 7)

    rows = queued(db, 7)
    assert len(rows) == 1, (
        "only the row written AFTER the switch is queued - the two written "
        "before it are invisible to the outbox forever, which is precisely "
        "what find_unqueued_syncable_rows() is for")
