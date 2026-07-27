"""
tests/test_line_item_invariant.py — findings M-16 / M-17.
========================================================
An invoice must be made of exactly what the customer was billed:

    SUM(line_total) == total_amount + cash_discount - round_off

WHY THIS NEEDED A TEST OF ITS OWN

M-16 and M-17 are the same corruption twice: a batch process appended
`invoice_line_items` rows to invoices that were already complete. Nothing caught
it, for the reason that recurs throughout this review — **every subsystem was
individually correct.** The invoice headers were untouched. The journal is posted
from the headers, so it footed and the hash chain verified. The payment ledger
agreed. Only the *lines* were inflated, and no check compared the lines to the
document they belong to.

The cost was not cosmetic: COGS is computed as
`invoice_line_items x Product.cost_price`, so phantom lines inflate cost and sink
profit. M-16 made Brownie Factory read a Rs-6,715 loss instead of its real
Rs+4,648 profit. M-17 (business 6, 15 rows, Rs3,298.30) overstated COGS by
Rs2,422.57.

Two halves, and both matter:

  * the INVARIANT — invoices written by the billing command must satisfy it, so a
    future regression in `create_sale_invoice` is caught here rather than by an
    owner reading a wrong P&L;
  * the DETECTOR — `scripts/repair_line_items_by_invariant.find_offenders` must
    identify the intruders, pick the right survivors, and refuse to act when it
    cannot prove which side is wrong.

The header is treated as authoritative because it was written once, by the billing
command, at sale time — and the corrupting process never touched it. That is an
argument from evidence, not a preference, and the detector only ever acts when the
surviving rows reconcile to it exactly.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3

import pytest
from fastapi.testclient import TestClient

from main_groq import app
from database.db import SessionLocal
from database.models import Invoice, InvoiceLineItem

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "scripts")))
import repair_line_items_by_invariant as RLI          # noqa: E402

client = TestClient(app)
R2 = lambda x: round(float(x or 0.0), 2)


def _target(total, disc=0.0, roff=0.0):
    return R2((total or 0.0) + (disc or 0.0) - (roff or 0.0))


# ══════════════════════════════════════════════════════════════════════════════
# The invariant holds for invoices the product itself writes
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def shop():
    uname = f"linv_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": uname, "password": "TestPass123!",
                                     "business_name": "Line Invariant Co"})
    assert r.status_code == 200, r.text
    body = r.json()
    h = {"Authorization": f"Bearer {body['token']}"}
    rp = client.post("/products", headers=h, json={
        "name": "Inv Rice", "unit": "Nos", "selling_price": 100.0,
        "cost_price": 60.0, "track_inventory": False,
        "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0})
    assert rp.status_code in (200, 201), rp.text
    client.post("/shifts/open", headers=h, json={"opening_cash": 0.0})
    return {"h": h, "bid": body["id"], "pid": rp.json().get("id")}


def _sale(shop, qty=2, price=100.0, **extra):
    payload = {
        "items": [{"product_id": shop["pid"], "product": "Inv Rice",
                   "qty": qty, "price": price}],
        "gst_enabled": True, "place_of_supply": "29",
        "mark_paid": True, "payment_mode": "cash",
    }
    payload.update(extra)
    r = client.post("/invoices", headers=shop["h"], json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _rows(bid):
    db = SessionLocal()
    try:
        out = []
        for inv in db.query(Invoice).filter(Invoice.business_id == bid).all():
            lines = (db.query(InvoiceLineItem)
                     .filter(InvoiceLineItem.invoice_id == inv.id)
                     .order_by(InvoiceLineItem.id).all())
            out.append((inv, lines))
        return out
    finally:
        db.close()


def test_a_plain_sale_satisfies_the_invariant(shop):
    _sale(shop, qty=3)
    for inv, lines in _rows(shop["bid"]):
        if not lines:
            continue
        got = R2(sum(l.line_total or 0.0 for l in lines))
        want = _target(inv.total_amount, inv.cash_discount, inv.round_off)
        assert abs(got - want) <= RLI.TOLERANCE, (
            f"{inv.invoice_id}: lines {got} vs header target {want}")


def test_the_discount_and_round_off_live_on_the_header_not_the_lines(shop):
    """The formula's whole subtlety. A post-tax cash discount reduces the header
    total but NOT any line, so comparing SUM(line_total) against total_amount
    alone reports a false positive — which is exactly what the first version of
    audit check I did on five real business-7 invoices."""
    before = {inv.invoice_id for inv, _ in _rows(shop["bid"])}
    _sale(shop, qty=4, cash_discount=25.0)
    new = [(i, l) for i, l in _rows(shop["bid"]) if i.invoice_id not in before]
    assert new, "no new invoice was created"
    inv, lines = new[0]
    if not (inv.cash_discount or 0):
        pytest.skip("this build does not apply cash_discount from this payload")
    line_sum = R2(sum(l.line_total or 0.0 for l in lines))
    assert line_sum > R2(inv.total_amount), (
        "a discounted invoice must have lines totalling MORE than the header")
    assert abs(line_sum - _target(inv.total_amount, inv.cash_discount,
                                 inv.round_off)) <= RLI.TOLERANCE


def test_every_invoice_in_this_business_reconciles(shop):
    """The reconciliation invariant over everything this test rang up — the
    property M-16 and M-17 both violated."""
    checked = 0
    for inv, lines in _rows(shop["bid"]):
        if not lines or not R2(inv.total_amount):
            continue
        checked += 1
        got = R2(sum(l.line_total or 0.0 for l in lines))
        want = _target(inv.total_amount, inv.cash_discount, inv.round_off)
        assert abs(got - want) <= RLI.TOLERANCE, f"{inv.invoice_id}: {got} != {want}"
    assert checked >= 1


# ══════════════════════════════════════════════════════════════════════════════
# The detector — on a purpose-built SQLite fixture, no app involved
# ══════════════════════════════════════════════════════════════════════════════

def _mini_db(tmp_path, invoices):
    """A minimal schema with just the columns find_offenders reads.

    Deliberately hand-built rather than reusing the app's DB: the detector is a
    SQL-level tool that will be pointed at production databases of varying
    vintage, so it must work against the columns alone.
    """
    p = tmp_path / "mini.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE invoices (id INTEGER PRIMARY KEY, business_id INT,
                   invoice_id TEXT, total_amount REAL, cash_discount REAL,
                   round_off REAL, invoice_type TEXT)""")
    con.execute("""CREATE TABLE invoice_line_items (id INTEGER PRIMARY KEY,
                   invoice_id INT, product_name TEXT, quantity REAL,
                   unit_price REAL, line_total REAL, created_at TEXT)""")
    lid = 1
    for inv in invoices:
        con.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,NULL)",
                    (inv["id"], inv.get("biz", 1), inv["no"], inv["total"],
                     inv.get("disc", 0.0), inv.get("roff", 0.0)))
        for name, amt, ca in inv["lines"]:
            con.execute("INSERT INTO invoice_line_items VALUES (?,?,?,1,?,?,?)",
                        (lid, inv["id"], name, amt, amt, ca))
            lid += 1
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def test_detector_leaves_a_clean_invoice_alone(tmp_path):
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "OK-1", "total": 236.0,
         "lines": [("A", 118.0, "2026-07-01"), ("B", 118.0, "2026-07-01")]},
    ])
    repairable, unresolved = RLI.find_offenders(con)
    assert (repairable, unresolved) == ([], [])


def test_detector_finds_an_appended_phantom_row(tmp_path):
    """The M-17 shape: three genuine lines, then intruders appended later."""
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "C1-0004", "total": 566.0, "roff": 0.34,
         "lines": [("Coffee", 123.70, "2026-06-30"),
                   ("Sugar", 186.51, "2026-06-30"),
                   ("Wheat", 255.45, "2026-06-30"),
                   ("Sugar", 186.51, "2026-07-01"),
                   ("Wheat", 255.45, "2026-07-01")]},
    ])
    repairable, unresolved = RLI.find_offenders(con)
    assert not unresolved
    assert len(repairable) == 1
    e = repairable[0]
    assert e["keep_count"] == 3
    assert [l["id"] for l in e["delete"]] == [4, 5]
    assert e["delete_value"] == 441.96


def test_detector_separates_rows_created_on_the_SAME_day(tmp_path):
    """The case a date-scoped repair cannot touch, and the reason this detector
    uses insertion order instead. `OW-0001`: genuine Sugar and phantom Coffee were
    both written on 2026-06-29."""
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "OW-0001", "total": 187.0, "roff": 0.49,
         "lines": [("Sugar", 186.51, "2026-06-29"),
                   ("Coffee", 123.70, "2026-06-29")]},
    ])
    repairable, _ = RLI.find_offenders(con)
    assert repairable[0]["keep_count"] == 1
    assert repairable[0]["delete"][0]["product_name"] == "Coffee"


def test_detector_accounts_for_a_cash_discount(tmp_path):
    """Header 2533 + 500 discount − (−0.44) = 3033.44. Without the discount term
    this invoice looks broken by 500 and the detector would delete a real line."""
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "C1-0002", "total": 2533.0, "disc": 500.0, "roff": -0.44,
         "lines": [("A", 1007.16, "d1"), ("B", 1098.44, "d1"),
                   ("C", 804.10, "d1"), ("D", 123.70, "d1"),
                   ("Phantom", 123.70, "d2")]},
    ])
    repairable, unresolved = RLI.find_offenders(con)
    assert not unresolved
    assert repairable[0]["keep_count"] == 4
    assert repairable[0]["delete"][0]["product_name"] == "Phantom"


def test_detector_REFUSES_when_no_prefix_reconciles(tmp_path):
    """The most important test here. If the surviving rows cannot be proven to
    match a figure the invoice already stored, the tool must delete NOTHING and
    hand the invoice to a human. A repair that guesses which side is wrong is
    worse than the corruption it is chasing."""
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "WEIRD-1", "total": 1000.0,
         "lines": [("A", 111.11, "d1"), ("B", 222.22, "d1"),
                   ("C", 333.33, "d1")]},
    ])
    repairable, unresolved = RLI.find_offenders(con)
    assert repairable == []
    assert len(unresolved) == 1
    assert "no prefix" in unresolved[0]["reason"]
    assert "delete" not in unresolved[0]


def test_detector_ignores_zero_value_imported_invoices(tmp_path):
    """CSV-imported rows carry no totals. Flagging them would bury real findings
    under hundreds of false positives — the same trap audit section B documents."""
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "CSV-1", "total": 0.0,
         "lines": [("A", 500.0, "d1")]},
    ])
    assert RLI.find_offenders(con) == ([], [])


def test_detector_can_be_scoped_to_one_business(tmp_path):
    con = _mini_db(tmp_path, [
        {"id": 1, "biz": 6, "no": "SIX-1", "total": 100.0,
         "lines": [("A", 100.0, "d1"), ("Phantom", 50.0, "d2")]},
        {"id": 2, "biz": 7, "no": "SEVEN-1", "total": 200.0,
         "lines": [("A", 200.0, "d1"), ("Phantom", 60.0, "d2")]},
    ])
    only6, _ = RLI.find_offenders(con, business_id=6)
    assert [e["invoice_no"] for e in only6] == ["SIX-1"]
    both, _ = RLI.find_offenders(con)
    assert len(both) == 2


def test_tolerance_absorbs_paise_but_not_a_whole_line(tmp_path):
    """A 1.00 window covers rounding. It must not swallow a real duplicate — the
    smallest phantom row found in production was Rs123.70."""
    con = _mini_db(tmp_path, [
        {"id": 1, "no": "ROUND-1", "total": 100.0,
         "lines": [("A", 100.4, "d1")]},                     # 0.40 drift -> clean
        {"id": 2, "no": "DUP-1", "total": 100.0,
         "lines": [("A", 100.0, "d1"), ("B", 1.50, "d2")]},   # 1.50 -> flagged
    ])
    repairable, unresolved = RLI.find_offenders(con)
    assert [e["invoice_no"] for e in repairable] == ["DUP-1"]
    assert unresolved == []


def test_the_money_snapshot_covers_the_totals_that_must_not_move():
    """`money_snapshot` is what proves a repair changed only line items. If a
    field were dropped from it, a repair could move that number unnoticed —
    which is the entire point of rule 29."""
    db = SessionLocal()
    try:
        raw = db.get_bind().raw_connection()
        raw.row_factory = sqlite3.Row
        snap = RLI.money_snapshot(raw)
    finally:
        db.close()
    for key in ("invoices", "invoice_value", "paid_total", "payments",
                "payments_sum", "journal_dr", "journal_cr", "line_items",
                "line_value", "stock_rows"):
        assert key in snap, f"{key} missing from the money snapshot"


def test_repair_is_dry_run_unless_apply_is_passed():
    """Read the source rather than run it: the default must be inert."""
    import inspect
    src = inspect.getsource(RLI.main)
    assert 'if not args.apply:' in src
    # The DELETE is built per child table (`f"DELETE FROM {tbl} ..."`) now that the
    # repair covers both invoices and b2b_orders, so match the dynamic form. This
    # assertion caught that refactor, which is why it is written against the
    # statement rather than a hardcoded table name.
    del_at = src.index("DELETE FROM {tbl}")
    assert src.index('if not args.apply:') < del_at, \
        "the dry-run bail-out must precede any DELETE"
    assert "export written" in src and src.index("export written") < del_at, \
        "rows must be exported BEFORE the first write"


# ══════════════════════════════════════════════════════════════════════════════
# The DB-level overfill guard (M-16/M-17 prevention)
# ══════════════════════════════════════════════════════════════════════════════
#
# The obvious constraint — SUM(line_total) == total_amount — is UNIMPLEMENTABLE as
# a row-level trigger, and shipping it would have broken every sale. Verified in
# the code before designing this, not assumed:
#
#   * `create_sale_invoice` writes the header WITH its final total, flushes, and
#     only THEN adds line items one at a time. After line 1 of 3 the equality is
#     false.
#   * The sync pull applies `invoice_line_items` in its `_child_last` group, i.e.
#     AFTER the invoice, one row at a time. Same transient state, on every synced
#     document.
#
# So the guard asserts the ASYMMETRY instead: a legitimate build-up only fills UP
# TO the header target; the corruption EXCEEDS it.
#
# These tests exist to prove both halves — that it blocks the defect AND that it
# does not break a normal sale, a discounted sale, a credit note, or a sync apply.
# The second half is the one that would have caused an outage.

from sqlalchemy import text as _sql

GUARD = "ck_invoice_line_items_no_overfill"


def _guard_present(conn) -> bool:
    if conn.dialect.name == "postgresql":
        return bool(conn.execute(_sql(
            "SELECT 1 FROM pg_trigger WHERE tgname = :n"), {"n": GUARD}).fetchone())
    return bool(conn.execute(_sql(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name = :n"),
        {"n": GUARD}).fetchone())


@pytest.fixture()
def conn():
    from database.db import engine
    with engine.connect() as c:
        yield c
        try:
            c.rollback()
        except Exception:
            pass


@pytest.fixture()
def guard(conn):
    from database.migration import _ensure_line_item_overfill_guard
    _ensure_line_item_overfill_guard(conn)
    if not _guard_present(conn):
        pytest.skip("overfill guard not installed on this dialect/build")
    return conn


def _invoice(conn, *, total, disc=0.0, roff=0.0):
    """A header written the way create_sale_invoice writes it: total FIRST."""
    biz = conn.execute(_sql(
        "INSERT INTO users (username, password, business_name, role) "
        "VALUES (:u,'x','Overfill Co','owner')"),
        {"u": f"of_{uuid.uuid4().hex[:10]}"})
    bid = conn.execute(_sql("SELECT id FROM users ORDER BY id DESC LIMIT 1")).scalar()
    num = f"OFT-{uuid.uuid4().hex[:6]}"
    conn.execute(_sql(
        "INSERT INTO invoices (business_id, invoice_id, customer, amount, "
        "total_amount, cash_discount, round_off, status, invoice_date) VALUES "
        "(:b,:n,'C',:t,:t,:d,:r,'Paid','2026-07-27')"),
        {"b": bid, "n": num, "t": total, "d": disc, "r": roff})
    conn.commit()
    return conn.execute(_sql(
        "SELECT id FROM invoices WHERE invoice_id = :n"), {"n": num}).scalar()


def _add_line(conn, inv_id, amount, name="L"):
    conn.execute(_sql(
        "INSERT INTO invoice_line_items (invoice_id, product_name, quantity, "
        "unit_price, line_total) VALUES (:i,:n,1,:a,:a)"),
        {"i": inv_id, "n": name, "a": amount})
    conn.commit()


def test_the_guard_is_installed(guard):
    assert _guard_present(guard)


def test_lines_may_be_added_ONE_AT_A_TIME_up_to_the_header_total(guard):
    """The build-up case. This is how BOTH write paths behave — the billing
    command and the sync apply — and a `SUM == total` trigger would reject every
    intermediate insert here."""
    inv = _invoice(guard, total=600.0)
    for amt in (100.0, 200.0, 300.0):          # cumulative 100 -> 300 -> 600
        _add_line(guard, inv, amt)
    got = guard.execute(_sql(
        "SELECT ROUND(SUM(line_total),2) FROM invoice_line_items "
        "WHERE invoice_id = :i"), {"i": inv}).scalar()
    assert R2(got) == 600.0


def test_appending_a_line_to_a_COMPLETED_invoice_is_refused(guard):
    """The M-16/M-17 defect itself, now impossible."""
    from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError
    inv = _invoice(guard, total=236.0)
    _add_line(guard, inv, 236.0)
    with pytest.raises((IntegrityError, OperationalError, DatabaseError)) as exc:
        _add_line(guard, inv, 123.70, name="PHANTOM")
    guard.rollback()
    assert "M-17" in str(exc.value) or "exceed" in str(exc.value).lower()
    remaining = guard.execute(_sql(
        "SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id = :i"),
        {"i": inv}).scalar()
    assert remaining == 1, "the phantom row must not have landed"


def test_the_header_cash_discount_raises_the_ceiling(guard):
    """target = total + cash_discount - round_off. A discounted invoice legitimately
    has lines totalling MORE than its header, so ignoring the discount term would
    reject a real sale — the mirror of the false positives audit check I produced
    the first time it was written."""
    inv = _invoice(guard, total=180.0, disc=10.0, roff=-0.4)   # target 190.40
    _add_line(guard, inv, 190.40)                              # exactly the target
    assert guard.execute(_sql(
        "SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id = :i"),
        {"i": inv}).scalar() == 1


def test_a_paise_level_overshoot_is_tolerated(guard):
    """1.00 of tolerance for rounding. The smallest phantom row found in
    production was Rs123.70, so this cannot hide a real duplicate."""
    inv = _invoice(guard, total=100.0)
    _add_line(guard, inv, 100.0)
    _add_line(guard, inv, 0.40, name="ROUNDING")     # 0.40 over -> allowed
    assert R2(guard.execute(_sql(
        "SELECT SUM(line_total) FROM invoice_line_items WHERE invoice_id = :i"),
        {"i": inv}).scalar()) == 100.40


def test_the_guard_is_inert_on_a_zero_total_invoice(guard):
    """CSV-imported rows carry no totals. The guard must not block importing their
    lines — the same exemption audit section B and check I both make."""
    inv = _invoice(guard, total=0.0)
    for amt in (500.0, 250.0):
        _add_line(guard, inv, amt)
    assert guard.execute(_sql(
        "SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id = :i"),
        {"i": inv}).scalar() == 2


def test_a_normal_multi_line_sale_still_succeeds_through_the_API(guard, shop):
    """End-to-end through the billing command, which writes the header total
    BEFORE the lines. If the guard were an equality check this would 500."""
    r = client.post("/invoices", headers=shop["h"], json={
        "items": [{"product_id": shop["pid"], "product": "Inv Rice",
                   "qty": 2, "price": 100.0},
                  {"product_id": shop["pid"], "product": "Inv Rice",
                   "qty": 3, "price": 100.0}],
        "gst_enabled": True, "place_of_supply": "29",
        "mark_paid": True, "payment_mode": "cash"})
    assert r.status_code in (200, 201), r.text


def test_a_SYNC_APPLY_of_an_invoice_and_its_lines_still_succeeds(guard):
    """THE test that protects push/pull.

    The pull worker puts `invoice_line_items` in `_child_last`, so the invoice
    lands first — carrying its final total — and its lines arrive afterwards, one
    row at a time. That is indistinguishable at the row level from the M-17
    corruption except for one thing: the cumulative sum rises TO the target and
    never past it.

    If this test fails, every synced invoice's line items are being rejected and
    landing in the conflict log (M-12), which would be a far worse outage than the
    defect the guard exists to prevent.
    """
    inv = _invoice(guard, total=1534.0)     # header arrives first, as on pull
    for amt in (236.0, 236.0, 1062.0):      # lines arrive after, one at a time
        _add_line(guard, inv, amt)
    assert R2(guard.execute(_sql(
        "SELECT SUM(line_total) FROM invoice_line_items WHERE invoice_id = :i"),
        {"i": inv}).scalar()) == 1534.0


def test_the_guard_is_reinstalled_idempotently(conn):
    from database.migration import _ensure_line_item_overfill_guard
    _ensure_line_item_overfill_guard(conn)
    _ensure_line_item_overfill_guard(conn)      # must not raise or duplicate
    assert _guard_present(conn) or conn.dialect.name not in ("sqlite", "postgresql")


def test_the_repair_covers_BOTH_document_families(tmp_path):
    """M-16/M-17 were invoices; M-18 is the same corruption on `b2b_orders` — a
    record TWO businesses quote to each other. One spec drives both so the prefix
    rule cannot drift between them."""
    families = {(p, c) for p, c, *_ in RLI.SPECS}
    assert ("invoices", "invoice_line_items") in families
    assert ("b2b_orders", "b2b_order_line_items") in families


def test_b2b_orders_have_no_discount_column_in_their_target():
    """`b2b_orders` carries no cash_discount/round_off, so its target is the plain
    total. Using the invoice expression here would reference columns that do not
    exist and the whole check would error out rather than run."""
    for parent, _child, _fk, _label, target in RLI.SPECS:
        if parent == "b2b_orders":
            assert "cash_discount" not in target and "round_off" not in target
            assert "total_amount" in target


# ══════════════════════════════════════════════════════════════════════════════
# The REPORT the repair prints — 2026-07-27
# ══════════════════════════════════════════════════════════════════════════════
# A repair script's output is the only thing an operator ever reads, and this one
# said less than it knew. It banners "(M-17)" and printed "Every INVOICE's line
# items reconcile to its header" after checking BOTH families, so a clean B2B
# result was indistinguishable from a B2B family that had never been looked at —
# and in the 2026-07-27 session that is exactly the wrong conclusion it invited.
# Rule 33's converse: a check that DID look must say what it looked at.

def _mini_both(tmp_path, name="both.db"):
    """Both document families, minimal columns."""
    p = tmp_path / name
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, business_id INT,
            invoice_id TEXT, total_amount REAL, cash_discount REAL,
            round_off REAL, paid_amount REAL, invoice_type TEXT);
        CREATE TABLE invoice_line_items (id INTEGER PRIMARY KEY, invoice_id INT,
            product_name TEXT, quantity REAL, unit_price REAL, line_total REAL,
            created_at TEXT);
        CREATE TABLE b2b_orders (id INTEGER PRIMARY KEY, seller_business_id INT,
            buyer_business_id INT, order_number TEXT, total_amount REAL);
        CREATE TABLE b2b_order_line_items (id INTEGER PRIMARY KEY, order_id INT,
            product_name TEXT, quantity REAL, unit_price REAL, line_total REAL,
            created_at TEXT);
        INSERT INTO invoices VALUES (1,1,'INV-1',200.0,0.0,0.0,0.0,NULL);
        INSERT INTO invoice_line_items VALUES (1,1,'A',1,200.0,200.0,'2026-07-01');
        INSERT INTO b2b_orders VALUES (1,6,87,'ORD-1',300.0);
        INSERT INTO b2b_order_line_items VALUES (1,1,'B',1,300.0,300.0,'2026-07-01');
    """)
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def test_scan_scope_names_BOTH_families_and_what_each_covered(tmp_path):
    scope = RLI.scan_scope(_mini_both(tmp_path))
    by = {s["parent"]: s for s in scope}
    assert set(by) == {"invoices", "b2b_orders"}, (
        "the scope report must name every family in SPECS, or a clean verdict "
        "again has no stated subject")
    assert by["invoices"]["parents_scanned"] == 1
    assert by["invoices"]["children_scanned"] == 1
    assert by["b2b_orders"]["parents_scanned"] == 1
    assert by["b2b_orders"]["children_scanned"] == 1
    assert all(s["present"] for s in scope)


def test_an_ABSENT_family_is_reported_as_not_scanned_not_as_clean(tmp_path):
    """Rule 33. A family whose tables do not exist was not examined, and must
    never be folded into the all-clear."""
    con = _mini_both(tmp_path, "nob2b.db")
    con.execute("DROP TABLE b2b_order_line_items")
    con.commit()
    by = {s["parent"]: s for s in RLI.scan_scope(con)}
    assert by["b2b_orders"]["present"] is False
    assert by["invoices"]["present"] is True


def test_money_snapshot_survives_a_database_without_the_b2b_tables(tmp_path):
    """It used to raise `no such table` and kill the run BEFORE repairing a
    single invoice — on exactly the older installs most likely to need it."""
    con = _mini_both(tmp_path, "nob2b2.db")
    con.execute("DROP TABLE b2b_order_line_items")
    con.commit()
    snap = RLI.money_snapshot(con)                  # must not raise
    assert snap["b2b_lines"] == RLI.MISSING
    assert snap["b2b_line_value"] == RLI.MISSING
    assert snap["invoices"] == 1, "the measurable figures must still be measured"


def test_absent_is_reported_as_absent_and_never_as_zero(tmp_path):
    """`0` is a measurement; `absent` is not. A diff must not be able to claim a
    quantity it could not read."""
    con = _mini_both(tmp_path, "nob2b3.db")
    con.execute("DELETE FROM b2b_order_line_items")
    con.commit()
    assert RLI.money_snapshot(con)["b2b_lines"] == 0      # empty, but readable
    con.execute("DROP TABLE b2b_order_line_items")
    con.commit()
    assert RLI.money_snapshot(con)["b2b_lines"] == RLI.MISSING


def test_scope_respects_the_business_filter(tmp_path):
    """The scope report and the scan share `_business_filter`, so they cannot
    disagree about what was in scope — a scope line that overstates coverage
    would be worse than no scope line at all."""
    con = _mini_both(tmp_path, "scoped.db")
    by = {s["parent"]: s for s in RLI.scan_scope(con, business_id=99)}
    assert by["invoices"]["parents_scanned"] == 0
    assert by["b2b_orders"]["parents_scanned"] == 0, (
        "b2b_orders is scoped by seller OR buyer; business 99 owns neither")
    by6 = {s["parent"]: s for s in RLI.scan_scope(con, business_id=6)}
    assert by6["b2b_orders"]["parents_scanned"] == 1, (
        "business 6 is the SELLER on ORD-1 and must be in scope")


def test_find_offenders_with_scope_agrees_with_find_offenders(tmp_path):
    """The two entry points must not drift; the scope variant is the same scan."""
    con = _mini_both(tmp_path, "agree.db")
    r1, u1 = RLI.find_offenders(con)
    r2, u2, scope = RLI.find_offenders_with_scope(con)
    assert (r1, u1) == (r2, u2)
    assert len(scope) == len(RLI.SPECS)
