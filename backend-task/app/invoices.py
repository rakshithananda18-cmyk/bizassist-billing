"""
app/invoices.py — a shop's billing invoices, for deliveries and collections.

Read-only over billing's `invoices` / `invoice_line_items` (app/billing_models):
a shop sees the bills of the billing customer it is linked to
(`ft_shops.customer_id`). A task keeps the bills it covers in
`ft_task_invoices`, so one bill is not sent out — or collected — twice.

Amounts follow billing's own rules: total = `total_amount or amount`, amount
due = total − `paid_amount` (billing core/billing/commands.py), credit notes
(`invoice_type = "credit_note"`) are not bills to deliver.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.billing_models import BillingInvoice, BillingInvoiceLine
from app.collections import confirmed_in_billing
from app.models import FieldShop, FieldTask, FieldTaskInvoice
from app.timeutil import biz_today

CREDIT_NOTE = "credit_note"
MAX_PER_TASK = 50
# Units billed as whole packs: their quantity is the number of boxes to carry.
BOX_UNITS = frozenset({"box", "boxes", "bx", "ctn", "ctns", "carton", "cartons", "case", "cases"})
_TYPE_LABEL = {"delivery": "delivery", "payment_collect": "collection"}


def _r2(x) -> float:
    return round(float(x or 0.0), 2)


def invoice_total(inv: BillingInvoice) -> float:
    return _r2(inv.total_amount or inv.amount or 0.0)


def balance_due(inv: BillingInvoice) -> float:
    return max(_r2(invoice_total(inv) - (inv.paid_amount or 0.0)), 0.0)


def _net_qty(line: BillingInvoiceLine) -> float:
    return max((line.quantity or 0.0) - (line.returned_qty or 0.0), 0.0)


def box_count(lines: Iterable[BillingInvoiceLine]) -> Optional[int]:
    """Boxes on a bill: the quantity on box/carton/case lines. None when the bill
    has no such line — then the owner types the boxes."""
    boxed = [ln for ln in lines if (ln.unit or "").strip().lower() in BOX_UNITS]
    return int(round(sum(_net_qty(ln) for ln in boxed))) if boxed else None


def _lines_by_invoice(db: Session, ids: List[int]) -> dict:
    out = {i: [] for i in ids}
    if ids:
        rows = (db.query(BillingInvoiceLine)
                .filter(BillingInvoiceLine.invoice_id.in_(ids))
                .order_by(BillingInvoiceLine.id.asc()).all())
        for ln in rows:
            out[ln.invoice_id].append(ln)
    return out


def _live_tasks(db: Session, business_id: int, ids: List[int]) -> dict:
    """invoice id → the pending or done tasks that already carry it."""
    out: dict = {}
    if not ids:
        return out
    rows = (db.query(FieldTaskInvoice.invoice_id, FieldTask.id, FieldTask.task_type, FieldTask.status,
                     FieldTask.uid, FieldTask.amount_collected)
            .join(FieldTask, FieldTask.id == FieldTaskInvoice.task_id)
            .filter(FieldTaskInvoice.business_id == business_id,
                    FieldTaskInvoice.invoice_id.in_(ids),
                    FieldTask.status != "cancelled")
            .order_by(FieldTask.id.asc()).all())
    confirmed = confirmed_in_billing(db, business_id,
                                    (uid for _, _, kind, status, uid, _ in rows
                                     if kind == "payment_collect" and status == "done"))
    for inv_id, task_id, task_type, status, uid, collected in rows:
        # A completed partial collection must not reserve the invoice forever.
        # Wait until its reported cash is fully accounted for in Billing before
        # scheduling another collection, so unconfirmed cash is not collected twice.
        if task_type == "payment_collect" and status == "done" and (
                float(collected or 0) - confirmed.get(uid, 0) <= 0.005):
            continue
        out.setdefault(inv_id, []).append({"task_id": task_id, "task_type": task_type, "status": status})
    return out


def _number(inv: BillingInvoice) -> str:
    return inv.invoice_id or f"#{inv.id}"


def shop_invoices(db: Session, business_id: int, shop: FieldShop, days: int) -> list:
    """The linked customer's bills from the last `days` days, plus any older
    bill still unpaid (it may still need collecting). Newest first."""
    if shop.customer_id is None:
        return []
    since = (date.fromisoformat(biz_today()) - timedelta(days=days)).isoformat()
    # SQL twin of invoice_total(): a 0 total_amount falls back to the legacy amount.
    total = func.coalesce(func.nullif(BillingInvoice.total_amount, 0), BillingInvoice.amount, 0.0)
    rows = (db.query(BillingInvoice)
            .filter(BillingInvoice.business_id == business_id,
                    BillingInvoice.customer_id == shop.customer_id,
                    func.coalesce(BillingInvoice.invoice_type, "") != CREDIT_NOTE,
                    or_(BillingInvoice.invoice_date >= since,
                        total - func.coalesce(BillingInvoice.paid_amount, 0.0) > 0.005))
            .order_by(BillingInvoice.invoice_date.is_(None), BillingInvoice.invoice_date.desc(),
                      BillingInvoice.id.desc())
            .limit(100).all())
    ids = [r.id for r in rows]
    lines = _lines_by_invoice(db, ids)
    tasks = _live_tasks(db, business_id, ids)
    return [{
        "id": inv.id,
        "number": _number(inv),
        "date": inv.invoice_date,
        "status": inv.status,
        "total": invoice_total(inv),
        "paid": _r2(inv.paid_amount),
        "balance_due": balance_due(inv),
        "boxes": box_count(lines[inv.id]),
        "lines": [{"product_name": ln.product_name, "quantity": _net_qty(ln), "unit": ln.unit}
                  for ln in lines[inv.id]],
        "tasks": tasks.get(inv.id, []),
    } for inv in rows]


def resolve_invoices(db: Session, business_id: int, shop: Optional[FieldShop],
                     invoice_ids: List[int]) -> List[BillingInvoice]:
    """The picked bills, checked: this business's, billed to the shop's linked
    customer, not credit notes. Order kept, repeats dropped."""
    ids = list(dict.fromkeys(invoice_ids or []))
    if not ids:
        return []
    if len(ids) > MAX_PER_TASK:
        raise HTTPException(status_code=422, detail=f"Pick at most {MAX_PER_TASK} invoices per task")
    if shop is None:
        raise HTTPException(status_code=422, detail="Choose the shop the invoices are for")
    if shop.customer_id is None:
        raise HTTPException(status_code=422,
                            detail=f"{shop.name} is not linked to a billing customer. Link it on the Shops page first.")
    found = {r.id: r for r in db.query(BillingInvoice).filter(
        BillingInvoice.business_id == business_id, BillingInvoice.id.in_(ids)).all()}
    missing = [i for i in ids if i not in found]
    if missing:
        # Includes ids that belong to another business — never reveal which.
        raise HTTPException(status_code=404, detail=f"Invoice(s) not found: {missing}")
    for inv in found.values():
        if inv.customer_id != shop.customer_id:
            raise HTTPException(status_code=422, detail=f"{_number(inv)} is billed to a different customer than {shop.name}")
        if (inv.invoice_type or "") == CREDIT_NOTE:
            raise HTTPException(status_code=422, detail=f"{_number(inv)} is a credit note, not a bill")
        if (inv.status or "").lower() in {"cancelled", "canceled", "void", "draft"}:
            raise HTTPException(status_code=422, detail=f"{_number(inv)} is not an active bill")
    return [found[i] for i in ids]


def ensure_not_planned(db: Session, business_id: int, task_type: str, invoices: List[BillingInvoice]) -> None:
    """One live task of a kind per bill: a bill is delivered once, collected once."""
    live = _live_tasks(db, business_id, [i.id for i in invoices])
    for inv in invoices:
        clash = next((t for t in live.get(inv.id, []) if t["task_type"] == task_type), None)
        if clash:
            label = _TYPE_LABEL.get(task_type, task_type.replace("_", " "))
            raise HTTPException(
                status_code=409,
                detail=f"{_number(inv)} is already on {label} task #{clash['task_id']} ({clash['status']}). "
                       "Cancel that task to plan it again.",
            )


def attach_invoices(db: Session, task: FieldTask, invoices: List[BillingInvoice]) -> None:
    """Link the bills to the task and fill what the owner left blank: the
    invoice numbers, and boxes and orders for a delivery or the amount due for
    a collection. Values the owner typed are kept."""
    if not invoices:
        return
    lines = _lines_by_invoice(db, [i.id for i in invoices])
    if task.reference is None:
        ref = ", ".join(_number(i) for i in invoices)
        task.reference = ref if len(ref) <= 200 else ref[:199] + "…"
    if task.task_type == "delivery":
        if task.boxes_planned is None:
            counts = [b for b in (box_count(lines[i.id]) for i in invoices) if b is not None]
            task.boxes_planned = sum(counts) if counts else None
        if task.orders_count is None:
            task.orders_count = len(invoices)
    if task.task_type == "payment_collect" and task.amount_expected is None:
        task.amount_expected = _r2(sum(balance_due(i) for i in invoices))
    for inv in invoices:
        task.invoices.append(FieldTaskInvoice(
            business_id=task.business_id, invoice_id=inv.id, invoice_number=_number(inv),
            invoice_date=inv.invoice_date, total=invoice_total(inv), balance_due=balance_due(inv),
        ))
