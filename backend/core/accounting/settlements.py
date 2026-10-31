"""Atomic append-only supplier settlement, customer refund and credit allocation.

All amounts come from deterministic source balances. Replays return the original
fact; reusing a key for a different source/amount fails. No command edits or
deletes a receipt, return or posted journal line.
"""
import logging
import math
import hashlib
from datetime import date
from sqlalchemy import func, text
from database.models import Invoice, PurchaseInvoice, User
from core.accounting.settlement_models import SupplierPayment, CustomerRefund, CustomerCreditAllocation
from core.accounting import posting
from core.billing.balances import invoice_balance, collection_status
from services.dates import biz_today_str

logger = logging.getLogger("bizassist.settlements")


def purge_settlement_state(db, business_id):
    """Private-business deletion only; caller owns authorization and transaction."""
    for model in (CustomerCreditAllocation, CustomerRefund, SupplierPayment):
        db.query(model).filter(model.business_id == business_id).delete(synchronize_session=False)


def _amount(value):
    amount = float(value)
    if not math.isfinite(amount) or amount <= 0 or amount >= 1e15:
        raise ValueError("Amount must be finite, positive and less than 1e15")
    amount = round(amount, 2)
    if amount <= 0:
        raise ValueError("Amount must be at least 0.01")
    return amount


def _date(value):
    value = value or biz_today_str()
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ValueError("Payment date must use YYYY-MM-DD") from None


def _prepare(db, model, bid, key, amount, binding):
    if not isinstance(key, str) or not key.strip() or len(key) > 160:
        raise ValueError("A stable idempotency_key of at most 160 characters is required")
    # Serialize only this request key, in the separate two-int advisory namespace.
    # Journal chain locking happens AFTER document locks, as in other commands;
    # taking its business-wide lock here would invert that order and deadlock a
    # concurrent ordinary receipt/return that already locked the same invoice.
    if db.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(f"{bid}|{model.__tablename__}|{key}".encode()).digest()[:4], signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:namespace,:key)"), {"namespace": 0x425A5354, "key": lock_key})
    prior = db.query(model).filter(model.business_id == bid, model.idempotency_key == key).first()
    if prior:
        if round(prior.amount, 2) != amount or any(getattr(prior, field) != value for field, value in binding.items()):
            raise ValueError("Idempotency key already belongs to a different settlement")
        return prior
    return None


def _shift(db, bid, operator, mode):
    from core.shifts import service
    mode = (mode or "Cash").strip()
    if mode.lower() not in {"cash", "upi", "card", "bank", "cheque"}:
        raise ValueError("Payment mode must be Cash, UPI, Card, Bank or Cheque")
    active = service.get_open_shift(db, business_id=bid, user_id=operator, lock=True)
    if mode.lower() in {"cash", "upi"} and active is None:
        raise ValueError("shift_required")
    return active.id if active else None


def _operator_name(db, bid, operator_id):
    user = db.query(User).filter(User.id == operator_id).first()
    if user is None or (user.parent_business_id or user.id) != bid:
        raise ValueError("Settlement operator does not belong to this business")
    return user.staff_login_name or user.username or "Owner"


def supplier_payment(db, *, business_id, operator_id, purchase_invoice_id, amount,
                     payment_mode="Cash", payment_date=None, note=None, idempotency_key):
    amount = _amount(amount)
    prior = _prepare(db, SupplierPayment, business_id, idempotency_key, amount,
                     {"purchase_invoice_id": purchase_invoice_id, "payment_mode": payment_mode,
                      **({"payment_date": _date(payment_date)} if payment_date else {})})
    if prior:
        return prior
    shift_id = _shift(db, business_id, operator_id, payment_mode)
    purchase = db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == business_id,
        PurchaseInvoice.id == purchase_invoice_id).with_for_update().first()
    if purchase is None or purchase.invoice_type == "debit_note":
        raise ValueError("A supplier payment must refer to this business's original purchase bill")
    if amount > invoice_balance(db, purchase, purchase=True)["outstanding"]:
        raise ValueError("Supplier payment exceeds the purchase bill's remaining balance after returns")
    row = SupplierPayment(business_id=business_id, purchase_invoice_id=purchase.id,
        vendor_id=purchase.supplier_id, amount=amount, payment_mode=payment_mode,
        payment_date=_date(payment_date), operator_id=operator_id, operator_name=_operator_name(db, business_id, operator_id), shift_id=shift_id,
        idempotency_key=idempotency_key, note=note)
    db.add(row)
    db.flush()
    posting.post_entry(db, business_id=business_id, entry_date=row.payment_date,
        source_type="supplier_payment", source_id=row.id, ref_no=f"SUP-PAY-{row.id}",
        narration=f"Supplier payment for {purchase.invoice_number}",
        lines=[(posting.ACC_AP, amount, 0), (posting.ACC_CASH, 0, amount)])
    # Purchase.status is the document review workflow (pending/confirmed), not
    # a receipt projection. Paid/partial is derived separately by the serializer.
    db.commit()
    logger.info("[SETTLEMENT] supplier payment biz=%s purchase=%s amount=%.2f uid=%s", business_id, purchase.id, amount, row.uid)
    return row


def credit_available(db, credit_note):
    """Available money credit, not the gross credit-note value of unpaid goods."""
    if credit_note.invoice_type != "credit_note" or not credit_note.parent_invoice_id:
        return 0.0
    original = db.query(Invoice).filter(Invoice.id == credit_note.parent_invoice_id,
        Invoice.business_id == credit_note.business_id).first()
    if original is None:
        return 0.0
    used = 0.0
    for model in (CustomerRefund, CustomerCreditAllocation):
        used += db.query(func.coalesce(func.sum(model.amount), 0)).filter(
            model.business_id == credit_note.business_id, model.credit_note_id == credit_note.id).scalar() or 0
    return round(max(min(float(credit_note.total_amount or 0) - used,
                         invoice_balance(db, original)["credit_due"]), 0), 2)


def _credit_source(db, bid, credit_note_id, target_invoice_id=None):
    credit_note = db.query(Invoice).filter(Invoice.business_id == bid, Invoice.id == credit_note_id).first()
    if credit_note is None or credit_note.invoice_type != "credit_note" or not credit_note.parent_invoice_id:
        raise ValueError("A refund/allocation requires a linked credit note owned by this business")
    identities = {credit_note.id, credit_note.parent_invoice_id}
    if target_invoice_id is not None:
        identities.add(target_invoice_id)
    locked = {row.id: row for row in db.query(Invoice).filter(Invoice.business_id == bid,
        Invoice.id.in_(identities)).order_by(Invoice.id).with_for_update().all()}
    credit_note = locked[credit_note.id]
    original = locked.get(credit_note.parent_invoice_id)
    if original is None or original.invoice_type == "credit_note":
        raise ValueError("The credit note has no valid original sale")
    return credit_note, original


def customer_refund(db, *, business_id, operator_id, credit_note_id, amount,
                    payment_mode="Cash", payment_date=None, note=None, idempotency_key):
    amount = _amount(amount)
    prior = _prepare(db, CustomerRefund, business_id, idempotency_key, amount,
                     {"credit_note_id": credit_note_id, "payment_mode": payment_mode,
                      **({"payment_date": _date(payment_date)} if payment_date else {})})
    if prior:
        return prior
    shift_id = _shift(db, business_id, operator_id, payment_mode)
    credit_note, original = _credit_source(db, business_id, credit_note_id)
    if amount > credit_available(db, credit_note):
        raise ValueError("Refund exceeds the available paid-return credit")
    row = CustomerRefund(business_id=business_id, credit_note_id=credit_note.id,
        source_invoice_id=original.id, customer_id=original.customer_id, amount=amount,
        payment_mode=payment_mode, payment_date=_date(payment_date), operator_id=operator_id, operator_name=_operator_name(db, business_id, operator_id),
        shift_id=shift_id, idempotency_key=idempotency_key, note=note)
    db.add(row)
    db.flush()
    posting.post_entry(db, business_id=business_id, entry_date=row.payment_date,
        source_type="customer_refund", source_id=row.id, ref_no=f"REF-{row.id}",
        narration=f"Customer refund against {credit_note.invoice_id}",
        lines=[(posting.ACC_AR, amount, 0), (posting.ACC_CASH, 0, amount)])
    db.commit()
    logger.info("[SETTLEMENT] customer refund biz=%s credit=%s amount=%.2f uid=%s", business_id, credit_note.id, amount, row.uid)
    return row


def allocate_credit(db, *, business_id, operator_id, credit_note_id, target_invoice_id,
                    amount, allocation_date=None, note=None, idempotency_key):
    amount = _amount(amount)
    prior = _prepare(db, CustomerCreditAllocation, business_id, idempotency_key, amount,
                     {"credit_note_id": credit_note_id, "target_invoice_id": target_invoice_id,
                      **({"payment_date": _date(allocation_date)} if allocation_date else {})})
    if prior:
        return prior
    credit_note, original = _credit_source(db, business_id, credit_note_id, target_invoice_id)
    target = db.query(Invoice).filter(Invoice.business_id == business_id,
        Invoice.id == target_invoice_id).with_for_update().first()
    if (target is None or target.id == original.id or target.invoice_type == "credit_note"
            or not original.customer_id or target.customer_id != original.customer_id):
        raise ValueError("Credit can only be allocated to a different sale for the same named customer")
    if amount > credit_available(db, credit_note) or amount > invoice_balance(db, target)["outstanding"]:
        raise ValueError("Allocation exceeds the available return credit or target outstanding")
    row = CustomerCreditAllocation(business_id=business_id, credit_note_id=credit_note.id,
        source_invoice_id=original.id, target_invoice_id=target.id, customer_id=original.customer_id,
        amount=amount, payment_date=_date(allocation_date), operator_id=operator_id, operator_name=_operator_name(db, business_id, operator_id),
        idempotency_key=idempotency_key, note=note)
    db.add(row)
    db.flush()
    posting.post_entry(db, business_id=business_id, entry_date=row.payment_date,
        source_type="customer_credit_allocation", source_id=row.id, ref_no=f"ALLOC-{row.id}",
        narration=f"Return credit {credit_note.invoice_id} allocated to {target.invoice_id}",
        lines=[(posting.ACC_AR, amount, 0), (posting.ACC_AR, 0, amount)])
    target.status = collection_status(invoice_balance(db, target))
    db.commit()
    logger.info("[SETTLEMENT] credit allocation biz=%s credit=%s target=%s amount=%.2f uid=%s", business_id, credit_note.id, target.id, amount, row.uid)
    return row
