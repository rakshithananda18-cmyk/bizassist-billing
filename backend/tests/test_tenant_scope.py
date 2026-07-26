"""
tests/test_tenant_scope.py — review finding S-3.
================================================
The gate on ``core/sync/tenant_scope.py``.

S-3 was: *no DB-level guard behind the tenant filter on SQLite.* RLS protects the
cloud; a local install is SQLite, where ``business_id`` filtering is
application-only, and there is nothing underneath to catch a missing filter. The
assumption that made this tolerable — "desktop installs are single-tenant" — was
retired by the B2B mirror, which writes a counterparty's rows into the local
database on purpose.

There is no database layer to move the rule into, so the rule is enforced here
instead: **a new unscoped read on a tenant table fails the build**, with a file
and a line number. An audit is true on the day it is run; a test is true on every
run. That difference is the whole finding.

Honest about what this is: the analyser is syntactic and deliberately generous
(see the module docstring), so a clean result is a FLOOR on isolation, not a
proof of it. What it does guarantee is that the set of unscoped tenant reads
cannot grow without someone writing down why.
"""
import os

import pytest

from core.sync import tenant_scope

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def models():
    return tenant_scope.tenant_models()


@pytest.fixture(scope="module")
def scan_result(models):
    unparsed = []
    findings, scanned = tenant_scope.scan(BACKEND, models, unparsed=unparsed)
    return findings, scanned, unparsed


# ── The analyser has to actually be looking at something ─────────────────────

def test_owner_columns_are_discovered_from_live_metadata(models):
    """Guards against the check quietly passing because it found no tables.
    The model list comes from SQLAlchemy mappers, so it cannot drift from the
    schema — but it CAN come back empty if imports change, and an empty scan
    passes every other assertion here."""
    assert len(models) >= 30, (
        f"only {len(models)} tenant-scoped models discovered — the mapper "
        "registry is probably not fully imported, which would make this whole "
        "file vacuous"
    )
    # Anchors: the money tables must be recognised as tenant-scoped.
    for name in ("Invoice", "InvoicePayment", "JournalEntry", "RegisterShift"):
        assert name in models, f"{name} not recognised as tenant-scoped"
    assert "business_id" in models["Invoice"]


def test_two_sided_b2b_tables_are_recognised(models):
    """B2B rows are scoped by TWO owner columns, not one. If the analyser did
    not know that, it would report every correct B2B read as unscoped and the
    allow-list would have to swallow them."""
    assert set(models["B2BConnection"]) >= {"seller_business_id", "buyer_business_id"}
    assert set(models["B2BOrder"]) >= {"seller_business_id", "buyer_business_id"}


def test_scan_examines_a_meaningful_number_of_reads(scan_result):
    _, scanned, _ = scan_result
    assert scanned >= 200, (
        f"only {scanned} tenant-table reads examined; the walk is probably not "
        "reaching core/ + routes/ + services/"
    )


# ── The gate ─────────────────────────────────────────────────────────────────

def test_no_unscoped_tenant_reads(scan_result):
    findings, scanned, _ = scan_result
    assert not findings, (
        "Unscoped read(s) on tenant-scoped table(s). On a local SQLite install "
        "there is no RLS behind this filter, and the B2B mirror means the local "
        "DB holds more than one business's rows.\n\n"
        + tenant_scope.format_report(findings, scanned)
        + "\n\nEither add the owner filter, or — if the read is intentionally "
          "cross-tenant — add it to core/sync/tenant_scope.ALLOWED with the "
          "reason, which is a review decision."
    )


def test_allow_list_has_no_stale_entries():
    """A stale allowance is a documented exception to a security rule for code
    that no longer exists. The next reader trusts it."""
    stale = tenant_scope.unused_allowances(BACKEND)
    assert not stale, (
        "core/sync/tenant_scope.ALLOWED has entries that match no read any "
        f"more — remove them: {sorted(stale)}"
    )


def test_every_allowance_carries_a_reason():
    for key, reason in tenant_scope.ALLOWED.items():
        assert reason and len(reason) > 25, (
            f"allowance {key!r} has no substantive justification; an "
            "unexplained exception is indistinguishable from an oversight"
        )


# ── The analyser must be able to fail ────────────────────────────────────────

def test_analyser_detects_a_planted_unscoped_read(tmp_path, models):
    """A gate that cannot fail is not a gate. Plant a genuinely unscoped read
    and assert it is caught, so a future refactor that breaks detection is
    visible here rather than as a false clean bill of health."""
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "planted.py").write_text(
        "def leak(db):\n"
        "    return db.query(Invoice).filter(Invoice.status == 'PAID').all()\n",
        encoding="utf-8",
    )
    findings, scanned = tenant_scope.scan(str(tmp_path), models)[:2]
    assert scanned == 1
    assert len(findings) == 1
    assert findings[0].model == "Invoice"
    assert findings[0].func == "leak"


def test_analyser_accepts_a_scoped_read(tmp_path, models):
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "ok.py").write_text(
        "def scoped(db, business_id):\n"
        "    return (db.query(Invoice)\n"
        "            .filter(Invoice.business_id == business_id)\n"
        "            .all())\n",
        encoding="utf-8",
    )
    findings, scanned = tenant_scope.scan(str(tmp_path), models)
    assert scanned == 1
    assert findings == []


def test_two_sided_scoping_counts_as_scoped(tmp_path, models):
    """A B2B read filtered on either owner column is scoped. Asserted because
    the OR form is easy to miss when the analyser only looks for
    `business_id`."""
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "b2b.py").write_text(
        "def mine(db, me):\n"
        "    return (db.query(B2BConnection)\n"
        "            .filter(or_(B2BConnection.seller_business_id == me,\n"
        "                        B2BConnection.buyer_business_id == me))\n"
        "            .all())\n",
        encoding="utf-8",
    )
    findings, _ = tenant_scope.scan(str(tmp_path), models)
    assert findings == []


def test_lazy_filter_without_a_terminal_is_not_counted(tmp_path, models):
    """`.filter()` alone materialises nothing. Counting it would inflate the
    scanned total with reads that never happen."""
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "lazy.py").write_text(
        "def build(db):\n"
        "    return db.query(Invoice).filter(Invoice.status == 'PAID')\n",
        encoding="utf-8",
    )
    findings, scanned = tenant_scope.scan(str(tmp_path), models)
    assert (findings, scanned) == ([], 0)


# ── The specific call site S-3 named ─────────────────────────────────────────

def test_connection_load_requires_a_business_id():
    """`core.connection.service._load` used to fetch by primary key alone and
    rely on every caller following up with `is_party`. All four did — this was a
    convention, not a live exposure — but a convention is one new call site away
    from a cross-tenant read. The scope is now in the SQL, and `business_id` is
    keyword-only and REQUIRED so it cannot be omitted by accident."""
    import inspect

    from core.connection import service

    sig = inspect.signature(service._load)
    param = sig.parameters.get("business_id")
    assert param is not None, "_load no longer takes business_id"
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
        "business_id must be keyword-only so it can never be filled positionally "
        "by a caller that meant to pass something else"
    )
    assert param.default is inspect.Parameter.empty, (
        "business_id must have no default — a default is how a scope becomes "
        "optional, and an optional scope is no scope"
    )

    src = inspect.getsource(service._load)
    assert "seller_business_id" in src and "buyer_business_id" in src, (
        "_load must constrain BOTH owner columns in the query itself"
    )


def test_connection_load_returns_not_found_for_a_non_party():
    """Behavioural, not just structural: a stranger must get the same answer as
    for a row that does not exist. Distinguishing the two leaks the existence of
    other businesses' connections to anyone who can count integers.

    Uses REAL `users` rows rather than synthetic ids. Since N4 turned on SQLite
    foreign-key enforcement, `b2b_connections.seller_business_id` has to point at
    a business that exists — which is the point of that change.
    """
    import uuid

    from database.db import SessionLocal
    from database.models import User
    from core.models import B2BConnection
    from core.connection import service

    db = SessionLocal()
    created = []
    try:
        for label in ("seller", "buyer", "stranger"):
            u = User(username=f"scope_{label}_{uuid.uuid4().hex[:8]}", password="x",
                     business_name=f"Scope {label}", role="owner")
            db.add(u)
            db.commit()
            db.refresh(u)
            created.append(u)
        seller, buyer, stranger_biz = created

        conn = B2BConnection(
            seller_business_id=seller.id,
            buyer_business_id=buyer.id,
            status=service.STATUS_ACCEPTED,
            price_tier="standard",
            discount_pct=0.0,
            credit_limit=0.0,
            outstanding_balance=0.0,
            stock_visibility="exact",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        # Both parties can load it.
        assert service._load(db, conn.id, business_id=seller.id).id == conn.id
        assert service._load(db, conn.id, business_id=buyer.id).id == conn.id

        # A third business gets "not found" — identical to a missing row.
        with pytest.raises(ValueError) as stranger:
            service._load(db, conn.id, business_id=stranger_biz.id)
        with pytest.raises(ValueError) as missing:
            service._load(db, 99_999_999, business_id=stranger_biz.id)
        assert str(stranger.value) == str(missing.value), (
            "a non-party must not be able to distinguish 'not yours' from "
            "'does not exist'"
        )

        db.delete(conn)
        db.commit()
    finally:
        for u in reversed(created):
            try:
                db.delete(u)
                db.commit()
            except Exception:
                db.rollback()
        db.close()


# ── The gate must not go quiet on a file it cannot read ──────────────────────

def test_every_scanned_file_was_actually_parsed(scan_result):
    """A file the analyser cannot parse is NOT covered by this check, and must
    never be reported as a clean run.

    The original implementation did `except (SyntaxError, UnicodeDecodeError):
    continue`, which handed an unparseable file a **silent free pass on tenant
    scoping** — a hole in a security gate, presented as green. That is precisely
    the class of defect this whole review is about (architecture rule 13: a
    swallow is judged by what it protects), so the unreadable set is part of the
    result and this test fails on it."""
    _, _, unparsed = scan_result
    assert not unparsed, (
        "file(s) could not be parsed and are therefore UNCHECKED for tenant "
        f"scoping — fix or exclude them explicitly: {unparsed}"
    )


def test_an_unparseable_file_is_reported_not_skipped(tmp_path, models):
    """Proves the reporting works, by planting a file that cannot be parsed."""
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "broken.py").write_text(
        "def leak(db:\n    return db.query(Invoice).all()\n", encoding="utf-8")
    unparsed = []
    findings, scanned = tenant_scope.scan(str(tmp_path), models, unparsed=unparsed)
    assert len(unparsed) == 1, "an unparseable file was silently skipped"
    assert "broken.py" in unparsed[0]
    assert "SyntaxError" in unparsed[0]
    # And it must be visible in the human-readable report too.
    report = tenant_scope.format_report(findings, scanned, unparsed)
    assert "could NOT be parsed" in report and "broken.py" in report
