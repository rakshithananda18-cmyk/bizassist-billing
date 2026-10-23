"""
core/field_team.py — money that Field Team staff collected, confirmed into the books.

Field Team (`backend-task/`, its own service) shares the cloud database. Its
staff complete `payment_collect` tasks with the amount, the mode (Cash / UPI /
Cheque / NEFT / Card) and a reference. Nothing reaches billing's books until the
owner confirms it here; then each bill gets a payment through billing's own
`commands.record_payment` — journal, paid status, sync — keyed
`ft-collect:<task uid>:<invoice id>`, so a double click or a second owner
confirming the same collection never records it twice.

Read-only over Field Team's tables, declared on their OWN metadata (not
`database.db.Base`): billing never creates, migrates or writes them, and its
Alembic autogenerate already skips `ft_*` (alembic/env.py). The tables exist
only in the cloud database, so on the desktop app this feature is simply
unavailable. Column subsets are checked against Field Team's models in its CI
(backend-task/tests/test_billing_contract.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, func, inspect
from sqlalchemy.orm import Session, declarative_base

from core.billing import commands as billing
from database.models import Invoice, InvoicePayment
from services.dates import _IST_OFFSET

FieldTeamBase = declarative_base(metadata=MetaData())

# Must equal Field Team's app/collections.KEY_PREFIX.
KEY_PREFIX = "ft-collect:"
CREDIT_NOTE = "credit_note"
_CENT = 0.005


class FtShop(FieldTeamBase):
    __tablename__ = "ft_shops"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=True)  # billing customers.id


class FtStaff(FieldTeamBase):
    __tablename__ = "ft_staff"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)


class FtTask(FieldTeamBase):
    __tablename__ = "ft_tasks"
    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False)
    business_id = Column(Integer, nullable=False)
    task_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    staff_id = Column(Integer, nullable=True)
    shop_id = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    amount_collected = Column(Float, nullable=True)
    payment_mode = Column(String, nullable=True)
    payment_ref = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=True)  # naive UTC


class FtTaskInvoice(FieldTeamBase):
    __tablename__ = "ft_task_invoices"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    task_id = Column(Integer, nullable=False)
    invoice_id = Column(Integer, nullable=False)  # billing invoices.id


def _r2(x) -> float:
    return round(float(x or 0.0), 2)


def available(db: Session) -> bool:
    """Field Team's tables are in this database (the cloud), not on the desktop."""
    insp = inspect(db.get_bind())
    return all(insp.has_table(t) for t in ("ft_tasks", "ft_shops", "ft_staff", "ft_task_invoices"))


def collection_key(task_uid: str, invoice_id: int) -> str:
    return f"{KEY_PREFIX}{task_uid}:{invoice_id}"


def _balance(inv: Invoice) -> float:
    # Billing's own outstanding rule (commands.py, parties.py).
    return max(_r2((inv.total_amount or inv.amount or 0.0) - (inv.paid_amount or 0.0)), 0.0)


def _collected_on(task: FtTask) -> Optional[str]:
    if task.completed_at is None:
        return None
    return (task.completed_at.replace(tzinfo=timezone.utc).astimezone(timezone(_IST_OFFSET))).date().isoformat()


def _recorded(db: Session, business_id: int, task_uids: List[str]) -> Dict[str, Dict[int, float]]:
    """task uid → {invoice id: amount already recorded in billing for it}."""
    out: Dict[str, Dict[int, float]] = {}
    if not task_uids:
        return out
    uid_of_key = func.substr(InvoicePayment.idempotency_key, len(KEY_PREFIX) + 1, 36)
    rows = (db.query(uid_of_key, InvoicePayment.invoice_id, InvoicePayment.amount_paid)
            .filter(InvoicePayment.business_id == business_id,
                    InvoicePayment.idempotency_key.like(f"{KEY_PREFIX}%"),
                    uid_of_key.in_(task_uids)).all())
    for uid, inv_id, amt in rows:
        out.setdefault(uid, {})
        out[uid][inv_id] = _r2(out[uid].get(inv_id, 0.0) + (amt or 0.0))
    return out


def _candidates(db: Session, business_id: int, task: FtTask, shop: Optional[FtShop],
                used: Dict[int, float]) -> List[Invoice]:
    """The bills a collection can pay, oldest first: the task's own bills, or —
    for a collection planned without bills — the shop's customer's unpaid bills.
    A bill this collection already paid is not offered again."""
    linked = [i for (i,) in db.query(FtTaskInvoice.invoice_id).filter(
        FtTaskInvoice.business_id == business_id, FtTaskInvoice.task_id == task.id).all()]
    q = db.query(Invoice).filter(Invoice.business_id == business_id,
                                 func.coalesce(Invoice.invoice_type, "") != CREDIT_NOTE)
    if linked:
        q = q.filter(Invoice.id.in_(linked))
    elif shop is not None and shop.customer_id is not None:
        q = q.filter(Invoice.customer_id == shop.customer_id)
    else:
        return []
    rows = q.order_by(Invoice.invoice_date.is_(None), Invoice.invoice_date.asc(), Invoice.id.asc()).all()
    return [inv for inv in rows if inv.id not in used and _balance(inv) > _CENT]


def suggest(amount: float, invoices: List[Invoice]) -> List[dict]:
    """Oldest bill first, each up to what is due on it."""
    left = _r2(amount)
    out = []
    for inv in invoices:
        take = _r2(min(left, _balance(inv)))
        out.append({"invoice_id": inv.id, "amount": take})
        left = _r2(left - take)
    return out


def pending_collections(db: Session, business_id: int) -> List[dict]:
    """Done collections with money not yet confirmed into the books, oldest first."""
    tasks = (db.query(FtTask)
             .filter(FtTask.business_id == business_id, FtTask.task_type == "payment_collect",
                     FtTask.status == "done", FtTask.amount_collected > _CENT)
             .order_by(FtTask.completed_at.asc(), FtTask.id.asc()).limit(300).all())
    recorded = _recorded(db, business_id, [t.uid for t in tasks])
    shops = {s.id: s for s in db.query(FtShop).filter(
        FtShop.business_id == business_id, FtShop.id.in_({t.shop_id for t in tasks if t.shop_id})).all()}
    staff = {s.id: s.name for s in db.query(FtStaff).filter(
        FtStaff.business_id == business_id, FtStaff.id.in_({t.staff_id for t in tasks if t.staff_id})).all()}
    out = []
    for t in tasks:
        used = recorded.get(t.uid, {})
        remaining = _r2(t.amount_collected - sum(used.values()))
        if remaining <= _CENT:
            continue
        shop = shops.get(t.shop_id)
        bills = _candidates(db, business_id, t, shop, used)
        plan = suggest(remaining, bills)
        out.append({
            "task_uid": t.uid,
            "task_id": t.id,
            "title": t.title,
            "shop": shop.name if shop else None,
            "shop_linked": bool(shop and shop.customer_id),
            "staff": staff.get(t.staff_id),
            "collected_on": _collected_on(t),
            "amount_collected": _r2(t.amount_collected),
            "already_confirmed": _r2(sum(used.values())),
            "remaining": remaining,
            "payment_mode": t.payment_mode or "Cash",
            "payment_ref": t.payment_ref,
            "bills": [{"invoice_id": inv.id, "number": inv.invoice_id or f"#{inv.id}", "date": inv.invoice_date,
                       "customer": inv.customer, "balance_due": _balance(inv)} for inv in bills],
            "suggested": plan,
            "unallocated": _r2(remaining - sum(p["amount"] for p in plan)),
        })
    return out


def confirm_collection(db: Session, business_id: int, task_uid: str, allocations: List[dict]) -> dict:
    """Record the owner-approved split as billing payments. Raises ValueError
    with a message for the owner when the split does not fit."""
    task = (db.query(FtTask).filter(FtTask.business_id == business_id, FtTask.uid == task_uid).first())
    if task is None or task.task_type != "payment_collect" or task.status != "done" \
            or (task.amount_collected or 0) <= _CENT:
        raise LookupError("Collection not found")
    used = _recorded(db, business_id, [task.uid]).get(task.uid, {})
    remaining = _r2(task.amount_collected - sum(used.values()))
    if remaining <= _CENT:
        raise ValueError("This collection is already recorded in billing")
    shop = db.query(FtShop).filter(FtShop.business_id == business_id, FtShop.id == task.shop_id).first() \
        if task.shop_id else None
    bills = {inv.id: inv for inv in _candidates(db, business_id, task, shop, used)}

    wanted = [(int(a["invoice_id"]), _r2(a["amount"])) for a in allocations if _r2(a["amount"]) > 0]
    if not wanted:
        raise ValueError("Enter an amount for at least one bill")
    if len({i for i, _ in wanted}) != len(wanted):
        raise ValueError("A bill appears twice")
    for inv_id, amt in wanted:
        inv = bills.get(inv_id)
        if inv is None:
            raise ValueError(f"Bill {inv_id} cannot take this collection")
        if amt > _balance(inv) + _CENT:
            raise ValueError(f"{inv.invoice_id or inv_id}: only ₹{_balance(inv):,.2f} is due")
    if sum(a for _, a in wanted) > remaining + _CENT:
        raise ValueError(f"Only ₹{remaining:,.2f} of this collection is left to confirm")

    staff = db.query(FtStaff.name).filter(FtStaff.business_id == business_id, FtStaff.id == task.staff_id).scalar() \
        if task.staff_id else None
    note = " · ".join(x for x in (
        f"Field Team collection by {staff or 'staff'}", shop.name if shop else None,
        f"ref {task.payment_ref}" if task.payment_ref else None) if x)
    recorded = []
    for inv_id, amt in wanted:
        # Commits per bill; the key makes a retry after a partial failure safe.
        p = billing.record_payment(
            db, business_id=business_id, invoice_id=inv_id, amount_paid=amt,
            payment_mode=task.payment_mode or "Cash", payment_date=_collected_on(task),
            note=note, idempotency_key=collection_key(task.uid, inv_id),
        )
        recorded.append({"invoice_id": inv_id, "payment_id": p.id, "amount": _r2(p.amount_paid)})
    done = _r2(sum(used.values()) + sum(r["amount"] for r in recorded))
    return {"task_uid": task.uid, "recorded": recorded, "confirmed_total": done,
            "remaining": _r2(task.amount_collected - done)}
