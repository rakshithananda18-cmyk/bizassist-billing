"""
scheduler.py
============
APScheduler setup for BizAssist proactive alerts.

All jobs run on IST (Asia/Kolkata) timezone.

Schedule:
  08:00  — Daily business summary
  09:00  — Overdue invoice alerts
  09:05  — Low stock alerts
  09:10  — Expiry warnings

Usage:
  from services.scheduler import start_scheduler
  start_scheduler()   # call once at app startup
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("bizassist.scheduler")

_scheduler: BackgroundScheduler = None


def start_scheduler():
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("[SCHED] Already running — skipping re-init.")
        return

    from services.alert_jobs import (
        run_daily_summary,
        run_overdue_alerts,
        run_low_stock_alerts,
        run_expiry_alerts,
    )

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    _scheduler.add_job(
        run_daily_summary,
        CronTrigger(hour=8, minute=0),
        id="daily_summary",
        name="Daily Business Summary",
        replace_existing=True,
        misfire_grace_time=3600,  # tolerate up to 1h delay on startup
    )

    _scheduler.add_job(
        run_overdue_alerts,
        CronTrigger(hour=9, minute=0),
        id="overdue_alerts",
        name="Overdue Invoice Alerts",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.add_job(
        run_low_stock_alerts,
        CronTrigger(hour=9, minute=5),
        id="low_stock_alerts",
        name="Low Stock Alerts",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.add_job(
        run_expiry_alerts,
        CronTrigger(hour=9, minute=10),
        id="expiry_alerts",
        name="Expiry Alerts",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    logger.info(
        "[SCHED] Started. Jobs: daily summary @ 8:00 IST, "
        "overdue/low-stock/expiry @ 9:00–9:10 IST."
    )


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHED] Stopped.")


def get_scheduler() -> BackgroundScheduler:
    return _scheduler
