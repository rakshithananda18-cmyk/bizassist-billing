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
  Sun 23:00 — Weekly memory distillation (Phase 4)

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
        run_memory_distillation,
    )
    from services.sync_worker import run_hybrid_sync

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

    _scheduler.add_job(
        run_memory_distillation,
        CronTrigger(day_of_week="sun", hour=23, minute=0),
        id="memory_distillation",
        name="Weekly Memory Distillation",
        replace_existing=True,
        misfire_grace_time=86400,  # tolerate up to 24h (weekly job)
    )

    _scheduler.add_job(
        run_hybrid_sync,
        "interval",
        seconds=15,             # tick interval (per-business sync is still gated by sync_interval, default 30s)
        id="hybrid_sync",
        name="Hybrid Sync Engine",
        replace_existing=True,
        max_instances=1,        # never overlap
        coalesce=True,          # collapse missed ticks into one instead of logging "skipped"
        misfire_grace_time=30,  # tolerate a late run rather than warning
    )

    # ── Telemetry relay + retention (Admin Console plan) ─────────────────────
    # Relay: local installs ship new telemetry lines to the cloud every 3h
    # (no-op on the cloud backend / when TELEMETRY_RELAY=0). First run ~2min
    # after boot so fresh field issues surface quickly.
    from services.telemetry_relay import run_telemetry_relay, run_telemetry_retention
    from datetime import datetime, timedelta

    _scheduler.add_job(
        run_telemetry_relay,
        "interval",
        hours=3,
        next_run_time=datetime.now(_scheduler.timezone) + timedelta(minutes=2),
        id="telemetry_relay",
        name="Telemetry Relay (local → cloud)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Retention: trim telemetry logs (global + per-business) to the last
    # TELEMETRY_RETENTION_DAYS days (default 7). Runs everywhere, nightly.
    _scheduler.add_job(
        run_telemetry_retention,
        CronTrigger(hour=2, minute=30),
        id="telemetry_retention",
        name="Telemetry Retention Trim",
        replace_existing=True,
        misfire_grace_time=86400,
    )

    # DB maintenance: weekly purge of the PERSISTENT telemetry_events table
    # (Supabase on the cloud) + 200 MB size guard. See telemetry_maintenance.py.
    from services.telemetry_maintenance import run_telemetry_db_maintenance
    _scheduler.add_job(
        run_telemetry_db_maintenance,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="telemetry_db_maintenance",
        name="Telemetry DB Maintenance (weekly purge + size guard)",
        replace_existing=True,
        misfire_grace_time=86400,
    )

    _scheduler.start()
    logger.info(
        "[SCHED] Started. Jobs: daily summary @ 8:00 IST, "
        "overdue/low-stock/expiry @ 9:00–9:10 IST, "
        "memory distillation @ Sunday 23:00 IST, "
        "telemetry relay every 3h + retention trim @ 2:30 IST, "
        "telemetry DB maintenance @ Sunday 3:00 IST."
    )


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHED] Stopped.")


def get_scheduler() -> BackgroundScheduler:
    return _scheduler
