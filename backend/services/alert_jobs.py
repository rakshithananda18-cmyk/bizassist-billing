"""
alert_jobs.py
=============
The four proactive alert jobs for BizAssist Phase 4.

Jobs:
  run_overdue_alerts()    — invoices past due with Overdue status
  run_low_stock_alerts()  — inventory items at or below threshold
  run_expiry_alerts()     — products expiring within N days
  run_daily_summary()     — morning business digest

Each job:
  1. Loads all active AlertConfig rows
  2. Queries the DB per business
  3. Calls notifier.notify() to send via email + WhatsApp
"""

import logging
from datetime import datetime
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory, AlertConfig, User
from services.notifier import notify
from services.dates import parse_date

logger = logging.getLogger("bizassist.alerts")


# ── Helper ────────────────────────────────────────────────────

def _load_active_configs() -> list:
    """Returns a list of dicts for all active alert configs."""
    db = SessionLocal()
    try:
        configs = db.query(AlertConfig).filter(AlertConfig.active == True).all()
        return [
            {
                "business_id":          c.business_id,
                "business_name":        c.business_name or f"Business {c.business_id}",
                "email":                c.email,
                "whatsapp_number":      c.whatsapp_number,
                "alert_overdue":        c.alert_overdue,
                "alert_low_stock":      c.alert_low_stock,
                "alert_expiry":         c.alert_expiry,
                "alert_daily_summary":  c.alert_daily_summary,
                "low_stock_threshold":  c.low_stock_threshold,
                "expiry_days_threshold": c.expiry_days_threshold,
            }
            for c in configs
        ]
    finally:
        db.close()


# ── Job 1: Overdue Invoices ───────────────────────────────────

def run_overdue_alerts():
    logger.info("[SCHED] Running overdue invoice alerts...")
    configs = [c for c in _load_active_configs() if c["alert_overdue"]]
    if not configs:
        logger.info("[SCHED] No businesses opted into overdue alerts.")
        return

    db = SessionLocal()
    try:
        for cfg in configs:
            bid = cfg["business_id"]

            overdue = (
                db.query(Invoice)
                .filter(Invoice.business_id == bid, Invoice.status == "Overdue")
                .order_by(Invoice.amount.desc())
                .limit(10)
                .all()
            )

            if not overdue:
                logger.info(f"[ALERT] No overdue invoices for business_id={bid}. Skipping.")
                continue

            total = sum(inv.amount or 0 for inv in overdue)

            lines = [
                f"⚠️ BizAssist: Overdue Invoice Alert",
                f"Business: {cfg['business_name']}",
                f"",
                f"You have {len(overdue)} overdue invoice(s) totalling ₹{total:,.0f}.",
                f"",
                f"Top overdue accounts:",
            ]
            for inv in overdue[:5]:
                lines.append(f"  • {inv.customer}: ₹{inv.amount:,.0f}  (Due: {inv.due_date})")
            if len(overdue) > 5:
                lines.append(f"  … and {len(overdue) - 5} more.")
            lines += [
                f"",
                f"Follow up promptly to recover outstanding payments.",
                f"– BizAssist AI"
            ]

            body = "\n".join(lines)
            subject = f"⚠️ {len(overdue)} Overdue Invoice(s) — ₹{total:,.0f} Pending"
            notify(cfg["email"], cfg["whatsapp_number"], subject, body)
            logger.info(f"[ALERT] Overdue alert dispatched for business_id={bid}")
    finally:
        db.close()


# ── Job 2: Low Stock ─────────────────────────────────────────

def run_low_stock_alerts():
    logger.info("[SCHED] Running low stock alerts...")
    configs = [c for c in _load_active_configs() if c["alert_low_stock"]]
    if not configs:
        logger.info("[SCHED] No businesses opted into low stock alerts.")
        return

    db = SessionLocal()
    try:
        for cfg in configs:
            bid       = cfg["business_id"]
            threshold = cfg["low_stock_threshold"]

            low = (
                db.query(Inventory)
                .filter(Inventory.business_id == bid, Inventory.stock <= threshold)
                .order_by(Inventory.stock.asc())
                .limit(15)
                .all()
            )

            if not low:
                logger.info(f"[ALERT] No low stock items for business_id={bid}. Skipping.")
                continue

            lines = [
                f"📦 BizAssist: Low Stock Alert",
                f"Business: {cfg['business_name']}",
                f"",
                f"{len(low)} product(s) are at or below {threshold} units:",
                f"",
            ]
            for item in low:
                lines.append(f"  • {item.product_name}: {item.stock} unit(s) remaining")
            lines += [
                f"",
                f"Reorder soon to avoid stockouts and lost sales.",
                f"– BizAssist AI"
            ]

            body    = "\n".join(lines)
            subject = f"📦 {len(low)} Product(s) Low on Stock — Action Needed"
            notify(cfg["email"], cfg["whatsapp_number"], subject, body)
            logger.info(f"[ALERT] Low stock alert dispatched for business_id={bid}")
    finally:
        db.close()


# ── Job 3: Expiry Warnings ────────────────────────────────────

def run_expiry_alerts():
    logger.info("[SCHED] Running expiry alerts...")
    configs = [c for c in _load_active_configs() if c["alert_expiry"]]
    if not configs:
        logger.info("[SCHED] No businesses opted into expiry alerts.")
        return

    db = SessionLocal()
    today = datetime.today()

    try:
        for cfg in configs:
            bid  = cfg["business_id"]
            days = cfg["expiry_days_threshold"]

            all_items = (
                db.query(Inventory)
                .filter(Inventory.business_id == bid, Inventory.expiry_date != None)
                .all()
            )

            expiring = []
            for item in all_items:
                exp = parse_date(item.expiry_date)
                if exp is None:
                    continue
                days_left = (exp - today).days
                if 0 <= days_left <= days:
                    expiring.append((item, days_left))

            if not expiring:
                logger.info(f"[ALERT] No expiring items for business_id={bid}. Skipping.")
                continue

            expiring.sort(key=lambda x: x[1])

            lines = [
                f"🗓️ BizAssist: Expiry Alert",
                f"Business: {cfg['business_name']}",
                f"",
                f"{len(expiring)} product(s) expiring within {days} days:",
                f"",
            ]
            for item, days_left in expiring[:10]:
                lines.append(
                    f"  • {item.product_name}: expires {item.expiry_date} ({days_left} day(s) left)"
                )
            if len(expiring) > 10:
                lines.append(f"  … and {len(expiring) - 10} more.")
            lines += [
                f"",
                f"Consider discounting or bundling these products to clear them before expiry.",
                f"– BizAssist AI"
            ]

            body    = "\n".join(lines)
            subject = f"🗓️ {len(expiring)} Product(s) Expiring Within {days} Days"
            notify(cfg["email"], cfg["whatsapp_number"], subject, body)
            logger.info(f"[ALERT] Expiry alert dispatched for business_id={bid}")
    finally:
        db.close()


# ── Job 4: Daily Business Summary ────────────────────────────

def run_daily_summary():
    logger.info("[SCHED] Running daily business summaries...")
    configs = [c for c in _load_active_configs() if c["alert_daily_summary"]]
    if not configs:
        logger.info("[SCHED] No businesses opted into daily summary.")
        return

    db    = SessionLocal()
    today = datetime.today()

    try:
        for cfg in configs:
            bid = cfg["business_id"]

            # Revenue stats
            total_rev   = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == bid).scalar() or 0
            paid_rev    = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == bid, Invoice.status == "Paid").scalar() or 0
            overdue_amt = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == bid, Invoice.status == "Overdue").scalar() or 0
            overdue_cnt = db.query(Invoice).filter(Invoice.business_id == bid, Invoice.status == "Overdue").count()
            pending_cnt = db.query(Invoice).filter(Invoice.business_id == bid, Invoice.status == "Pending").count()

            collection_rate = round((paid_rev / total_rev * 100)) if total_rev else 0

            # Inventory stats
            threshold      = cfg["low_stock_threshold"]
            exp_days       = cfg["expiry_days_threshold"]
            inv_total      = db.query(Inventory).filter(Inventory.business_id == bid).count()
            low_stock_cnt  = db.query(Inventory).filter(Inventory.business_id == bid, Inventory.stock <= threshold).count()

            all_items = db.query(Inventory).filter(Inventory.business_id == bid).all()
            expiring_cnt = 0
            for item in all_items:
                exp = parse_date(item.expiry_date)
                if exp is None:
                    continue
                days_left = (exp - today).days
                if 0 <= days_left <= exp_days:
                    expiring_cnt += 1

            lines = [
                f"☀️ Good morning! BizAssist Daily Summary",
                f"Business: {cfg['business_name']}",
                f"Date: {today.strftime('%A, %d %B %Y')}",
                f"",
                f"── Revenue ──────────────────────",
                f"  Total Revenue    : ₹{total_rev:,.0f}",
                f"  Collected (Paid) : ₹{paid_rev:,.0f}  ({collection_rate}% collected)",
                f"  Overdue          : ₹{overdue_amt:,.0f}  ({overdue_cnt} invoice(s))",
                f"  Pending          : {pending_cnt} invoice(s) awaiting payment",
                f"",
                f"── Inventory ────────────────────",
                f"  Total Products   : {inv_total}",
                f"  Low Stock (≤{threshold}) : {low_stock_cnt} item(s)",
                f"  Expiring Soon    : {expiring_cnt} item(s) within {exp_days} days",
                f"",
            ]

            # Action callouts
            if overdue_cnt > 0:
                lines.append(f"🔴 Action: Follow up on {overdue_cnt} overdue invoice(s) — ₹{overdue_amt:,.0f} at risk.")
            if low_stock_cnt > 0:
                lines.append(f"🟡 Action: Reorder {low_stock_cnt} low-stock product(s) to prevent stockouts.")
            if expiring_cnt > 0:
                lines.append(f"🟠 Action: Promote or discount {expiring_cnt} product(s) expiring within {exp_days} days.")
            if overdue_cnt == 0 and low_stock_cnt == 0 and expiring_cnt == 0:
                lines.append(f"✅ All clear — no urgent actions today. Have a productive day!")

            lines += [f"", f"– BizAssist AI"]

            body    = "\n".join(lines)
            subject = f"☀️ Daily Summary — {today.strftime('%d %b %Y')} | {cfg['business_name']}"
            notify(cfg["email"], cfg["whatsapp_number"], subject, body)
            logger.info(f"[ALERT] Daily summary dispatched for business_id={bid}")
    finally:
        db.close()
