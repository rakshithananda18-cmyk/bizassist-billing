"""
app/timeutil.py — server time and the business calendar.
========================================================
Every field action is stamped with SERVER time. The phone's clock is accepted
only as evidence (stored next to it) because a phone clock can be changed by the
person whose punctuality it would prove.

Storage is naive UTC; the business date ("today's route", attendance day) is the
wall-clock date in BIZ_TIMEZONE.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app import config
from app.db import utc_now

BIZ_TZ = ZoneInfo(config.BIZ_TIMEZONE)


def biz_now(now_utc: datetime | None = None) -> datetime:
    """Aware datetime in the business timezone."""
    now_utc = now_utc or utc_now()
    return now_utc.replace(tzinfo=timezone.utc).astimezone(BIZ_TZ)


def biz_today(now_utc: datetime | None = None) -> str:
    return biz_now(now_utc).date().isoformat()


def parse_hhmm(value: str) -> time:
    hh, mm = (value or "").strip().split(":")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("time must be HH:MM")
    return time(h, m)


def biz_local_to_utc(day: str, hhmm: str) -> datetime:
    """Business-local `day` + `HH:MM` → naive UTC."""
    local = datetime.combine(date.fromisoformat(day), parse_hhmm(hhmm), tzinfo=BIZ_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None) -> str | None:
    """Serialise a stored naive-UTC datetime unambiguously (trailing Z)."""
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


def parse_client_time(value: str | None) -> datetime | None:
    """Best-effort parse of the phone's ISO timestamp → naive UTC. Never raises:
    a bad client clock is evidence, not an error."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def iso_weekday(day: str) -> int:
    """Monday=1 … Sunday=7."""
    return date.fromisoformat(day).isoweekday()


def day_bounds_utc(day: str) -> tuple[datetime, datetime]:
    """[start, end) of a business-local day, as naive UTC."""
    start_local = datetime.combine(date.fromisoformat(day), time(0, 0), tzinfo=BIZ_TZ)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )
