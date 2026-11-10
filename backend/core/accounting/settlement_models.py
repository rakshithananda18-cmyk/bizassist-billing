"""Append-only, tenant-owned settlement facts. Corrections require reversing facts.

These tables deliberately contain no mutable status: source balances are derived
from receipts, return documents, refunds and allocations in one read contract.
"""
from sqlalchemy import Column, Integer, Float, String, Text, ForeignKey, UniqueConstraint, CheckConstraint, event, inspect
from database.db import Base, BusinessOwnedMixin


class SupplierPayment(Base, BusinessOwnedMixin):
    __tablename__ = "supplier_payments"
    purchase_invoice_id = Column(Integer, ForeignKey("purchase_invoices.id"), nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=False)
    payment_date = Column(String, nullable=False)
    operator_id = Column(Integer, nullable=False)
    operator_name = Column(String, nullable=False, default="Unknown operator")
    shift_id = Column(Integer, ForeignKey("register_shifts.id"), nullable=True, index=True)
    idempotency_key = Column(String(160), nullable=False)
    note = Column(Text)
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_supplier_payment_key"),
        UniqueConstraint("business_id", "uid", name="uq_supplier_payment_uid"),
        CheckConstraint("amount > 0 AND amount < 1e15", name="supplier_payment_positive"),
        CheckConstraint("business_id IS NOT NULL AND uid IS NOT NULL", name="supplier_payment_identity"),
    )


class CustomerRefund(Base, BusinessOwnedMixin):
    __tablename__ = "customer_refunds"
    credit_note_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    source_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=False)
    payment_date = Column(String, nullable=False)
    operator_id = Column(Integer, nullable=False)
    operator_name = Column(String, nullable=False, default="Unknown operator")
    shift_id = Column(Integer, ForeignKey("register_shifts.id"), nullable=True, index=True)
    idempotency_key = Column(String(160), nullable=False)
    note = Column(Text)
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_customer_refund_key"),
        UniqueConstraint("business_id", "uid", name="uq_customer_refund_uid"),
        CheckConstraint("amount > 0 AND amount < 1e15", name="customer_refund_positive"),
        CheckConstraint("business_id IS NOT NULL AND uid IS NOT NULL", name="customer_refund_identity"),
    )


class CustomerCreditAllocation(Base, BusinessOwnedMixin):
    __tablename__ = "customer_credit_allocations"
    credit_note_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    source_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    target_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    payment_date = Column(String, nullable=False)
    operator_id = Column(Integer, nullable=False)
    operator_name = Column(String, nullable=False, default="Unknown operator")
    idempotency_key = Column(String(160), nullable=False)
    note = Column(Text)
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_customer_allocation_key"),
        UniqueConstraint("business_id", "uid", name="uq_customer_allocation_uid"),
        CheckConstraint("amount > 0 AND amount < 1e15", name="customer_allocation_positive"),
        CheckConstraint("business_id IS NOT NULL AND uid IS NOT NULL", name="customer_allocation_identity"),
        CheckConstraint("source_invoice_id <> target_invoice_id", name="customer_allocation_distinct"),
    )


def _refuse_financial_edit(_mapper, _connection, target):
    state = inspect(target)
    for column in target.__table__.columns:
        if column.name not in {"updated_at", "operator_id"} and state.attrs[column.name].history.has_changes():
            raise ValueError("Posted settlements are append-only; create a separately linked reversing fact")


for _model in (SupplierPayment, CustomerRefund, CustomerCreditAllocation):
    event.listen(_model, "before_update", _refuse_financial_edit)
