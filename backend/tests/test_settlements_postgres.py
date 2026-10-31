"""Settlement command acceptance on a disposable, loopback PostgreSQL database.

SQLite runs skip this module. CI opts in through BIZASSIST_TEST_DATABASE_URL;
the test database is owned by its caller and must be disposable. No table drops,
SQLite fixture DDL, network calls or merchant data are used here.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, text
from sqlalchemy.exc import IntegrityError

from database.db import Base, SessionLocal, engine
from database.models import Customer, Product, User
from core.models import JournalEntry, JournalLine
from core.accounting import posting, settlements
from core.accounting.period_lock import PeriodLockedError, lock_period
from core.accounting.settlement_models import SupplierPayment, CustomerRefund, CustomerCreditAllocation
from core.accounting.settlement_schema import install_financial_schema
from core.billing import commands as billing
from core.billing.balances import business_revenue_summary, invoice_balance
from core.purchase.commands import accept_supplier_invoice
from core.shifts import service as shifts
from services.dates import biz_today_str


@pytest.fixture(scope="module")
def postgres_schema():
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL-only settlement integration; use a disposable loopback test database")
    if engine.url.host not in {"127.0.0.1", "localhost", "::1"} or "test" not in (engine.url.database or "").lower():
        pytest.fail("Settlement integration refuses a non-loopback or non-test database", pytrace=False)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_financial_schema(connection)
    yield


@pytest.fixture
def pg_money(postgres_schema):
    """Real committed transactions, with unique tenant identities per test."""
    tag = uuid4().hex
    # Startup's synthetic legacy owner may occupy id=1 without advancing the
    # PostgreSQL serial; use isolated identities without altering that sequence.
    owner_id = 1_000_000_000 + int(tag[:8], 16) % 500_000_000
    db = SessionLocal()
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "pg_advisory_xact_lock" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        owner = User(id=owner_id, username=f"pg_money_{tag}", public_id=f"PG-{tag}", password="unusable-test-only",
            role="enterprise", business_name="Postgres money fixture", state_code="29",
            settings=json.dumps({"hosting_mode": "cloud", "transactions": {"round_off_enabled": False}}))
        other = User(id=owner_id + 1, username=f"pg_other_{tag}", public_id=f"OTHER-{tag}", password="unusable-test-only",
            role="enterprise", business_name="Postgres other fixture", state_code="29",
            settings=json.dumps({"hosting_mode": "cloud"}))
        db.add_all([owner, other]); db.flush()
        customer = Customer(business_id=owner.id, name=f"Customer {tag}")
        product = Product(business_id=owner.id, name=f"Service {tag}", cost_price=40,
            selling_price=100, is_active=True, track_inventory=False, cgst_rate=0, sgst_rate=0, igst_rate=0)
        db.add_all([customer, product]); db.commit()
        yield SimpleNamespace(db=db, owner=owner, other=other, customer=customer,
            product=product, statements=statements, tag=tag)
    finally:
        db.rollback()
        db.close()
        event.remove(engine, "before_cursor_execute", observe)


def sale(fixture, amount=100, paid=0, shift_id=None, customer=None):
    customer = customer or fixture.customer
    return billing.create_sale_invoice(fixture.db, business_id=fixture.owner.id,
        customer=customer.name, customer_id=customer.id, paid_amount=paid, shift_id=shift_id,
        lines=[{"product_id": fixture.product.id, "quantity": 1, "unit_price": amount}])


def purchase(fixture):
    return accept_supplier_invoice(fixture.db, fixture.owner.id,
        {"supplier_name": "Postgres supplier", "invoice_number": f"PG-P-{fixture.tag}",
         "invoice_date": biz_today_str(),
         "items": [{"product_name": f"Purchased {fixture.tag}", "quantity": 1, "unit_price": 100}]})


def credit(fixture, original):
    return billing.create_credit_note(fixture.db, business_id=fixture.owner.id,
        original_invoice_id=original.id,
        lines=[{"product_id": fixture.product.id, "quantity": 1}])


def test_pg_supplier_payment_commits_once_and_replay_uses_postgres_lock(pg_money):
    f = pg_money; db = f.db
    bill = purchase(f)
    values = dict(business_id=f.owner.id, operator_id=f.owner.id, purchase_invoice_id=bill.id,
        amount=30, payment_mode="Bank", idempotency_key="pg-supplier-replay")
    first = settlements.supplier_payment(db, **values)
    first_id = first.id
    # A second session proves the command really committed and the replay sees
    # durable facts, rather than merely reusing an identity-map object.
    with SessionLocal() as replay_db:
        replay = settlements.supplier_payment(replay_db, **values)
        assert replay.id == first_id
        assert replay_db.query(SupplierPayment).filter(SupplierPayment.business_id == f.owner.id).count() == 1
    assert invoice_balance(db, bill, purchase=True)["outstanding"] == 70
    assert db.query(JournalEntry).filter(JournalEntry.business_id == f.owner.id,
        JournalEntry.source_type == "supplier_payment").count() == 1
    assert any(":namespace" in statement or "%(namespace)" in statement for statement in f.statements)
    assert posting.verify_chain(db, f.owner.id)["ok"]
    with pytest.raises(ValueError, match="different settlement"):
        settlements.supplier_payment(db, **{**values, "amount": 31})
    db.rollback()
    with pytest.raises(ValueError, match="exceeds"):
        settlements.supplier_payment(db, **{**values, "amount": 71, "idempotency_key": "pg-overpay"})
    db.rollback()


def test_pg_supplier_cash_requires_shift_and_closed_period_rolls_back(pg_money):
    f = pg_money; db = f.db
    bill = purchase(f)
    values = dict(business_id=f.owner.id, operator_id=f.owner.id, purchase_invoice_id=bill.id,
        amount=10, payment_mode="Cash", idempotency_key="pg-cash")
    with pytest.raises(ValueError, match="shift_required"):
        settlements.supplier_payment(db, **values)
    db.rollback()
    shift = shifts.open_shift(db, business_id=f.owner.id, user_id=f.owner.id, opening_cash=100)
    payment = settlements.supplier_payment(db, **values)
    assert payment.shift_id == shift.id
    assert shifts.compute_tally(db, shift)["expected_cash"] == 90
    lock_period(db, business_id=f.owner.id, through=biz_today_str()); db.commit()
    with pytest.raises(PeriodLockedError):
        settlements.supplier_payment(db, **{**values, "idempotency_key": "pg-closed", "payment_mode": "Bank"})
    db.rollback()
    assert db.query(SupplierPayment).filter(SupplierPayment.business_id == f.owner.id).count() == 1
    assert invoice_balance(db, bill, purchase=True)["outstanding"] == 90
    assert posting.verify_chain(db, f.owner.id)["ok"]


def test_pg_paid_return_refund_and_same_customer_allocation_reconcile(pg_money):
    f = pg_money; db = f.db
    shift = shifts.open_shift(db, business_id=f.owner.id, user_id=f.owner.id, opening_cash=0)
    original = sale(f, paid=100, shift_id=shift.id)
    note = credit(f, original)
    target = sale(f, amount=80)
    stranger = Customer(business_id=f.owner.id, name="Different customer"); db.add(stranger); db.commit()
    wrong_target = sale(f, amount=10, customer=stranger)
    with pytest.raises(ValueError, match="same named customer"):
        settlements.allocate_credit(db, business_id=f.owner.id, operator_id=f.owner.id,
            credit_note_id=note.id, target_invoice_id=wrong_target.id, amount=1, idempotency_key="pg-wrong-customer")
    db.rollback()
    allocation_values = dict(business_id=f.owner.id, operator_id=f.owner.id, credit_note_id=note.id,
        target_invoice_id=target.id, amount=60, idempotency_key="pg-allocation")
    allocation = settlements.allocate_credit(db, **allocation_values)
    assert settlements.allocate_credit(db, **allocation_values).id == allocation.id
    refund_values = dict(business_id=f.owner.id, operator_id=f.owner.id, credit_note_id=note.id,
        amount=40, payment_mode="Cash", idempotency_key="pg-refund")
    refund = settlements.customer_refund(db, **refund_values)
    assert settlements.customer_refund(db, **refund_values).id == refund.id
    assert invoice_balance(db, original)["credit_due"] == 0
    assert invoice_balance(db, target)["outstanding"] == 20
    assert invoice_balance(db, wrong_target)["outstanding"] == 10
    assert shifts.compute_tally(db, shift)["expected_cash"] == 60
    assert business_revenue_summary(db, f.owner.id)["cash_received"] == 100
    assert business_revenue_summary(db, f.owner.id)["collected_revenue"] == 60
    assert db.query(CustomerRefund).filter(CustomerRefund.business_id == f.owner.id).count() == 1
    assert db.query(CustomerCreditAllocation).filter(CustomerCreditAllocation.business_id == f.owner.id).count() == 1
    for source in ("customer_refund", "customer_credit_allocation"):
        entry = db.query(JournalEntry).filter(JournalEntry.business_id == f.owner.id,
            JournalEntry.source_type == source).one()
        debit, credit_total = db.query(func.sum(JournalLine.debit), func.sum(JournalLine.credit)).filter(
            JournalLine.entry_id == entry.id).one()
        assert debit == credit_total
    assert posting.verify_chain(db, f.owner.id)["ok"]


def test_pg_settlement_commands_reject_foreign_tenant_sources(pg_money):
    f = pg_money; db = f.db
    bill = purchase(f)
    note = credit(f, sale(f, paid=100))
    target = sale(f, amount=80)
    common = dict(business_id=f.other.id, operator_id=f.other.id, amount=1)
    with pytest.raises(ValueError, match="original purchase"):
        settlements.supplier_payment(db, **common, purchase_invoice_id=bill.id,
            payment_mode="Bank", idempotency_key="foreign-purchase")
    db.rollback()
    with pytest.raises(ValueError, match="linked credit note"):
        settlements.customer_refund(db, **common, credit_note_id=note.id,
            payment_mode="Bank", idempotency_key="foreign-refund")
    db.rollback()
    with pytest.raises(ValueError, match="linked credit note"):
        settlements.allocate_credit(db, **common, credit_note_id=note.id,
            target_invoice_id=target.id, idempotency_key="foreign-allocation")
    db.rollback()
    for model in (SupplierPayment, CustomerRefund, CustomerCreditAllocation):
        assert db.query(model).filter(model.business_id.in_([f.owner.id, f.other.id])).count() == 0


def test_pg_database_rejects_cross_tenant_parent_and_posted_fact_edit(pg_money):
    f = pg_money; db = f.db
    bill = purchase(f)
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO supplier_payments "
            "(business_id,uid,purchase_invoice_id,amount,payment_mode,payment_date,operator_id,operator_name,idempotency_key) "
            "VALUES (:bid,:uid,:purchase,1,'Bank',:date,:operator,'Test operator','raw-cross-tenant')"),
            {"bid": f.other.id, "uid": str(uuid4()), "purchase": bill.id,
             "date": biz_today_str(), "operator": f.other.id})
    db.rollback()
    payment = settlements.supplier_payment(db, business_id=f.owner.id, operator_id=f.owner.id,
        purchase_invoice_id=bill.id, amount=10, payment_mode="Bank", idempotency_key="pg-immutable")
    payment_id = payment.id
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE supplier_payments SET amount=11 WHERE id=:id"), {"id": payment_id})
    db.rollback()
    assert db.get(SupplierPayment, payment_id).amount == 10
