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
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, User, ActionLog

logger = logging.getLogger("bizassist.actions")


# ── Helpers ─────────────────────────────────────────────────────────
def _business_name(db, user_id: int) -> str:
    u = db.query(User).filter(User.id == user_id).first()
    return (u.business_name if u and u.business_name else "our team")


def _reminder_message(customer: str, amount: float, business: str, due: str | None) -> str:
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
    db = SessionLocal()
    try:
        business = _business_name(db, user_id)
        rows = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("total"),
                func.max(Invoice.due_date).label("due"),
                func.count(Invoice.id).label("invoices"),
            )
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .all()
        )

        items = [{
            "customer": r.customer,
            "amount": float(r.total or 0),
            "invoices": int(r.invoices or 0),
            "due": r.due,
            "message": _reminder_message(r.customer, r.total or 0, business, r.due),
        } for r in rows]

        total = sum(i["amount"] for i in items)
        return {
            "action": "send_payment_reminders",
            "title": "Send payment reminders",
            "count": len(items),
            "summary": (
                f"{len(items)} overdue customer{'s' if len(items) != 1 else ''} "
                f"— ₹{total:,.0f} total"
            ) if items else "No overdue customers — nothing to remind.",
            "items": items,
            "confirm_label": f"Log {len(items)} reminder{'s' if len(items) != 1 else ''}",
            "warning": "Drafts only — nothing is emailed. Copy each message to send it.",
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

    db = SessionLocal()
    try:
        for it in items:
            db.add(ActionLog(
                business_id=user_id,
                action="send_payment_reminders",
                target=it["customer"],
                amount=it["amount"],
                detail=it["message"],
                status="logged",
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to log reminders: {e}", exc_info=True)
        return {"ok": False, "executed": 0,
                "markdown": "❌ Could not record the reminders. Please try again."}
    finally:
        db.close()

    lines = [f"**Logged {len(items)} payment reminder{'s' if len(items) != 1 else ''}.**\n",
             "Copy-ready drafts (nothing was emailed):\n"]
    for it in items:
        lines.append(f"- **{it['customer']}** — ₹{it['amount']:,.0f}")
    return {"ok": True, "executed": len(items), "markdown": "\n".join(lines)}


# ── Registry ────────────────────────────────────────────────────────
ACTIONS = {
    "send_payment_reminders": {
        "preview": _reminders_preview,
        "execute": _reminders_execute,
    },
}


def is_action(action_key: str) -> bool:
    return action_key in ACTIONS


def preview(action_key: str, user_id: int, params: dict = None) -> dict | None:
    spec = ACTIONS.get(action_key)
    if not spec:
        return None
    try:
        return spec["preview"](user_id, params or {})
    except Exception as e:
        logger.error(f"action preview '{action_key}' failed: {e}", exc_info=True)
        return None


def execute(action_key: str, user_id: int, params: dict = None) -> dict | None:
    spec = ACTIONS.get(action_key)
    if not spec:
        return None
    try:
        return spec["execute"](user_id, params or {})
    except Exception as e:
        logger.error(f"action execute '{action_key}' failed: {e}", exc_info=True)
        return None
