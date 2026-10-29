"""Synthetic regressions from the 29 October money-sector review."""
import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func

from database.db import SessionLocal
from database.models import User, Product, Inventory, Invoice, PurchaseInvoice, Customer
from core.models import JournalEntry, JournalLine, StockLedger, Godown
from core.billing import commands as billing
from core.purchase import commands as purchases
from core.stock import ledger
from core.accounting import posting
from core.api.payments import RecordPaymentRequestFlexible, CreateExpenseRequest, CreditNoteLine
from core.api.parties import SettleDuesRequest
from core.api.purchases import DebitNoteLine
from core.api.reports import report_pnl
from routes.shifts import OpenShiftRequest, CloseShiftRequest, CashMovementRequest
from core.shifts import service as shifts
from tests.test_phase1b import client, auth_owner


@pytest.fixture
def shop():
    with SessionLocal() as db:
        token = uuid.uuid4().hex[:10]
        # Other suite fixtures seed explicit user IDs, leaving Postgres's serial
        # counter behind. This fixture tests money commands, not signup/sequence
        # recovery: allocate a free fixture identity without consuming stale IDs.
        owner_id = (db.query(func.max(User.id)).scalar() or 0) + 1
        owner = User(id=owner_id, username='money_fixture_' + token, public_id='BA-' + token.upper(),
                     password='unusable', state_code='29', business_name='Money audit fixture',
                     settings=json.dumps({'transactions': {'round_off_enabled': False}}))
        db.add(owner)
        db.flush()
        product = Product(business_id=owner.id, name='Snapshot fixture', unit='Nos',
                          selling_price=100, track_inventory=False, cgst_rate=0, sgst_rate=0, igst_rate=0)
        db.add(product)
        db.commit()
        yield db, owner, product
        db.rollback()


def sale(shop, *, qty=3, price=100, **options):
    db, owner, product = shop
    line_options = options.pop('line_options', {})
    return billing.create_sale_invoice(db, business_id=owner.id,
        lines=[{'product_id': product.id, 'quantity': qty, 'unit_price': price, **line_options}], **options)


def credit(shop, original, qty):
    db, owner, product = shop
    return billing.create_credit_note(db, business_id=owner.id, original_invoice_id=original.id,
                                     lines=[{'product_id': product.id, 'quantity': qty}])


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), 0, -1, 0.001])
def test_payment_and_settlement_commands_reject_invalid_amount_before_query(invalid):
    with pytest.raises(ValueError):
        billing.record_payment(None, business_id=1, invoice_id=1, amount_paid=invalid)
    with pytest.raises(ValueError):
        billing.settle_customer_dues(None, business_id=1, customer_id=1, amount=invalid)


@pytest.mark.parametrize('invalid', ['NaN', 'Infinity', '-Infinity'])
def test_money_request_schemas_reject_nonfinite_json_strings(invalid):
    for model, payload in (
        (RecordPaymentRequestFlexible, {'invoice_id': 1, 'amount': invalid}),
        (CreateExpenseRequest, {'expense_date': '2026-10-29', 'category': 'Rent', 'expense_type': 'Indirect', 'amount': invalid, 'payment_mode': 'Cash'}),
        (SettleDuesRequest, {'amount': invalid}),
        (CreditNoteLine, {'product_id': 1, 'product_name': 'Fixture', 'quantity': invalid, 'unit_price': 1}),
        (DebitNoteLine, {'product_id': 1, 'quantity': invalid}),
        (OpenShiftRequest, {'opening_cash': invalid}),
        (CashMovementRequest, {'movement_type': 'paid_in', 'category': 'change_top_up', 'amount': invalid}),
        (CloseShiftRequest, {'closing_cash_actual': 1, 'closing_upi_actual': invalid}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_discounted_sale_full_return_uses_saved_net_and_tax_snapshot(shop):
    original = sale(shop, bill_discount=15, line_options={'discount_pct': 10, 'cgst_rate': 9, 'sgst_rate': 9})
    returned = credit(shop, original, 3)
    assert returned.total_amount == original.total_amount
    assert returned.subtotal == original.subtotal
    assert returned.discount_total == original.discount_total
    assert returned.cgst_total == original.cgst_total
    assert returned.sgst_total == original.sgst_total


def test_tax_inclusive_sale_cannot_be_taxed_again_when_returned(shop):
    original = sale(shop, qty=2, price=118, tax_inclusive=True,
                    line_options={'cgst_rate': 9, 'sgst_rate': 9})
    returned = credit(shop, original, 2)
    assert original.total_amount == returned.total_amount == 236
    assert original.subtotal == returned.subtotal == 200
    assert returned.is_tax_inclusive is True


def test_partial_returns_consume_exact_remaining_paise_and_cess(shop):
    original = sale(shop, qty=3, price=.05,
                    line_options={'cgst_rate': 9, 'sgst_rate': 9, 'cess_rate': 10})
    notes = [credit(shop, original, 1) for _ in range(3)]
    for field in ('subtotal', 'cgst_total', 'sgst_total', 'cess_total', 'total_amount'):
        assert round(sum(getattr(note, field) for note in notes), 2) == getattr(original, field)
    with pytest.raises(ValueError, match='Cannot return'):
        credit(shop, original, 1)


def test_different_product_returns_share_header_adjustments_without_losing_paise(shop):
    db, owner, product = shop
    other = Product(business_id=owner.id, name='Second snapshot fixture', track_inventory=False)
    owner.settings = json.dumps({'transactions': {'round_off_enabled': True}})
    db.add(other)
    db.commit()
    original = billing.create_sale_invoice(db, business_id=owner.id, cash_discount=1.15, bill_discount=4.77,
        lines=[{'product_id': product.id, 'quantity': 2, 'unit_price': 19.95, 'cgst_rate': 2.5, 'sgst_rate': 2.5},
               {'product_id': other.id, 'quantity': 1, 'unit_price': 40, 'cgst_rate': 9, 'sgst_rate': 9}])
    notes = [billing.create_credit_note(db, business_id=owner.id, original_invoice_id=original.id,
        lines=[{'product_id': other.id, 'quantity': 1}]), credit(shop, original, 1), credit(shop, original, 1)]
    for field in ('subtotal', 'cgst_total', 'sgst_total', 'cash_discount', 'round_off', 'total_amount'):
        assert round(sum(getattr(note, field) for note in notes), 2) == getattr(original, field), field


def test_cash_discount_roundoff_and_journal_reverse_exactly_after_partial_returns(shop):
    db, owner, _ = shop
    owner.settings = json.dumps({'transactions': {'round_off_enabled': True}})
    db.commit()
    original = sale(shop, qty=3, price=33.33, cash_discount=2.25,
                    line_options={'cgst_rate': 9, 'sgst_rate': 9})
    notes = [credit(shop, original, 1) for _ in range(3)]
    assert round(sum(note.total_amount for note in notes), 2) == original.total_amount
    assert round(sum(note.cash_discount for note in notes), 2) == original.cash_discount
    assert round(sum(note.round_off for note in notes), 2) == original.round_off
    sums = {}
    for row in db.query(JournalLine).join(JournalEntry).filter(JournalEntry.business_id == owner.id):
        sums[row.account] = sums.get(row.account, 0) + (row.debit or 0) - (row.credit or 0)
    assert all(round(value, 2) == 0 for value in sums.values()), sums
    metrics = {row['metric']: row['amount'] for row in report_pnl(from_date=None, to_date=None, current_user={'id': owner.id}, db=db)}
    assert metrics['Sales Revenue (Journal, GST-exclusive)'] == 0
    assert metrics['GST Payable (Tax collected — liability, not income)'] == 0
    assert metrics['Discount Allowed (Contra-revenue)'] == 0
    assert metrics['Journal-Invoice reconciliation delta (0 = fully posted)'] == 0


def test_duplicate_sales_return_rows_and_return_of_return_are_rejected(shop):
    db, owner, product = shop
    original = sale(shop, qty=3)
    with pytest.raises(ValueError, match='duplicate'):
        billing.create_credit_note(db, business_id=owner.id, original_invoice_id=original.id,
            lines=[{'product_id': product.id, 'quantity': 2}, {'product_id': product.id, 'quantity': 2}])
    db.rollback()
    assert db.query(Invoice).filter_by(parent_invoice_id=original.id).count() == 0
    returned = credit(shop, original, 1)
    with pytest.raises(ValueError, match='original sale'):
        credit(shop, returned, 1)


def test_return_stock_uses_original_godown_batch_and_expiry(shop):
    db, owner, product = shop
    product.track_inventory = True
    godown = Godown(business_id=owner.id, name='Fixture godown')
    db.add(godown)
    db.commit()
    original = sale(shop, qty=1.5, godown_id=godown.id, line_options={'batch_no': 'LOT-FIXTURE'})
    original.line_items[0].expiry_date = '2027-12-31'
    db.commit()
    returned = credit(shop, original, .5)
    movement = db.query(StockLedger).filter_by(reference_type='credit_note', reference_id=returned.id).one()
    assert (movement.godown_id, movement.batch_no, movement.expiry_date, movement.qty_delta) == (godown.id, 'LOT-FIXTURE', '2027-12-31', .5)


def test_new_inventory_cache_preserves_fractional_balance(shop):
    db, owner, product = shop
    assert db.query(Inventory).filter_by(product_id=product.id).first() is None
    ledger.record_movement(db, business_id=owner.id, product_id=product.id,
                           product_name=product.name, movement_type=ledger.OPENING, qty_delta=.375)
    db.commit()
    assert db.query(Inventory).filter_by(product_id=product.id).one().stock == .375


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf')])
def test_stock_command_rejects_nonfinite_quantity_before_database_access(invalid):
    with pytest.raises(ValueError, match='finite'):
        ledger.record_movement(None, business_id=1, product_name='Fixture',
                               movement_type=ledger.ADJUSTMENT, qty_delta=invalid)


def test_purchase_header_discount_roundoff_and_cess_are_returned_exactly(shop):
    db, owner, product = shop
    original = purchases.accept_supplier_invoice(db, owner.id, {
        'supplier_name': 'Fixture supplier', 'invoice_number': 'PUR-' + uuid.uuid4().hex,
        'invoice_date': '2026-10-29', 'status': 'confirmed',
        'discount_total': .07, 'round_off': .01, 'cess_total': .03,
        'items': [{'product_id': product.id, 'product_name': product.name, 'quantity': 3,
                   'unit_price': .05, 'cgst_rate': 9, 'sgst_rate': 9}],
    })
    notes = [purchases.create_debit_note(db, owner.id, original.id,
              [{'product_id': product.id, 'quantity': 1}]) for _ in range(3)]
    for field in ('subtotal', 'cgst_total', 'sgst_total', 'cess_total', 'discount_total', 'round_off', 'total_amount'):
        assert round(sum(getattr(note, field) for note in notes), 2) == getattr(original, field), field
    with pytest.raises(ValueError, match='original purchase'):
        purchases.create_debit_note(db, owner.id, notes[0].id, [{'product_id': product.id, 'quantity': 1}])


def test_duplicate_purchase_return_rows_are_rejected(shop):
    db, owner, product = shop
    original = purchases.accept_supplier_invoice(db, owner.id, {
        'supplier_name': 'Fixture supplier', 'invoice_number': 'PUR-' + uuid.uuid4().hex,
        'invoice_date': '2026-10-29', 'status': 'confirmed',
        'items': [{'product_id': product.id, 'product_name': product.name, 'quantity': 3, 'unit_price': 10}],
    })
    with pytest.raises(ValueError, match='duplicate'):
        purchases.create_debit_note(db, owner.id, original.id,
            [{'product_id': product.id, 'quantity': 2}, {'product_id': product.id, 'quantity': 2}])
    db.rollback()
    assert db.query(PurchaseInvoice).filter_by(parent_invoice_id=original.id).count() == 0


def test_journal_rejects_nonfinite_even_when_called_without_http_validation(shop):
    db, owner, _ = shop
    with pytest.raises(ValueError, match='finite'):
        posting.post_entry(db, business_id=owner.id, entry_date='2026-10-29', source_type='fixture',
                           source_id=1, ref_no='FIXTURE', narration='Fixture',
                           lines=[('Cash', float('nan'), 0), ('Sales', 0, float('nan'))])


def test_shift_amounts_reject_nonfinite_before_writing(shop):
    db, owner, _ = shop
    with pytest.raises(ValueError, match='finite'):
        shifts.open_shift(db, business_id=owner.id, user_id=owner.id, opening_cash=float('nan'))
    shifts.open_shift(db, business_id=owner.id, user_id=owner.id, opening_cash=0)
    with pytest.raises(ValueError, match='finite'):
        shifts.close_shift(db, business_id=owner.id, user_id=owner.id,
                           closing_cash_actual=0, closing_upi_actual=float('inf'))


def test_supplier_payment_type_cannot_be_posted_as_customer_receipt(auth_owner):
    response = client.post('/payments', headers=auth_owner['headers'],
                           json={'type': 'made', 'invoice_id': 999999, 'amount': 10})
    assert response.status_code == 422, response.text
    assert 'customer receipts only' in response.json()['detail']


@pytest.mark.parametrize('path,payload', [
    ('/payments', {'invoice_id': 999999, 'amount': 'NaN'}),
    ('/expenses', {'expense_date': '2026-10-29', 'category': 'Rent',
                   'expense_type': 'Indirect', 'payment_mode': 'Cash', 'amount': 'Infinity'}),
    ('/shifts/open', {'opening_cash': 'NaN'}),
])
def test_http_money_inputs_reject_nonfinite_values(auth_owner, path, payload):
    response = client.post(path, headers=auth_owner['headers'], json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('literal', ['1e309', 'Infinity', 'NaN'])
def test_http_nonfinite_numeric_literals_are_safe_422_without_echo(auth_owner, literal):
    response = client.post('/payments', headers={**auth_owner['headers'], 'Content-Type': 'application/json'},
                           content='{"invoice_id":999999,"amount":' + literal + '}')
    assert response.status_code == 422, response.text
    detail = response.json()['detail']
    assert isinstance(detail, list)
    assert all('input' not in error and 'ctx' not in error for error in detail)


def test_fully_returned_unpaid_sale_has_no_collectible_balance(shop):
    from core.billing.balances import invoice_balance, party_balance
    from core.api.payments import invoice_account
    from core.api.sales import _invoice_out_for_frontend
    db, owner, _ = shop
    customer = Customer(business_id=owner.id, name='Return balance fixture')
    db.add(customer)
    db.commit()
    original = sale(shop, qty=1, customer_id=customer.id)
    credit(shop, original, 1)
    balance = invoice_balance(db, original)
    assert balance['outstanding'] == 0
    assert party_balance(db, owner.id, customer.id)['outstanding'] == 0
    assert _invoice_out_for_frontend(original, balance)['can_record_payment'] is False
    account = invoice_account(original.id, current_user={'id': owner.id}, db=db)
    assert account['outstanding'] == 0
    assert account['credited_amount'] == original.total_amount
    with pytest.raises(ValueError, match='exceeds'):
        billing.record_payment(db, business_id=owner.id, invoice_id=original.id, amount_paid=.01)
    with pytest.raises(ValueError, match='no outstanding'):
        billing.settle_customer_dues(db, business_id=owner.id, customer_id=customer.id, amount=10)
    assert customer.credit_balance == 0


def test_partial_return_and_receipt_share_the_same_remaining_balance(shop):
    from core.billing.balances import invoice_balance, party_balance
    db, owner, _ = shop
    customer = Customer(business_id=owner.id, name='Partial balance fixture')
    db.add(customer)
    db.commit()
    original = sale(shop, qty=2, price=50, customer_id=customer.id)
    credit(shop, original, 1)
    billing.record_payment(db, business_id=owner.id, invoice_id=original.id, amount_paid=20)
    assert invoice_balance(db, original)['outstanding'] == 30
    assert party_balance(db, owner.id, customer.id)['outstanding'] == 30
    result = billing.settle_customer_dues(db, business_id=owner.id, customer_id=customer.id,
                                         amount=30, idempotency_key='fixture-' + uuid.uuid4().hex)
    assert result['total_applied'] == 30
    assert result['advance'] == 0
    assert invoice_balance(db, original)['outstanding'] == 0
    assert original.paid_amount == 50


def test_paid_customer_return_exposes_credit_without_fabricating_refund(shop):
    from core.billing.balances import invoice_balance, party_balance
    db, owner, _ = shop
    customer = Customer(business_id=owner.id, name='Paid return fixture')
    db.add(customer)
    db.commit()
    original = sale(shop, qty=1, price=100, customer_id=customer.id, paid_amount=100)
    from core.models import InvoicePayment
    receipts_before = db.query(InvoicePayment).filter_by(invoice_id=original.id).count()
    credit(shop, original, 1)
    balance = invoice_balance(db, original)
    assert balance['outstanding'] == 0 and balance['credit_due'] == 100
    assert party_balance(db, owner.id, customer.id)['credit_due'] == 100
    assert db.query(InvoicePayment).filter_by(invoice_id=original.id).count() == receipts_before
    assert customer.credit_balance == 0


def test_legacy_zero_total_uses_amount_but_genuine_free_sale_keeps_paid_status(shop):
    from core.billing.balances import invoice_balance
    from core.api.sales import _invoice_out_for_frontend
    db, owner, _ = shop
    legacy = Invoice(business_id=owner.id, invoice_id='LEGACY-' + uuid.uuid4().hex,
                     total_amount=0, amount=50, paid_amount=0, invoice_type='B2C')
    db.add(legacy)
    db.commit()
    assert invoice_balance(db, legacy)['outstanding'] == 50
    free = sale(shop, qty=1, price=0)
    assert _invoice_out_for_frontend(free, invoice_balance(db, free))['status'] == 'Paid'


def test_purchase_debit_note_reduces_vendor_dues_and_paid_return_is_credit(shop):
    from core.billing.balances import invoice_balance, party_balance
    db, owner, product = shop
    original = purchases.accept_supplier_invoice(db, owner.id, {
        'supplier_name': 'Balance supplier', 'invoice_number': 'PUR-' + uuid.uuid4().hex,
        'invoice_date': '2026-10-29', 'status': 'confirmed',
        'items': [{'product_id': product.id, 'product_name': product.name, 'quantity': 2, 'unit_price': 50}],
    })
    purchases.create_debit_note(db, owner.id, original.id, [{'product_id': product.id, 'quantity': 1}])
    assert invoice_balance(db, original, purchase=True)['outstanding'] == 50
    assert party_balance(db, owner.id, original.supplier_id, purchase=True)['outstanding'] == 50
    original.status = 'Paid'
    db.commit()
    balance = invoice_balance(db, original, purchase=True)
    assert balance['outstanding'] == 0 and balance['credit_due'] == 50
