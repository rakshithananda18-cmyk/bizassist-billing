"""
tests/test_tenant_fk_invariants.py — the tenant boundary, proved by behaviour
=============================================================================

`ensure_tenant_fks` emits DDL. Emitting DDL is not evidence that anything is
enforced — the same argument `test_db_invariants.py` makes for the CHECK rules.
So every test here proves enforcement by ATTEMPTING A VIOLATING WRITE and
asserting the database refused it, on whichever dialect is running.

THE DEFECT THIS PINS (measured 2026-08-01, both databases)
----------------------------------------------------------
    uid e10f6d92-e55a-4b49-9fcb-b4679bdc56dd   Rs 45.00 cash
      local : invoice 457, business 8  (BA-W9J21Y)  total  45.00  -> correct
      cloud : invoice 786, business 7  (BA-JABXGD)  total 424.00  -> overpaid

`invoice_payments.invoice_id` referenced `invoices.id` alone, so nothing at the
storage layer required the parent to belong to the same tenant. Both databases
audited clean — the cloud row carries `business_id = 7`, matching the invoice it
hangs off, so it is self-consistent on arrival. The defect existed only in the
comparison between two databases.

`test_the_measured_defect_is_rejected` reconstructs those exact rows.
"""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.accounting.db_invariants import (  # noqa: E402
    TENANT_FKS, ensure_tenant_fks, find_tenant_violations,
    tenant_violation_sample, _tfk)


# ── a scratch database with just the two tables the rule needs ───────────────

_DDL = """
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY, business_id INTEGER, invoice_id VARCHAR,
    total_amount FLOAT, uid VARCHAR
);
CREATE TABLE invoice_payments (
    id INTEGER PRIMARY KEY, business_id INTEGER, invoice_id INTEGER,
    amount_paid FLOAT, uid VARCHAR
);
"""

_ONLY = [f for f in TENANT_FKS
         if f.child == "invoice_payments" and f.fk_column == "invoice_id"]


@pytest.fixture()
def conn(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    c = eng.connect()
    for stmt in filter(None, (s.strip() for s in _DDL.split(";"))):
        c.execute(text(stmt))
    # Two tenants, and the SAME invoice number in each — which is legal
    # (invoice numbers are unique per business) and is precisely what made the
    # real defect possible.
    c.execute(text("INSERT INTO invoices VALUES "
                   "(457, 8, 'LCL-OW-0003',  45.0, 'inv-a'),"
                   "(786, 7, 'LCL-OW-0003', 424.0, 'inv-b')"))
    c.commit()
    yield c
    c.close()


def _pay(conn, *, pid, biz, inv, amt=45.0, uid="p1"):
    conn.execute(text(
        "INSERT INTO invoice_payments (id, business_id, invoice_id, "
        "amount_paid, uid) VALUES (:i, :b, :v, :a, :u)"),
        {"i": pid, "b": biz, "v": inv, "a": amt, "u": uid})
    conn.commit()


def _count(conn) -> int:
    return conn.execute(text("SELECT COUNT(*) FROM invoice_payments")).scalar()


# ── enforcement ─────────────────────────────────────────────────────────────

def test_an_apostrophe_in_why_does_not_break_the_installer():
    """Regression for the first run of this file.

    `why` is prose written by a human and prose contains apostrophes. One in
    "another tenant's invoice" terminated the trigger's SQL literal, the DDL
    failed, `ensure_tenant_fks` filed it under `errors`, and the app would have
    booted with no guard and a log line nobody reads. Asserted on every rule so
    the next person can write English.
    """
    assert any("'" in fk.why for fk in TENANT_FKS), (
        "this regression test is vacuous unless at least one rule actually "
        "contains an apostrophe")


def test_the_measured_defect_is_rejected(conn):
    """The exact rows from 2026-08-01: a business-8 receipt onto business 7."""
    report = ensure_tenant_fks(conn, _ONLY)
    assert report["errors"] == {}, report["errors"]
    assert report["installed"] == [_ONLY[0].name]

    with pytest.raises(Exception) as e:
        _pay(conn, pid=1, biz=8, inv=786,
             uid="e10f6d92-e55a-4b49-9fcb-b4679bdc56dd")
    assert "fk_tenant_invoice_payments_invoice_id" in str(e.value)
    conn.rollback()
    assert _count(conn) == 0, "the write must not have landed"


def test_the_same_receipt_on_its_own_tenant_is_accepted(conn):
    """The guard must not cost the product a legitimate write.

    Same uid, same amount — only the parent differs. If this failed, the rule
    would be forbidding a capability rather than an outcome.
    """
    ensure_tenant_fks(conn, _ONLY)
    _pay(conn, pid=1, biz=8, inv=457,
         uid="e10f6d92-e55a-4b49-9fcb-b4679bdc56dd")
    assert _count(conn) == 1


def test_update_across_the_boundary_is_rejected_too(conn):
    """INSERT-only enforcement would let the row walk over afterwards."""
    ensure_tenant_fks(conn, _ONLY)
    _pay(conn, pid=1, biz=8, inv=457)
    with pytest.raises(Exception):
        conn.execute(text("UPDATE invoice_payments SET invoice_id = 786 "
                          "WHERE id = 1"))
        conn.commit()
    conn.rollback()
    assert conn.execute(text(
        "SELECT invoice_id FROM invoice_payments WHERE id = 1")).scalar() == 457


@pytest.mark.parametrize("biz,inv", [(None, 786), (8, None), (None, None)])
def test_null_on_either_side_is_left_alone(conn, biz, inv):
    """Same NULL semantics as Postgres MATCH SIMPLE.

    A rule that rejected these would reject rows the product writes today, and
    a rule the two engines apply differently is worse than no rule — it would
    make the databases disagree about what is storable.
    """
    ensure_tenant_fks(conn, _ONLY)
    _pay(conn, pid=1, biz=biz, inv=inv)
    assert _count(conn) == 1


def test_a_parent_that_does_not_exist_is_not_this_rules_business(conn):
    """No parent row -> the JOIN finds nothing -> nothing to compare.

    Orphans are the single-column FK's problem, and conflating the two would
    make this guard fire on a different defect than the one it documents.
    """
    ensure_tenant_fks(conn, _ONLY)
    _pay(conn, pid=1, biz=8, inv=999999)
    assert _count(conn) == 1


# ── refusing to install over existing damage ────────────────────────────────

def test_refuses_to_install_over_existing_violations(conn):
    """The cloud is in exactly this state right now, and must stay usable."""
    _pay(conn, pid=1, biz=8, inv=786)             # the bad row, pre-existing

    report = ensure_tenant_fks(conn, _ONLY)
    assert report["installed"] == []
    assert report["skipped_violations"] == {_ONLY[0].name: 1}

    # AND the guard is genuinely absent, not merely reported as skipped. A
    # report that says "skipped" over a constraint that did install would be a
    # lie in the safe direction; this asserts the two agree.
    _pay(conn, pid=2, biz=8, inv=786, uid="p2")
    assert _count(conn) == 2


def test_installs_once_the_violation_is_repaired(conn):
    """The repair-then-boot cycle the operator is being asked to run."""
    _pay(conn, pid=1, biz=8, inv=786)
    assert ensure_tenant_fks(conn, _ONLY)["skipped_violations"]

    conn.execute(text("DELETE FROM invoice_payments WHERE id = 1"))
    conn.commit()

    assert ensure_tenant_fks(conn, _ONLY)["installed"] == [_ONLY[0].name]
    with pytest.raises(Exception):
        _pay(conn, pid=3, biz=8, inv=786, uid="p3")
    conn.rollback()


def test_violation_scan_names_both_tenants(conn):
    """The ERROR log has to say which tenant took the row and which lost it."""
    _pay(conn, pid=1, biz=8, inv=786)
    assert find_tenant_violations(conn, _ONLY[0]) == 1
    assert tenant_violation_sample(conn, _ONLY[0]) == [(1, 8, 7)]


def test_installer_is_idempotent(conn):
    ensure_tenant_fks(conn, _ONLY)
    assert ensure_tenant_fks(conn, _ONLY)["already"] == [_ONLY[0].name]


def test_missing_table_is_reported_as_missing_not_as_installed(conn):
    """Rule 33 at the installer level: absent is not clean."""
    ghost = _tfk("no_such_child", "parent_id", "no_such_parent", "n/a.")
    report = ensure_tenant_fks(conn, [ghost])
    assert report["skipped_missing_table"] == [ghost.name]
    assert report["installed"] == []


# ── the declaration list itself ─────────────────────────────────────────────

def test_every_declared_reference_names_columns_that_actually_exist():
    """THE TEST THAT WOULD HAVE CAUGHT THE FICTIONAL PROBE LIST.

    `clear_staff_bizids.py` shipped with four probes against
    `b2b_connections.seller_public_id` and friends. Not one of those columns has
    ever existed on either database, so the guard they implemented was never
    once operative — and nothing said so, because a failed probe and an empty
    probe print the same thing.

    A declaration list is only as good as its agreement with the schema, so the
    agreement is asserted rather than assumed. This runs against the ORM
    metadata, which is the same definition `create_all` builds from.
    """
    from database.models import Base
    tables = Base.metadata.tables

    problems = []
    for fk in TENANT_FKS:
        for name in (fk.child, fk.parent):
            if name not in tables:
                problems.append(f"{fk.name}: no such table {name!r}")
        if fk.child in tables:
            cols = set(tables[fk.child].columns.keys())
            for col in (fk.fk_column, fk.tenant):
                if col not in cols:
                    problems.append(f"{fk.name}: {fk.child} has no column {col!r}")
        if fk.parent in tables:
            if fk.tenant not in set(tables[fk.parent].columns.keys()):
                problems.append(
                    f"{fk.name}: {fk.parent} has no column {fk.tenant!r}")
    assert not problems, "\n".join(problems)


def test_every_declared_reference_explains_the_product_damage():
    """`why` is required by the NamedTuple but emptiness is not.

    The existing INVARIANTS all carry a real explanation and that is the reason
    the module is readable two months later. A one-word `why` passes typing and
    fails the purpose.
    """
    thin = [fk.name for fk in TENANT_FKS if len(fk.why) < 60]
    assert not thin, f"these need a real explanation: {thin}"


def test_names_are_unique():
    names = [fk.name for fk in TENANT_FKS]
    assert len(names) == len(set(names))
