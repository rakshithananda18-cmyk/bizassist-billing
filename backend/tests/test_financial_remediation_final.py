"""Financial contracts spanning money commands, projections, quoting and upgrade shapes."""
import json
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, text, inspect, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database.models import Base, User, Product, Customer, Invoice, InvoiceLineItem, PurchaseInvoice
from core.models import B2BConnection, JournalEntry, JournalLine
from core.accounting import settlements, posting
from core.accounting.settlement_models import SupplierPayment, CustomerRefund, CustomerCreditAllocation
from core.accounting.settlement_schema import install_financial_schema
from core.billing import commands as billing
from core.billing.balances import invoice_balance, business_revenue_summary
from core.purchase.commands import accept_supplier_invoice, create_debit_note
from core.order import service as orders
from core.shifts import service as shifts
from core.api.reports import report_pnl


@pytest.fixture
def money():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    owner = User(id=940001, username="financial_owner", public_id="BA-FINAL-OWNER", password="unusable",
        role="enterprise", business_name="Financial fixture", state_code="29",
        settings=json.dumps({"transactions": {"round_off_enabled": False}}))
    buyer = User(id=940002, username="financial_buyer", public_id="BA-FINAL-BUYER", password="unusable",
        role="enterprise", business_name="Financial buyer", state_code="29")
    db.add_all([owner, buyer]); db.flush()
    product = Product(business_id=owner.id, name="Financial item", cost_price=40, selling_price=100,
        is_active=True, track_inventory=False, cgst_rate=0, sgst_rate=0, igst_rate=0)
    customer = Customer(business_id=owner.id, name="Financial customer")
    db.add_all([product, customer]); db.commit()
    yield db, owner, buyer, product, customer, Session, engine
    db.close(); engine.dispose()


def sale(money, *, price=100, paid=0, **kwargs):
    db, owner, _, product, customer, _, _ = money
    return billing.create_sale_invoice(db, business_id=owner.id, customer=customer.name,
        customer_id=customer.id, lines=[{"product_id": product.id, "quantity": 1, "unit_price": price}],
        paid_amount=paid, **kwargs)


def returned(money, invoice, quantity=1):
    db, owner, _, product, *_ = money
    return billing.create_credit_note(db, business_id=owner.id, original_invoice_id=invoice.id,
        lines=[{"product_id": product.id, "quantity": quantity}])


def purchase(money, number="P-1"):
    db, owner, *_ = money
    return accept_supplier_invoice(db, owner.id, {"supplier_name": "Supplier", "invoice_number": number,
        "invoice_date": "2026-10-30", "items": [{"product_name": number, "quantity": 1, "unit_price": 100}]})


def test_supplier_partial_payments_replay_and_balance(money):
    db, owner, *_ = money
    bill = purchase(money)
    row = settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
        purchase_invoice_id=bill.id, amount=30, payment_mode="Bank", idempotency_key="SUP-1")
    replay = settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
        purchase_invoice_id=bill.id, amount=30, payment_mode="Bank", idempotency_key="SUP-1")
    assert replay.id == row.id
    assert invoice_balance(db, bill, purchase=True)["outstanding"] == 70
    assert db.query(SupplierPayment).count() == 1
    assert posting.verify_chain(db, owner.id)["ok"]
    with pytest.raises(ValueError, match="different settlement"):
        settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
            purchase_invoice_id=bill.id, amount=31, payment_mode="Bank", idempotency_key="SUP-1")
    with pytest.raises(ValueError, match="exceeds"):
        settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
            purchase_invoice_id=bill.id, amount=71, payment_mode="Bank", idempotency_key="SUP-2")


def test_supplier_payment_respects_return_and_tenant(money):
    db, owner, buyer, *_ = money
    bill = purchase(money)
    create_debit_note(db, business_id=owner.id, original_purchase_id=bill.id,
        lines=[{"product_id": bill.line_items[0].product_id, "quantity": 0.5}])
    with pytest.raises(ValueError, match="exceeds"):
        settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
            purchase_invoice_id=bill.id, amount=60, payment_mode="Bank", idempotency_key="RETURN-EXCESS")
    with pytest.raises(ValueError, match="original purchase"):
        settlements.supplier_payment(db, business_id=buyer.id, operator_id=buyer.id,
            purchase_invoice_id=bill.id, amount=10, payment_mode="Bank", idempotency_key="FOREIGN")


def test_refund_credit_allocation_and_cash_reconcile(money):
    db, owner, _, _, _, _, _ = money
    shift = shifts.open_shift(db, business_id=owner.id, user_id=owner.id, opening_cash=0)
    original = sale(money, paid=100, shift_id=shift.id)
    credit = returned(money, original)
    target = sale(money, price=80, shift_id=shift.id)
    allocation = settlements.allocate_credit(db, business_id=owner.id, operator_id=owner.id,
        credit_note_id=credit.id, target_invoice_id=target.id, amount=60, idempotency_key="ALLOC-1")
    assert invoice_balance(db, original)["credit_due"] == 40
    assert invoice_balance(db, target)["outstanding"] == 20
    assert settlements.allocate_credit(db, business_id=owner.id, operator_id=owner.id,
        credit_note_id=credit.id, target_invoice_id=target.id, amount=60, idempotency_key="ALLOC-1").id == allocation.id
    refund = settlements.customer_refund(db, business_id=owner.id, operator_id=owner.id,
        credit_note_id=credit.id, amount=40, payment_mode="Cash", idempotency_key="REF-1")
    assert settlements.customer_refund(db, business_id=owner.id, operator_id=owner.id,
        credit_note_id=credit.id, amount=40, payment_mode="Cash", idempotency_key="REF-1").id == refund.id
    assert invoice_balance(db, original)["credit_due"] == 0
    assert shifts.compute_tally(db, shift)["expected_cash"] == 60
    with pytest.raises(ValueError, match="exceeds"):
        billing.record_payment(db, business_id=owner.id, invoice_id=target.id, amount_paid=21)
    billing.record_payment(db, business_id=owner.id, invoice_id=target.id, amount_paid=20, shift_id=shift.id)
    assert invoice_balance(db, target)["outstanding"] == 0
    assert invoice_balance(db, target)["credit_due"] == 0
    assert shifts.compute_tally(db, shift)["expected_cash"] == 80
    metrics = business_revenue_summary(db, owner.id)
    assert metrics["net_revenue"] == metrics["collected_revenue"] == 80
    assert db.query(CustomerCreditAllocation).count() == db.query(CustomerRefund).count() == 1


def test_unpaid_return_cannot_be_refunded_or_allocated(money):
    db, owner, *_ = money
    original = sale(money)
    credit = returned(money, original)
    target = sale(money, price=50)
    with pytest.raises(ValueError, match="available"):
        settlements.customer_refund(db, business_id=owner.id, operator_id=owner.id,
            credit_note_id=credit.id, amount=1, payment_mode="Bank", idempotency_key="UNPAID-REF")
    with pytest.raises(ValueError, match="available"):
        settlements.allocate_credit(db, business_id=owner.id, operator_id=owner.id,
            credit_note_id=credit.id, target_invoice_id=target.id, amount=1, idempotency_key="UNPAID-ALLOC")


def test_credit_cannot_move_between_customers(money):
    db, owner, _, _, _, _, _ = money
    original = sale(money, paid=100)
    credit = returned(money, original)
    target = billing.create_sale_invoice(db, business_id=owner.id, customer="Different customer",
        lines=[{"product_name": "Service", "quantity": 1, "unit_price": 50}])
    with pytest.raises(ValueError, match="same named customer"):
        settlements.allocate_credit(db, business_id=owner.id, operator_id=owner.id,
            credit_note_id=credit.id, target_invoice_id=target.id, amount=1, idempotency_key="WRONG-CUSTOMER")


def test_cash_settlement_requires_shift_and_closed_period_rolls_back(money):
    db, owner, *_ = money
    bill = purchase(money)
    with pytest.raises(ValueError, match="shift_required"):
        settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
            purchase_invoice_id=bill.id, amount=1, payment_mode="Cash", idempotency_key="NO-SHIFT")
    from core.accounting.period_lock import lock_period
    lock_period(db, business_id=owner.id, through="2026-10-30")
    with pytest.raises(ValueError):
        settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
            purchase_invoice_id=bill.id, amount=10, payment_mode="Bank", payment_date="2026-10-30", idempotency_key="CLOSED")
    db.rollback()
    assert db.query(SupplierPayment).count() == 0


@pytest.mark.parametrize("amount", [-1, 0, float("nan"), float("inf"), 1e16])
def test_settlement_nonfinite_negative_and_overflow_rejected(money, amount):
    db, owner, *_ = money
    with pytest.raises(ValueError):
        settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
            purchase_invoice_id=99999, amount=amount, payment_mode="Bank", idempotency_key="INVALID")


def test_zero_cost_return_and_unknown_legacy_cost_are_distinct(money):
    db, owner, _, product, *_ = money
    product.cost_price = 0; db.commit()
    original = sale(money)
    product.cost_price = 40; db.commit()
    returned(money, original)
    rows = report_pnl(from_date=None, to_date=None, current_user={"id": owner.id}, db=db)
    cogs = next(row for row in rows if row["metric"] == "Cost of Goods Sold (COGS)")
    assert cogs["amount"] == 0 and cogs["complete"]
    legacy = Invoice(business_id=owner.id, invoice_id="UNKNOWN-LEGACY", total_amount=100, amount=100, status="Pending")
    db.add(legacy); db.flush()
    db.add(InvoiceLineItem(invoice_id=legacy.id, product_id=product.id, product_name=product.name,
        quantity=1, unit_price=100, taxable_value=100, line_total=100, cost_price=0))
    db.commit()
    rows = report_pnl(from_date=None, to_date=None, current_user={"id": owner.id}, db=db)
    cogs = next(row for row in rows if row["metric"] == "Cost of Goods Sold (COGS)")
    assert cogs["amount"] is None and not cogs["complete"] and cogs["missing_cost_lines"] == 1


def test_upgrade_installs_existing_dn_index_and_does_not_guess_cost(money):
    db, owner, _, product, _, _, engine = money
    original = sale(money)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_purchase_invoices_biz_dn"))
        # Recreate the predecessor shape without today's feed triggers, whose
        # payload explicitly names today's snapshot columns. This is fixture DDL,
        # not an upgrade that drops business columns in the product.
        trigger_names = conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='invoice_line_items'")).scalars().all()
        for trigger_name in trigger_names:
            conn.execute(text("DROP TRIGGER " + conn.dialect.identifier_preparer.quote(trigger_name)))
        conn.execute(text("ALTER TABLE invoice_line_items DROP COLUMN cost_price"))
        conn.execute(text("ALTER TABLE invoice_line_items DROP COLUMN cost_snapshot_known"))
        install_financial_schema(conn)
        assert conn.execute(text("SELECT cost_price FROM invoice_line_items")).scalar() is None
        assert conn.execute(text("SELECT cost_snapshot_known FROM invoice_line_items")).scalar() is None
    assert any(index["name"] == "uq_purchase_invoices_biz_dn" for index in inspect(engine).get_indexes("purchase_invoices"))


@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("rounding", [False, True])
def test_order_uses_shared_math_and_immutable_destination(money, inclusive, rounding):
    db, owner, buyer, product, *_ = money
    owner.settings = json.dumps({"transactions": {"round_off_enabled": rounding}})
    product.selling_price = 100.5; product.cgst_rate = product.sgst_rate = 9; product.igst_rate = 18
    db.add(B2BConnection(seller_business_id=owner.id, buyer_business_id=buyer.id,
        status="accepted", price_tier="standard", discount_pct=3, stock_visibility="exact")); db.commit()
    with patch("core.templates.loader.resolve_for", return_value={"billing": {"tax_inclusive_default": inclusive}}):
        order = orders.create_order(db, buyer.id, owner.id, [{"product_id": product.id, "quantity": 3.7}])
    quoted = order.total_amount
    buyer.state_code = "27"; db.commit()
    for status in ("accepted", "packed", "dispatched", "completed"):
        orders.transition_order_status(db, owner.id, order.id, status)
    final = db.get(Invoice, order.seller_invoice_id)
    assert final.total_amount == quoted
    assert final.place_of_supply == "29" and final.igst_total == 0
    assert final.cgst_total > 0 and final.sgst_total > 0


def test_master_repost_does_not_hide_tampered_hash(money):
    db, owner, *_ = money
    sale(money)
    entry = db.query(JournalEntry).first(); old_hash = entry.entry_hash
    entry.narration = "Tampered fixture narration"; db.commit()
    from core.accounting.repost import repost_unposted_documents
    repost_unposted_documents(db, owner.id)
    assert entry.entry_hash == old_hash
    assert not posting.verify_chain(db, owner.id)["ok"]


def test_new_settlement_journal_reposts_idempotently(money):
    db, owner, *_ = money
    bill = purchase(money)
    row = settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
        purchase_invoice_id=bill.id, amount=10, payment_mode="Bank", idempotency_key="REPOST")
    from core.accounting.repost import repost_synced_row
    assert repost_synced_row(db, "supplier_payments", row).status == "existing"
    assert db.query(JournalEntry).filter(JournalEntry.source_type == "supplier_payment").count() == 1


def test_http_settlements_and_credit_sources_are_owner_scoped(money):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from database.db import get_db
    from services.auth import get_active_user
    from core.api.settlements import router
    db, owner, *_ = money
    bill = purchase(money)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_active_user] = lambda: {"id": owner.id, "user_id": owner.id, "role": "enterprise"}
    with TestClient(app) as client:
        result = client.post("/supplier-payments", json={"purchase_invoice_id": bill.id,
            "amount": 10, "payment_mode": "Bank", "idempotency_key": "HTTP"})
        assert result.status_code == 201, result.text
        assert client.get("/supplier-payments").json()["total"] == 1
        assert client.get("/customer-credits").json()["items"] == []
        app.dependency_overrides[get_active_user] = lambda: {"id": owner.id, "user_id": owner.id, "role": "cashier"}
        assert client.get("/supplier-payments").status_code == 403


def test_all_collection_surfaces_use_remaining_dues(money):
    from services import actions, recommendations, charts, insights_service
    from services.handlers import invoices as invoice_handlers
    from services.tools import invoices as invoice_tools
    db, owner, _, _, _, Session, _ = money
    invoice = sale(money, paid=20)
    returned(money, invoice, quantity=0.5)
    invoice.status = "Overdue"; invoice.due_date = "2026-01-01"; db.commit()
    assert business_revenue_summary(db, owner.id)["overdue_revenue"] == 30
    with patch.object(invoice_tools, "SessionLocal", Session):
        assert json.loads(invoice_tools.get_top_debtors(owner.id))[0]["overdue_total"] == 30
        assert json.loads(invoice_tools.get_dso(owner.id))["outstanding"] == 30
        assert json.loads(invoice_tools.get_dso(owner.id))["total_billed"] == 50
        listed = json.loads(invoice_tools.get_invoice_list(owner.id, status="Overdue"))
        assert len(listed) == 1 and listed[0]["outstanding"] == 30 and listed[0]["amount"] == 50
        assert json.loads(invoice_tools.get_sales_growth(owner.id))["latest_month_billed"] == 50
    with patch.object(actions, "SessionLocal", Session), patch.object(actions, "email_configured", return_value=False):
        assert actions._reminders_preview(owner.id, {})["items"][0]["amount"] == 30
    with patch.object(invoice_handlers, "SessionLocal", Session):
        text = invoice_handlers._total_revenue(owner.id)
        assert "₹50" in text and "₹30" in text
    with patch.object(recommendations, "SessionLocal", Session), patch("services.memory_service.get_business_facts", return_value=[]):
        assert "Revenue: Rs.50" in recommendations.get_business_snapshot(owner.id)
    with patch.object(charts, "SessionLocal", Session):
        result = charts.build_chart_data("chart revenue status", owner.id)
        assert result["datasets"][0]["data"][result["labels"].index("Overdue")] == 30
    assert sum(row["amount"] for row in insights_service.dashboard_charts(owner.id, db)["aging_overview"]) == 30


def test_legacy_zero_total_and_modern_receipt_mix_are_preserved(money):
    db, owner, *_ = money
    db.add(Invoice(business_id=owner.id, invoice_id="LEGACY-PAID", amount=100,
                   total_amount=0, status="Paid", paid_amount=0))
    db.commit()
    sale(money, price=10, paid=10)
    summary = business_revenue_summary(db, owner.id)
    assert summary["net_revenue"] == summary["collected_revenue"] == 110


def test_financial_fact_edits_are_refused(money):
    db, owner, *_ = money
    bill = purchase(money)
    payment = settlements.supplier_payment(db, business_id=owner.id, operator_id=owner.id,
        purchase_invoice_id=bill.id, amount=10, payment_mode="Bank", idempotency_key="IMMUTABLE")
    payment.amount = 11
    with pytest.raises(ValueError, match="append-only"):
        db.commit()
    db.rollback()
    assert db.get(SupplierPayment, payment.id).amount == 10


def test_print_balances_preserve_fiscal_total_and_show_corrections(money):
    from core.billing.print_payload import build_print_payload
    db, owner, *_ = money
    original = sale(money, paid=100)
    note = returned(money, original, quantity=0.5)
    settlements.customer_refund(db, business_id=owner.id, operator_id=owner.id,
        credit_note_id=note.id, amount=30, payment_mode="Bank", idempotency_key="PRINT-REFUND")
    totals = build_print_payload(db, business_id=owner.id, invoice_no=original.invoice_id)["totals"]
    assert totals["grand_total"] == totals["original_total"] == 100
    assert totals["credited_amount"] == totals["adjusted_total"] == 50
    assert totals["cash_received"] == 100 and totals["amount_refunded"] == 30
    assert totals["amount_paid"] == 70 and totals["return_credit"] == 20
    assert totals["balance_due"] == 0
    note_totals = build_print_payload(db, business_id=owner.id, invoice_no=note.invoice_id)["totals"]
    assert note_totals["cash_received"] == note_totals["amount_paid"] == note_totals["balance_due"] == 0
    assert note_totals["amount_refunded"] == 30 and note_totals["return_credit"] == 20


def test_plain_bill_print_and_unpaid_return_never_invent_cash(money):
    from core.billing.print_payload import build_print_payload
    db, owner, *_ = money
    original = sale(money)
    totals = build_print_payload(db, business_id=owner.id, invoice_no=original.invoice_id)["totals"]
    assert totals["grand_total"] == totals["adjusted_total"] == totals["balance_due"] == 100
    assert totals["cash_received"] == totals["amount_paid"] == 0
    returned(money, original)
    totals = build_print_payload(db, business_id=owner.id, invoice_no=original.invoice_id)["totals"]
    assert totals["credited_amount"] == 100 and totals["balance_due"] == 0
    assert totals["cash_received"] == totals["return_credit"] == 0


def test_past_due_pending_invoice_is_overdue_without_scheduler_rewrite(money):
    from core.billing.balances import outstanding_rows
    db, owner, *_ = money
    invoice = sale(money, price=50, due_date="2020-01-01")
    assert invoice.status == "Pending"
    assert outstanding_rows(db, owner.id, overdue=True)[0].amount == 50
    assert business_revenue_summary(db, owner.id)["overdue_revenue"] == 50


def test_shift_uses_advance_identity_not_ambiguous_credit_tender(money):
    from core.models import InvoicePayment
    db, owner, *_ = money
    shift = shifts.open_shift(db, business_id=owner.id, user_id=owner.id, opening_cash=0)
    original = sale(money, paid=100, payment_mode="Credit", shift_id=shift.id)
    assert shifts.compute_tally(db, shift)["sales_other"] == 100
    assert business_revenue_summary(db, owner.id)["cash_received"] == 100
    target = sale(money, price=10)
    db.add(InvoicePayment(business_id=owner.id, invoice_id=target.id, amount_paid=10,
        payment_mode="Credit", shift_id=shift.id, idempotency_key=f"advance-credit::{target.id}"))
    db.commit()
    assert shifts.compute_tally(db, shift)["sales_other"] == 100
    assert business_revenue_summary(db, owner.id)["cash_received"] == 100


def test_legacy_partial_baseline_survives_new_receipts_without_new_legacy_cash_post(money):
    from core.billing.print_payload import build_print_payload
    from core.models import InvoicePayment
    db, owner, *_ = money
    legacy = Invoice(business_id=owner.id, invoice_id="LEGACY-PARTIAL", amount=100,
        total_amount=100, status="Partial", paid_amount=30, invoice_date="2026-01-01")
    db.add(legacy); db.commit()
    billing.record_payment(db, business_id=owner.id, invoice_id=legacy.id, amount_paid=20,
        idempotency_key="LEGACY-NEW")
    billing.record_payment(db, business_id=owner.id, invoice_id=legacy.id, amount_paid=10,
        idempotency_key="LEGACY-NEXT")
    assert legacy.legacy_paid_baseline == 30
    assert legacy.legacy_paid_baseline_source == "header_before_first_receipt"
    assert invoice_balance(db, legacy)["paid"] == 60
    assert invoice_balance(db, legacy)["outstanding"] == 40
    assert business_revenue_summary(db, owner.id)["cash_received"] == 60
    assert db.query(func.sum(InvoicePayment.amount_paid)).scalar() == 30
    assert db.query(func.sum(JournalLine.debit)).filter(JournalLine.account == posting.ACC_CASH).scalar() == 30
    assert build_print_payload(db, business_id=owner.id, invoice_no=legacy.invoice_id)["totals"]["cash_received"] == 60


def test_existing_receipts_do_not_turn_stale_header_into_verified_cash(money):
    db, owner, *_ = money
    modern = sale(money, paid=20)
    modern.legacy_paid_baseline = None
    modern.paid_amount = 90
    db.commit()
    billing.record_payment(db, business_id=owner.id, invoice_id=modern.id, amount_paid=10)
    assert modern.legacy_paid_baseline is None
    assert invoice_balance(db, modern)["paid"] == 30
    assert business_revenue_summary(db, owner.id)["cash_received"] == 30


def test_known_modern_header_without_receipts_does_not_invent_legacy_cash(money):
    db, owner, *_ = money
    modern = sale(money)
    modern.paid_amount = 90; modern.status = "Paid"; db.commit()
    assert modern.legacy_paid_baseline == 0
    assert invoice_balance(db, modern)["paid"] == 0
    assert business_revenue_summary(db, owner.id)["cash_received"] == 0
