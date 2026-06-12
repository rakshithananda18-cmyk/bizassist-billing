"""
actions.py — Tier 3 of the agentic engine (gated, side-effecting actions).

Every action follows the same safe lifecycle:

    preview(action, user_id, params)  -> what WOULD happen (no side effects)
    execute(action, user_id, params)  -> do it, and write an audit row per item

The frontend always shows the preview in a confirm modal first; nothing runs
until the user confirms. Add a new action by adding one entry to ACTIONS.

Current actions:
    send_payment_reminders — generates a polite reminder draft per overdue
                             customer (0 AI tokens) and logs them. Nothing is
                             emailed (customers have no stored contact info);
                             the drafts are copy-ready for manual sending.
"""
import json
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, User, ActionLog, Customer
from services.notifier import send_email, is_configured as email_configured

logger = logging.getLogger("bizassist.actions")


# ── Helpers ─────────────────────────────────────────────────────────
def _business_name(db, user_id: int) -> str:
    u = db.query(User).filter(User.id == user_id).first()
    return (u.business_name if u and u.business_name else "our team")


def _customer_email(db, user_id: int, customer_name: str) -> Optional[str]:
    """A stored email for this customer, if any (Customer table, by name)."""
    if not customer_name:
        return None
    c = (db.query(Customer)
         .filter(Customer.business_id == user_id,
                 func.lower(Customer.name) == customer_name.strip().lower())
         .first())
    return (c.email or None) if c else None


def _already_reminded_today(db, user_id: int, customer_name: str) -> bool:
    """Idempotency: was this customer already emailed a reminder today?"""
    start = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    return db.query(ActionLog).filter(
        ActionLog.business_id == user_id,
        ActionLog.action == "send_payment_reminders",
        ActionLog.target == customer_name,
        ActionLog.status == "sent",
        ActionLog.created_at >= start,
    ).first() is not None


def _reminder_message(customer: str, amount: float, business: str, due: Optional[str]) -> str:
    due_part = f" (due {due})" if due else ""
    return (
        f"Hi {customer},\n\n"
        f"This is a friendly reminder that you have an outstanding balance of "
        f"₹{amount:,.0f}{due_part}. We'd be grateful if you could arrange payment "
        f"at your earliest convenience.\n\n"
        f"If you've already paid, please ignore this message.\n\n"
        f"Thank you,\n{business}"
    )


# ── send_payment_reminders ──────────────────────────────────────────
def _reminders_preview(user_id: int, params: dict) -> dict:
    # Honour an explicit customer selection from the Send-reminders picker; when
    # none is given, fall back to every overdue customer.
    selected = [c for c in (params or {}).get("customers", []) if c]
    db = SessionLocal()
    try:
        business = _business_name(db, user_id)
        q = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("total"),
                func.max(Invoice.due_date).label("due"),
                func.count(Invoice.id).label("invoices"),
            )
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
        )
        if selected:
            q = q.filter(Invoice.customer.in_(selected))
        rows = q.group_by(Invoice.customer).order_by(func.sum(Invoice.amount).desc()).all()

        smtp_ok = email_configured()
        items = []
        for r in rows:
            email = _customer_email(db, user_id, r.customer)
            if email and smtp_ok:
                channel = "email"          # will actually send
            elif email and not smtp_ok:
                channel = "email_unconfigured"
            else:
                channel = "no_contact"     # no stored email → copy-only
            items.append({
                "customer": r.customer,
                "amount": float(r.total or 0),
                "invoices": int(r.invoices or 0),
                "due": r.due,
                "email": email,
                "channel": channel,
                "message": _reminder_message(r.customer, r.total or 0, business, r.due),
            })

        total = sum(i["amount"] for i in items)
        sendable = sum(1 for i in items if i["channel"] == "email")
        if not items:
            summary = "No overdue customers — nothing to remind."
            warning = ""
        elif not smtp_ok:
            summary = f"{len(items)} overdue customer(s) — ₹{total:,.0f} total"
            warning = ("Email isn't configured (set EMAIL_USER / EMAIL_PASS in .env). "
                       "Reminders will be drafted and logged, not sent.")
        else:
            summary = (f"{len(items)} overdue customer(s) — ₹{total:,.0f} total. "
                       f"{sendable} will be emailed; {len(items) - sendable} have no email on file (copy-only).")
            warning = "" if sendable == len(items) else \
                "Customers without a stored email won't be emailed — add their email to send."
        return {
            "action": "send_payment_reminders",
            "title": "Send payment reminders",
            "count": len(items),
            "summary": summary,
            "items": items,
            "confirm_label": (f"Send {sendable} & log {len(items)}" if sendable
                              else f"Log {len(items)} reminder{'s' if len(items) != 1 else ''}"),
            "warning": warning,
            "executable": len(items) > 0,
        }
    finally:
        db.close()


def _reminders_execute(user_id: int, params: dict) -> dict:
    # Re-derive from the DB (never trust client-supplied items)
    preview = _reminders_preview(user_id, params)
    items = preview["items"]
    if not items:
        return {"ok": False, "executed": 0,
                "markdown": "✅ No overdue customers — no reminders to send."}

    business = None
    sent = logged = skipped = 0
    db = SessionLocal()
    try:
        business = _business_name(db, user_id)
        for it in items:
            cust = it["customer"]
            # Idempotency: don't email the same customer twice in one day.
            if it["channel"] == "email" and _already_reminded_today(db, user_id, cust):
                skipped += 1
                continue

            status = "logged"
            if it["channel"] == "email" and it.get("email"):
                ok = send_email(it["email"],
                                f"Payment reminder from {business}",
                                it["message"])
                status = "sent" if ok else "failed"
                if ok:
                    sent += 1
                else:
                    logged += 1
            else:
                logged += 1   # no email / SMTP off → draft logged only

            db.add(ActionLog(
                business_id=user_id, action="send_payment_reminders",
                target=cust, amount=it["amount"], detail=it["message"], status=status,
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"[ACTION] Failed to process reminders: {e}", exc_info=True)
        return {"ok": False, "executed": 0,
                "markdown": "❌ Could not process the reminders. Please try again."}
    finally:
        db.close()

    parts = []
    if sent:    parts.append(f"📧 **Emailed {sent}**")
    if logged:  parts.append(f"📝 Drafted & logged {logged} (no email on file)")
    if skipped: parts.append(f"⏭️ Skipped {skipped} (already reminded today)")
    head = " · ".join(parts) if parts else "Nothing to do."
    return {"ok": True, "executed": sent + logged,
            "markdown": f"**Payment reminders processed.**\n\n{head}"}


# ── mark_invoice_paid ───────────────────────────────────────────────
def _mark_paid_preview(user_id: int, params: dict) -> dict:
    import re
    q = (params or {}).get("query", "") or (params or {}).get("invoice_id", "")
    m = re.search(r"\b([A-Za-z]{2,6}-INV-\d+)\b", q, re.I)
    inv_id = (params or {}).get("invoice_id") or (m.group(1) if m else None)
    if not inv_id:
        return {"action": "mark_invoice_paid", "title": "Mark invoice paid",
                "summary": "No invoice ID found in the request.", "items": [],
                "executable": False, "warning": "Tell me which invoice, e.g. SUP-INV-0049."}
    db = SessionLocal()
    try:
        r = (db.query(Invoice)
             .filter(Invoice.business_id == user_id,
                     func.lower(Invoice.invoice_id) == inv_id.lower())
             .first())
        if not r:
            return {"action": "mark_invoice_paid", "title": "Mark invoice paid",
                    "summary": f"No invoice {inv_id} found in your records.",
                    "items": [], "executable": False}
        already = (r.status == "Paid")
        return {
            "action": "mark_invoice_paid", "title": "Mark invoice paid",
            "summary": (f"{r.invoice_id} ({r.customer}, ₹{(r.amount or 0):,.0f}) is already Paid."
                        if already else
                        f"Mark {r.invoice_id} — {r.customer}, ₹{(r.amount or 0):,.0f} — as Paid?"),
            "items": [{"invoice_id": r.invoice_id, "customer": r.customer,
                       "amount": float(r.amount or 0), "status": r.status}],
            "confirm_label": "Mark as Paid",
            "executable": not already,
            "params": {"invoice_id": r.invoice_id},
        }
    finally:
        db.close()


def _mark_paid_execute(user_id: int, params: dict) -> dict:
    inv_id = (params or {}).get("invoice_id")
    if not inv_id:
        pv = _mark_paid_preview(user_id, params)
        inv_id = (pv.get("params") or {}).get("invoice_id")
    if not inv_id:
        return {"ok": False, "executed": 0, "markdown": "❌ No invoice specified."}
    db = SessionLocal()
    try:
        r = (db.query(Invoice)
             .filter(Invoice.business_id == user_id,
                     func.lower(Invoice.invoice_id) == inv_id.lower())
             .first())
        if not r:
            return {"ok": False, "executed": 0, "markdown": f"❌ Invoice {inv_id} not found."}
        if r.status == "Paid":
            return {"ok": True, "executed": 0, "markdown": f"✅ {r.invoice_id} was already marked Paid."}
        prev = r.status
        r.status = "Paid"
        db.add(ActionLog(business_id=user_id, action="mark_invoice_paid",
                         target=r.invoice_id, amount=r.amount,
                         detail=f"status {prev} → Paid", status="done"))
        db.commit()
        try:
            from services.context_cache import invalidate_user_cache
            invalidate_user_cache(user_id)   # invoice data changed
        except Exception:
            pass
        return {"ok": True, "executed": 1,
                "markdown": f"✅ **{r.invoice_id}** marked **Paid** (was {prev})."}
    except Exception as e:
        db.rollback()
        logger.error(f"[ACTION] mark_invoice_paid failed: {e}", exc_info=True)
        return {"ok": False, "executed": 0, "markdown": "❌ Could not update the invoice."}
    finally:
        db.close()


# ── Registry ────────────────────────────────────────────────────────
ACTIONS = {
    "send_payment_reminders": {
        "preview": _reminders_preview,
        "execute": _reminders_execute,
    },
    "mark_invoice_paid": {
        "preview": _mark_paid_preview,
        "execute": _mark_paid_execute,
    },
}


def is_action(action_key: str) -> bool:
    return action_key in ACTIONS


def preview(action_key: str, user_id: int, params: dict = None) -> Optional[dict]:
    spec = ACTIONS.get(action_key)
    if not spec:
        return None
    try:
        return spec["preview"](user_id, params or {})
    except Exception as e:
        logger.error(f"[ACTION] preview '{action_key}' failed: {e}", exc_info=True)
        return None


def execute(action_key: str, user_id: int, params: dict = None) -> Optional[dict]:
    spec = ACTIONS.get(action_key)
    if not spec:
        return None
    try:
        return spec["execute"](user_id, params or {})
    except Exception as e:
        logger.error(f"[ACTION] execute '{action_key}' failed: {e}", exc_info=True)
        return None
