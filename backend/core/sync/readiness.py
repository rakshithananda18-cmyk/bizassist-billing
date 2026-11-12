"""Keep partially restored local books readable, but never writable."""
import json

from fastapi import HTTPException

FINANCIAL_TABLES = frozenset({
    "invoices", "invoice_line_items", "invoice_payments", "payments",
    "inventory", "stock_ledger", "purchase_invoices", "purchase_invoice_line_items",
    "purchase_orders", "purchase_order_line_items", "expenses", "stock_transfers",
    "stock_transfer_line_items", "supplier_payments", "customer_refunds",
    "customer_credit_allocations", "register_shifts", "shift_cash_movements", "period_locks",
})
RESTORE_MESSAGE = (
    "Cloud restoration is not complete on this device. Keep it online until restoration "
    "finishes before creating or changing financial records."
)


def assert_financial_ready(db, business_id):
    if db.get_bind().dialect.name != "sqlite":
        return
    from database.models import User
    with db.no_autoflush:
        raw = db.query(User.settings).filter(User.id == business_id).scalar()
    try:
        settings = json.loads(raw or "{}")
        general = settings.get("general") or {}
        pending = general.get("sync_bootstrap_pending") is True
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(409, "Business settings are unreadable. Restore or repair them before changing financial records.") from None
    if pending:
        raise HTTPException(409, RESTORE_MESSAGE, headers={"X-Sync-State": "restoring"})


def install_readiness_guard():
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from database.db import sync_disabled_var

    if getattr(Session, "_stater_restore_guard", False):
        return

    @event.listens_for(Session, "before_flush")
    def protect_financial_flush(session, _context, _instances):
        if sync_disabled_var.get() or session.get_bind().dialect.name != "sqlite":
            return
        from database.models import _get_business_id
        businesses = set()
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            if getattr(obj, "__tablename__", None) in FINANCIAL_TABLES:
                business_id = _get_business_id(obj, session.connection())
                if business_id is not None:
                    businesses.add(business_id)
        for business_id in businesses:
            assert_financial_ready(session, business_id)

    Session._stater_restore_guard = True
