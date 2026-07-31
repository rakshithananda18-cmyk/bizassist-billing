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

import atexit
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("bizassist.scheduler")

_scheduler: BackgroundScheduler = None

# ── Interpreter-shutdown guard ───────────────────────────────────────────────
# Symptom this fixes: an endless stream of
#     RuntimeError: cannot schedule new futures after interpreter shutdown
# once every job interval, forever, after the process was asked to stop.
#
# Why it happened: APScheduler's BackgroundScheduler runs its own thread and
# submits each due job to a ThreadPoolExecutor. `concurrent.futures.thread`
# registers an atexit hook at IMPORT time which flips a module-global
# `_shutdown` flag, after which every `submit()` raises. If the scheduler is
# still ticking at that point, it raises on every single tick and logs a full
# traceback each time.
#
# Normally `stop_scheduler()` runs from the FastAPI lifespan and this never
# arises. But under `uvicorn --reload` the app runs in a spawned CHILD process
# that the reloader terminates directly — on Windows especially, the child can
# die without the lifespan shutdown ever completing. The scheduler thread then
# outlives the orderly shutdown and spams until the process is finally reaped.
#
# The fix is ordering: atexit handlers run LIFO, and `concurrent.futures.thread`
# registered its hook when it was first imported (early). Registering ours AT
# MODULE IMPORT — before any scheduler exists — therefore guarantees we run
# BEFORE the pool is torn down, so the scheduler is already stopped by the time
# `submit()` would start failing.
_SHUTTING_DOWN = threading.Event()


def start_scheduler():
    global _scheduler

    if _SHUTTING_DOWN.is_set():
        # A late startup during teardown would resurrect the exact loop the
        # atexit hook exists to prevent.
        logger.info("[SCHED] Interpreter is shutting down — not starting.")
        return

    if _scheduler and _scheduler.running:
        logger.info("[SCHED] Already running — skipping re-init.")
        return

    from services.alert_jobs import (
        run_daily_summary,
        run_overdue_alerts,
        run_low_stock_alerts,
        run_expiry_alerts,
        run_memory_distillation,
        run_books_integrity_audit,
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
        run_books_integrity_audit,
        CronTrigger(hour=3, minute=30),   # nightly, off-peak
        id="books_integrity_audit",
        name="Books Integrity Audit (hash chain + journal foots)",
        replace_existing=True,
        misfire_grace_time=3600,
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

    # Cloud parity audit — DELIBERATELY NOT part of the 15 s tick above.
    #
    # It performs a full `since=2020-01-01` cloud pull (180 s read timeout). Run
    # inline on the push tick, one slow parity starved every following tick under
    # `max_instances=1`, producing minutes of
    #   Execution of job "Hybrid Sync Engine" skipped: maximum number of running
    #   instances reached (1)
    # after every restart, with zero pushes or pulls happening for that whole
    # window. Its own job with its own `max_instances=1` means a slow parity now
    # delays only the next parity.
    #
    # 30 min cadence against a 6 h per-business internal rate limit: frequent
    # enough that a restart re-arms quickly, cheap enough that the extra sweeps
    # are pure no-ops.
    from services.sync_worker import run_cloud_parity_sweep
    _scheduler.add_job(
        run_cloud_parity_sweep,
        "interval",
        minutes=30,
        id="cloud_parity_sweep",
        name="Cloud Parity Audit",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    from services.log_uploader import run_daily_log_upload
    _scheduler.add_job(
        run_daily_log_upload,
        CronTrigger(hour=23, minute=30),
        id="daily_log_upload",
        name="Daily Diagnostic Log Upload",
        replace_existing=True,
        misfire_grace_time=3600,
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
        "telemetry DB maintenance @ Sunday 3:00 IST, "
        "hybrid sync every 15s, cloud parity audit every 30m."
    )


def stop_scheduler():
    """Stop the scheduler. Idempotent and never raises.

    Called from BOTH the FastAPI lifespan (orderly shutdown) and the atexit hook
    below (hard shutdown, e.g. a `--reload` child being terminated), so it has to
    tolerate being invoked twice, and to swallow anything the interpreter throws
    while it is already tearing itself down.
    """
    global _scheduler
    _SHUTTING_DOWN.set()
    sched = _scheduler
    if not sched:
        return
    try:
        if sched.running:
            # wait=False: never block shutdown on an in-flight job. A sync tick
            # is fully restartable — its work is queue-driven and idempotent.
            sched.shutdown(wait=False)
            # Instant Pull listener threads are daemons, so they would die with
            # the process anyway — but signalling them lets an in-flight SSE read
            # unwind instead of being killed mid-stream.
            try:
                from services import cloud_listener
                cloud_listener.stop_all()
            except Exception:
                pass
            logger.info("[SCHED] Stopped.")
    except Exception:
        # Logging can itself fail once the interpreter is far enough gone, so
        # this must stay silent rather than raise out of an atexit handler.
        pass
    finally:
        _scheduler = None


# Registered at IMPORT time, not inside start_scheduler(), so it is guaranteed
# to sit ABOVE `concurrent.futures.thread`'s hook in the LIFO atexit order.
atexit.register(stop_scheduler)


def get_scheduler() -> BackgroundScheduler:
    return _scheduler
