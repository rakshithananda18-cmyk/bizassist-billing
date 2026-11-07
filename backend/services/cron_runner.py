"""Lease scheduled work durably so scale-to-zero does not lose daily jobs."""
import contextvars
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from database.db import SessionLocal
from database.runtime_state import ScheduledJobRun
from services import alert_jobs
from services.telemetry_relay import run_telemetry_retention
from services.telemetry_maintenance import run_telemetry_db_maintenance

JOBS = {
    "daily_summary": (alert_jobs.run_daily_summary, "daily"),
    "overdue_alerts": (alert_jobs.run_overdue_alerts, "daily"),
    "low_stock_alerts": (alert_jobs.run_low_stock_alerts, "daily"),
    "expiry_alerts": (alert_jobs.run_expiry_alerts, "daily"),
    "books_integrity_audit": (alert_jobs.run_books_integrity_audit, "daily"),
    "telemetry_retention": (run_telemetry_retention, "daily"),
    "memory_distillation": (alert_jobs.run_memory_distillation, "weekly"),
    "telemetry_db_maintenance": (run_telemetry_db_maintenance, "weekly"),
}
checkpoint = contextvars.ContextVar("cron_checkpoint", default=None)


def period_for(job, now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Kolkata"))
    if JOBS[job][1] == "weekly":
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02d}"
    return local.date().isoformat()


def run(job, period, budget_s=95):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lease = now + timedelta(seconds=budget_s + 30)
    db = SessionLocal()
    try:
        try:
            db.add(ScheduledJobRun(job=job, period=period, status="running", lease_until=lease, started_at=now))
            db.commit()
            cursor = None
        except IntegrityError:
            db.rollback()
            row = db.get(ScheduledJobRun, (job, period))
            if row.status == "done":
                return "already_ran"
            cursor = row.cursor
            changed = db.query(ScheduledJobRun).filter(
                ScheduledJobRun.job == job, ScheduledJobRun.period == period,
                ScheduledJobRun.status != "done",
                or_(ScheduledJobRun.lease_until.is_(None), ScheduledJobRun.lease_until <= now),
            ).update({"status":"running", "lease_until":lease, "error":None}, synchronize_session=False)
            db.commit()
            if not changed:
                return "busy"
            cursor = db.get(ScheduledJobRun, (job, period)).cursor

        def save_cursor(value):
            changed = db.query(ScheduledJobRun).filter_by(job=job, period=period, status="running", lease_until=lease).update({"cursor":value}, synchronize_session=False)
            db.commit()
            if changed != 1:
                raise RuntimeError("Scheduled-job lease lost")

        context = checkpoint.set(save_cursor)
        try:
            cursor = JOBS[job][0](after_business_id=cursor, deadline=time.monotonic() + budget_s)
            status = "partial" if cursor is not None else "done"
            changed = db.query(ScheduledJobRun).filter_by(job=job, period=period, status="running", lease_until=lease).update(
                {"status":status,"cursor":cursor,"lease_until":None,"finished_at":datetime.now(timezone.utc).replace(tzinfo=None) if status == "done" else None}, synchronize_session=False)
            db.commit()
            if changed != 1:
                raise RuntimeError("Scheduled-job lease lost")
            return status
        except Exception as exc:
            db.rollback()
            db.query(ScheduledJobRun).filter_by(job=job, period=period, status="running", lease_until=lease).update(
                {"status":"partial","lease_until":None,"error":type(exc).__name__}, synchronize_session=False)
            db.commit()
            raise
        finally:
            checkpoint.reset(context)
    finally:
        db.close()
