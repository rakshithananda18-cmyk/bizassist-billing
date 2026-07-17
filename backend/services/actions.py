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
from database.models import Invoice, User, ActionLog, Customer, AlertConfig, Inventory
from services.notifier import send_email, is_configured as email_configured
from services.dates import parse_date, utc_now

logger = logging.getLogger("bizassist.actions")


# ── Helpers ─────────────────────────────────────────────────────────
def _business_name(db, user_id: int) -> str:
    u = db.query(User).filter(User.id == user_id).first()
    return (u.business_name if u and u.business_name else "our team")


def _owner_email(db, user_id: int) -> Optional[str]:
    """Where to send owner-facing digests: the account email, else the alert email."""
    u = db.query(User).filter(User.id == user_id).first()
    if u and getattr(u, "email", None):
        return u.email
    cfg = db.query(AlertConfig).filter(AlertConfig.business_id == user_id).first()
    return (cfg.email or None) if cfg else None


def _action_done_today(db, user_id: int, action: str, target: str, statuses=("sent", "done")) -> bool:
    """Idempotency for once-a-day owner-facing actions."""
    start = datetime.combine(utc_now().date(), datetime.min.time())
    return db.query(ActionLog).filter(
        ActionLog.business_id == user_id, ActionLog.action == action,
        ActionLog.target == target, ActionLog.status.in_(list(statuses)),
        ActionLog.created_at >= start,
    ).first() is not None


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
    start = datetime.combine(utc_now().date(), datetime.min.time())
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
    params = params or {}
    selected = [c for c in params.get("customers", []) if c]
    db = SessionLocal()
    try:
        business = _business_name(db, user_id)
        # Honour a SINGLE named target from the LLM router (e.g. "follow up with
        # Sri Venkateswara about INV-0007") — fuzzy-resolve the hint to a real
        # overdue customer so the preview scopes to them, not all 20 (B4). An
        # invoice_id hint resolves to that invoice's customer.
        if not selected:
            target = params.get("customer")
            inv_id = params.get("invoice_id")
            overdue_names = [r[0] for r in db.query(Invoice.customer)
                             .filter(Invoice.business_id == user_id,
                                     Invoice.status == "Overdue").distinct().all()]
            if not target and inv_id:
                row = (db.query(Invoice.customer)
                       .filter(Invoice.business_id == user_id,
                               func.lower(Invoice.invoice_id) == str(inv_id).lower())
                       .first())
                if row:
                    target = row[0]
            if target:
                from services.direct_query_handler import _match_customer_name
                resolved = _match_customer_name(target, overdue_names) or \
                    (target if target in overdue_names else None)
                if resolved:
                    selected = [resolved]
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


# ── email_reminder_digest (owner digest — works without customer emails) ───
def _digest_rows(db, user_id: int):
    return (db.query(Invoice.customer, func.sum(Invoice.amount).label("total"),
                     func.max(Invoice.due_date).label("due"), func.count(Invoice.id).label("n"))
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer).order_by(func.sum(Invoice.amount).desc()).all())


def _digest_preview(user_id: int, params: dict) -> dict:
    db = SessionLocal()
    try:
        owner = _owner_email(db, user_id)
        rows = _digest_rows(db, user_id)
        total = sum(float(r.total or 0) for r in rows)
        items = [{"customer": r.customer, "amount": float(r.total or 0), "invoices": int(r.n or 0)} for r in rows]
        if not rows:
            summary, warning, executable = "No overdue customers — nothing to send.", "", False
        elif not owner:
            summary = f"{len(rows)} overdue customer(s) — ₹{total:,.0f} total"
            warning = "No account email on file — add your email to receive the digest."
            executable = False
        elif not email_configured():
            summary = f"Email a digest of {len(rows)} overdue customer(s) (₹{total:,.0f}) to {owner}"
            warning = "Email isn't configured (set EMAIL_USER / EMAIL_PASS in .env) — can't send yet."
            executable = False
        else:
            summary = f"Email a digest of {len(rows)} overdue customer(s) (₹{total:,.0f}) to {owner}"
            warning, executable = "", True
        return {"action": "email_reminder_digest", "title": "Email me the reminder digest",
                "summary": summary, "items": items, "confirm_label": "Email me the digest",
                "warning": warning, "executable": executable, "recipient": owner}
    finally:
        db.close()


def _digest_execute(user_id: int, params: dict) -> dict:
    db = SessionLocal()
    try:
        owner = _owner_email(db, user_id)
        business = _business_name(db, user_id)
        rows = _digest_rows(db, user_id)
        if not rows:
            return {"ok": False, "executed": 0, "markdown": "✅ No overdue customers — nothing to send."}
        if not owner:
            return {"ok": False, "executed": 0, "markdown": "❌ No account email on file — add your email first."}
        if not email_configured():
            return {"ok": False, "executed": 0, "markdown": "❌ Email isn't configured (set EMAIL_USER / EMAIL_PASS in .env)."}
        if _action_done_today(db, user_id, "email_reminder_digest", owner):
            return {"ok": True, "executed": 0, "markdown": "⏭️ Digest already emailed to you today."}
        total = sum(float(r.total or 0) for r in rows)
        lines = [f"Overdue summary for {business} — {len(rows)} customers, ₹{total:,.0f} outstanding:\n"]
        for r in rows:
            due = f", due {r.due}" if r.due else ""
            lines.append(f"- {r.customer}: ₹{float(r.total or 0):,.0f} ({int(r.n or 0)} invoice(s){due})")
        body = "\n".join(lines) + "\n\nSent by BizAssist."
        ok = send_email(owner, f"Overdue reminders digest — {business}", body)
        db.add(ActionLog(business_id=user_id, action="email_reminder_digest", target=owner,
                         amount=total, detail=body, status="sent" if ok else "failed"))
        db.commit()
        return {"ok": ok, "executed": 1 if ok else 0,
                "markdown": (f"📧 Emailed your overdue digest ({len(rows)} customers, ₹{total:,.0f}) to **{owner}**."
                             if ok else "❌ Couldn't send the email — check your SMTP settings.")}
    except Exception as e:
        db.rollback()
        logger.error(f"[ACTION] digest failed: {e}", exc_info=True)
        return {"ok": False, "executed": 0, "markdown": "❌ Could not send the digest."}
    finally:
        db.close()


# ── escalate_overdue (90+ days, firmer tone) ────────────────────────
_ESCALATE_DAYS = 90


def _escalate_message(customer: str, amount: float, business: str, days: int) -> str:
    return (
        f"Dear {customer},\n\n"
        f"Our records show an overdue balance of ₹{amount:,.0f} that is now more than {days} days "
        f"past due. Please arrange payment immediately, or contact us within 7 days to agree a payment "
        f"plan and avoid further action.\n\n"
        f"If payment has already been made, kindly share the details.\n\n"
        f"Regards,\n{business}"
    )


def _escalate_preview(user_id: int, params: dict) -> dict:
    db = SessionLocal()
    try:
        business = _business_name(db, user_id)
        now = utc_now()
        rows = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").all()
        agg = {}
        for r in rows:
            due = parse_date(r.due_date)
            days = (now - due).days if due else 0
            if days >= _ESCALATE_DAYS:
                a = agg.setdefault(r.customer, {"amount": 0.0, "maxdays": 0})
                a["amount"] += float(r.amount or 0)
                a["maxdays"] = max(a["maxdays"], days)
        smtp_ok = email_configured()
        items = []
        for c, v in sorted(agg.items(), key=lambda x: -x[1]["amount"]):
            email = _customer_email(db, user_id, c)
            channel = "email" if (email and smtp_ok) else ("email_unconfigured" if email else "no_contact")
            items.append({"customer": c, "amount": v["amount"], "days": v["maxdays"],
                          "email": email, "channel": channel,
                          "message": _escalate_message(c, v["amount"], business, _ESCALATE_DAYS)})
        total = sum(i["amount"] for i in items)
        return {"action": "escalate_overdue", "title": "Escalate 90+ day overdue",
                "summary": (f"{len(items)} account(s) {_ESCALATE_DAYS}+ days overdue — ₹{total:,.0f}"
                            if items else f"No accounts are {_ESCALATE_DAYS}+ days overdue."),
                "items": items, "confirm_label": f"Escalate {len(items)}",
                "warning": ("" if smtp_ok else
                            "Email isn't configured — escalations will be drafted and logged, not sent."),
                "executable": len(items) > 0}
    finally:
        db.close()


def _escalate_execute(user_id: int, params: dict) -> dict:
    items = _escalate_preview(user_id, params)["items"]
    if not items:
        return {"ok": False, "executed": 0, "markdown": f"✅ No accounts {_ESCALATE_DAYS}+ days overdue."}
    sent = logged = skipped = 0
    db = SessionLocal()
    try:
        business = _business_name(db, user_id)
        for it in items:
            cust = it["customer"]
            if it["channel"] == "email" and _action_done_today(db, user_id, "escalate_overdue", cust, statuses=("sent",)):
                skipped += 1
                continue
            status = "logged"
            if it["channel"] == "email" and it.get("email"):
                ok = send_email(it["email"], f"Urgent: overdue account — {business}", it["message"])
                status = "sent" if ok else "failed"
                sent += 1 if ok else 0
                logged += 0 if ok else 1
            else:
                logged += 1
            db.add(ActionLog(business_id=user_id, action="escalate_overdue", target=cust,
                             amount=it["amount"], detail=it["message"], status=status))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"[ACTION] escalate failed: {e}", exc_info=True)
        return {"ok": False, "executed": 0, "markdown": "❌ Could not process escalations."}
    finally:
        db.close()
    parts = []
    if sent:    parts.append(f"📧 Escalated {sent} by email")
    if logged:  parts.append(f"📝 Drafted {logged} (no email)")
    if skipped: parts.append(f"⏭️ Skipped {skipped} (already escalated today)")
    return {"ok": True, "executed": sent + logged,
            "markdown": f"**90+ day escalations processed.**\n\n{' · '.join(parts) or 'Nothing to do.'}"}


# ── draft_reorder_po (low stock → reorder draft) ────────────────────
def _reorder_low_items(db, user_id: int) -> list:
    out = []
    for it in db.query(Inventory).filter(Inventory.business_id == user_id).all():
        s = it.stock if isinstance(it.stock, int) else (int(it.stock) if str(it.stock or "").strip().isdigit() else None)
        rp = it.reorder_point or 10
        if s is not None and s <= rp:
            out.append({"product": it.product_name or "—", "stock": s, "reorder_point": rp,
                        "suggested_qty": max(rp * 2 - s, rp), "supplier": it.supplier or "—"})
    out.sort(key=lambda x: x["stock"])
    return out


def _reorder_preview(user_id: int, params: dict) -> dict:
    db = SessionLocal()
    try:
        low = _reorder_low_items(db, user_id)
        items = [{"customer": f"{l['product']} (stock {l['stock']})", "amount": l["suggested_qty"],
                  "message": f"Reorder {l['suggested_qty']} units of {l['product']} "
                             f"(supplier: {l['supplier']}; stock {l['stock']} ≤ reorder point {l['reorder_point']})."}
                 for l in low]
        return {"action": "draft_reorder_po", "title": "Draft reorder list",
                "summary": (f"{len(low)} product(s) at/under reorder point" if low
                            else "All products are above their reorder point."),
                "items": items, "confirm_label": f"Log reorder draft ({len(low)})",
                "warning": "Draft only — no order is placed.", "executable": len(low) > 0}
    finally:
        db.close()


def _reorder_execute(user_id: int, params: dict) -> dict:
    db = SessionLocal()
    try:
        low = _reorder_low_items(db, user_id)
        if not low:
            return {"ok": False, "executed": 0, "markdown": "✅ Nothing to reorder — all stock is above reorder point."}
        for l in low:
            db.add(ActionLog(business_id=user_id, action="draft_reorder_po", target=l["product"],
                             amount=l["suggested_qty"],
                             detail=f"Reorder {l['suggested_qty']} units (supplier {l['supplier']}, stock {l['stock']})",
                             status="done"))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"[ACTION] reorder failed: {e}", exc_info=True)
        return {"ok": False, "executed": 0, "markdown": "❌ Could not log the reorder draft."}
    finally:
        db.close()
    lines = [f"**Reorder draft — {len(low)} product(s).**\n"]
    for l in low:
        lines.append(f"- **{l['product']}**: reorder **{l['suggested_qty']}** (stock {l['stock']}, supplier {l['supplier']})")
    return {"ok": True, "executed": len(low), "markdown": "\n".join(lines)}


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
    "email_reminder_digest": {
        "preview": _digest_preview,
        "execute": _digest_execute,
    },
    "escalate_overdue": {
        "preview": _escalate_preview,
        "execute": _escalate_execute,
    },
    "draft_reorder_po": {
        "preview": _reorder_preview,
        "execute": _reorder_execute,
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
    # Phase-0 write rail #3: per-business, per-action daily cap — enforced at
    # the dispatcher so EVERY entry point (HTTP route today, agent runtime
    # tomorrow) hits the same wall. A runaway loop can't spam customers.
    try:
        from services.action_rails import check_daily_cap
        db = SessionLocal()
        try:
            allowed, used, cap = check_daily_cap(db, user_id, action_key)
        finally:
            db.close()
        if not allowed:
            logger.warning(f"[ACTION] daily cap reached for '{action_key}' biz={user_id} ({used}/{cap})")
            return {
                "ok": False, "executed": 0, "error": "daily_cap_reached",
                "used": used, "cap": cap,
                "markdown": (f"⛔ **Daily limit reached for this action** ({used}/{cap} today). "
                             "It resets at midnight UTC — raise the cap in settings/env if this was intentional."),
            }
    except Exception as e:  # the cap must never turn into an outage
        logger.error(f"[ACTION] cap check failed for '{action_key}': {e}", exc_info=True)
    try:
        return spec["execute"](user_id, params or {})
    except Exception as e:
        logger.error(f"[ACTION] execute '{action_key}' failed: {e}", exc_info=True)
        return None
