"""
tests/test_child_rows_reach_the_outbox.py — M-21: line items never synced. Ever.
================================================================================
THE DEFECT
----------
`_queue_change` declines any row whose business cannot be resolved, and
`_get_business_id` read one place: `obj.business_id`. Four child tables have no
such column, so the resolver returned None and the outbox refused every row of
all four — while `_SYNC_TABLES` listed them and the cloud's MODEL_MAP was
perfectly able to apply them.

The cloud could always receive line items. The client never sent one.

MEASURED ON THE REAL DATABASE, 2026-07-28
-----------------------------------------
    invoice_line_items          184 rows local, 0 EVER queued (whole history)
    purchase_invoice_line_items   0 rows local, 0 queued
    purchase_order_line_items     0 rows local, 0 queued
    stock_transfer_line_items     0 rows local, 0 queued

Seen live: invoice LCL-OW-0030 (Rs497, 2 items) synced to the cloud and rendered
there as "No items on this invoice". The header totals are columns ON the
invoice, so the document looked almost right — the money was correct and the
goods were missing. A cloud-side line-item audit reads a genuinely empty invoice
and cannot tell it from one that was never itemised.

WHY THE RESOLVER NEEDS THE CONNECTION
-------------------------------------
The parent invoice is often INSERTed in the same flush as its items, so it is
not yet visible to any other session. Resolving through `connection` — the one
the listener is already handed — is what makes the lookup see it.

RELATION TO M-20
----------------
Same asymmetry, different mechanism: apply-side supported, push-side impossible.
M-20 was a table missing from `_SYNC_TABLES`; this is a table present in it that
the resolver could never speak for. Fixing one did not fix the other, which is
why this file tests the property (every syncable table CAN produce a row) rather
than the four names.
"""
import json
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
from database.models import Base, Invoice, InvoiceLineItem


@pytest.fixture
def db():
    d = tempfile.mkdtemp(prefix="bizassist_child_",
                         dir=os.environ.get("BIZASSIST_TEST_TMPDIR") or None)
    engine = create_engine(f"sqlite:///{d}/test_child.db", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    s.execute(text(
        "INSERT INTO users (id, username, password, business_name, role, "
        "settings, parent_business_id, public_id) VALUES "
        "(7, 'o@t.test', 'x', 'B', 'owner', :s, NULL, :p)"),
        {"s": json.dumps({"general": {"hosting_mode": "hybrid"}}),
         "p": str(uuid.uuid4())})
    s.commit()
    yield s
    s.close()
    engine.dispose()
    shutil.rmtree(d, ignore_errors=True)


def queued(db, entity):
    return db.execute(text(
        "SELECT entity_id, payload FROM sync_queue WHERE entity = :e ORDER BY id"),
        {"e": entity}).fetchall()


def make_sale(db, n_items=2):
    """An invoice and its line items, in ONE flush — the real billing shape."""
    inv = Invoice(business_id=7, invoice_id="LCL-OW-0030", total_amount=497.0,
                  uid=str(uuid.uuid4()))
    db.add(inv)
    db.flush()
    for i in range(n_items):
        db.add(InvoiceLineItem(invoice_id=inv.id, product_name=f"P{i}",
                               quantity=1, unit_price=100.0, line_total=100.0,
                               uid=str(uuid.uuid4())))
    db.commit()
    return inv


# ══════════════════════════════════════════════════════════════════════════════
# 1. THE DEFECT, as the user saw it
# ══════════════════════════════════════════════════════════════════════════════

def test_line_items_of_a_synced_invoice_are_queued_too(db):
    """LCL-OW-0030: the invoice arrived, the items did not."""
    make_sale(db, n_items=2)
    assert len(queued(db, "invoices")) == 1
    assert len(queued(db, "invoice_line_items")) == 2, (
        "the invoice synced and its items did not - the cloud renders this as "
        "'No items on this invoice' while the totals look correct")


def test_the_queued_item_carries_its_parents_business(db):
    """The row is useless to the cloud if it is filed under the wrong tenant, so
    resolving to *a* business is not enough - it must be the invoice's."""
    make_sale(db, n_items=1)
    rows = db.execute(text(
        "SELECT business_id FROM sync_queue WHERE entity='invoice_line_items'"
    )).fetchall()
    assert [r[0] for r in rows] == [7]


def test_items_are_queued_when_the_parent_is_new_in_the_same_flush(db):
    """The parent invoice is INSERTed in the same transaction and is invisible
    to any other session. Resolving on a separate connection would find nothing
    and decline - silently, exactly as before."""
    inv = Invoice(business_id=7, invoice_id="SAME-FLUSH", total_amount=1.0,
                  uid=str(uuid.uuid4()))
    db.add(inv)
    db.flush()
    db.add(InvoiceLineItem(invoice_id=inv.id, product_name="P", quantity=1,
                           unit_price=1.0, line_total=1.0, uid=str(uuid.uuid4())))
    db.commit()
    assert len(queued(db, "invoice_line_items")) == 1


def test_an_item_update_is_queued(db):
    """Editing a sale must travel too, not just creating one."""
    make_sale(db, n_items=1)
    item = db.query(InvoiceLineItem).first()
    item.line_total = 999.0
    db.commit()
    ops = db.execute(text(
        "SELECT operation FROM sync_queue WHERE entity='invoice_line_items' "
        "ORDER BY id")).fetchall()
    assert [o[0] for o in ops] == ["INSERT", "UPDATE"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE GATE STILL GATES
# ══════════════════════════════════════════════════════════════════════════════

def test_a_local_only_business_still_queues_no_items(db):
    """The child now resolves a business - it must then obey that business's
    hosting_mode, not bypass it."""
    M._NOT_HYBRID_SEEN.clear()
    db.execute(text("UPDATE users SET settings = :s WHERE id = 7"),
               {"s": json.dumps({"general": {"hosting_mode": "local"}})})
    db.commit()
    make_sale(db, n_items=2)
    assert queued(db, "invoice_line_items") == []
    assert queued(db, "invoices") == []


def test_an_orphan_item_is_declined_not_misfiled(db):
    """An item pointing at an invoice that does not exist has no owner. Filing
    it under a guess would push one tenant's row into another's account."""
    db.add(InvoiceLineItem(invoice_id=999999, product_name="Orphan", quantity=1,
                           unit_price=1.0, line_total=1.0, uid=str(uuid.uuid4())))
    db.commit()
    assert queued(db, "invoice_line_items") == []


def test_an_item_cannot_have_a_null_parent_at_all(db):
    """The resolver returns None for a NULL parent, but it never gets the
    chance: the column is NOT NULL, so the database refuses first. Asserted
    rather than assumed — if that constraint were ever dropped, the ownerless
    row would reach the resolver and this test would stop describing reality."""
    from sqlalchemy.exc import IntegrityError
    db.add(InvoiceLineItem(invoice_id=None, product_name="NoParent", quantity=1,
                           unit_price=1.0, line_total=1.0, uid=str(uuid.uuid4())))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert M._get_business_id(
        InvoiceLineItem(invoice_id=None, product_name="x"), connection=None) is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. THE PROPERTY — the class of defect, not the four names
# ══════════════════════════════════════════════════════════════════════════════

def test_every_syncable_table_can_resolve_a_business():
    """THE REGRESSION GATE. A table in _SYNC_TABLES whose rows can never name a
    business is a table that can never sync, and nothing said so for either
    M-20 or M-21. Adding such a table now fails here instead of in production
    a fortnight later.
    """
    from database.sync_map import PULL_ONLY_TABLES
    mapped = {t.name: t for t in Base.metadata.tables.values()}
    unreachable = []
    for tbl in sorted(M._SYNC_TABLES):
        if tbl in PULL_ONLY_TABLES:
            continue
        t = mapped.get(tbl)
        if t is None:
            continue  # declared in core.models; covered by its own suite
        if "business_id" in t.columns:
            continue
        if tbl == "users":
            continue
        spec = M._BUSINESS_ID_VIA_PARENT.get(tbl)
        if spec is None:
            unreachable.append(tbl)
    assert unreachable == [], (
        f"{unreachable} are listed as syncable but have no business_id and no "
        f"parent mapping, so _get_business_id returns None and EVERY row is "
        f"silently declined - this is M-21")


def test_child_fk_columns_all_exist():
    """`stock_transfer_line_items` uses `transfer_id`, not the
    `stock_transfer_id` the table name suggests. A wrong name here resolves to
    None and re-creates the defect, so the map is checked against the schema
    rather than trusted."""
    mapped = {t.name: t for t in Base.metadata.tables.values()}
    bad = []
    for child, (parent, fk) in M._BUSINESS_ID_VIA_PARENT.items():
        ct, pt = mapped.get(child), mapped.get(parent)
        if ct is None or pt is None:
            bad.append(f"{child}: table missing")
        elif fk not in ct.columns:
            bad.append(f"{child}.{fk} does not exist "
                       f"(has: {sorted(c.name for c in ct.columns if c.name.endswith('_id'))})")
        elif "business_id" not in pt.columns:
            bad.append(f"{parent}.business_id does not exist")
    assert bad == [], bad
