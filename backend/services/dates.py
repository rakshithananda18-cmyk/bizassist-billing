"""
services/dates.py
=================
One date parser for the whole backend.

`invoice_date`, `due_date`, and `expiry_date` are stringly-typed columns written
from many upload formats, so the same 3-4-format `strptime` loop was copy-pasted
in a dozen places (H3). This is the single source of truth: every caller uses
`parse_date()` instead of its own loop.

Returns a naive `datetime` (most callers do date arithmetic like `(today - due)
.days` or `today <= exp <= soon`). Use `parse_date_only()` when you want a `date`.
"""
import os
from datetime import datetime, date, timezone, timedelta
from typing import Optional

_IST_OFFSET = timedelta(hours=5, minutes=30)

# Business wall-clock timezone. Timestamps are STORED naive-UTC, but the
# *business calendar date* stamped on invoices/receipts/journal entries must be
# the merchant's local date — otherwise a sale made at 01:00 IST lands on the
# previous day when the server runs in UTC. Env-tunable; defaults to IST (the
# scheduler and print layer already assume Asia/Kolkata).
try:
    from zoneinfo import ZoneInfo
    _BIZ_TZ = ZoneInfo(os.getenv("BIZ_TIMEZONE", "Asia/Kolkata"))
except Exception:                                    # pragma: no cover
    _BIZ_TZ = None

# Order matters for separator-ambiguous inputs: ISO first, then day-first
# (the dominant Indian format), then US month-first, then slashed-ISO.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
)


def parse_date(value) -> Optional[datetime]:
    """
    Parse a stringly-typed date in any of the app's known formats.

    Tolerates a trailing time component ("2026-01-01 00:00:00" / "...T...").
    Returns None for empty/None/unparseable input — never raises.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.split(" ")[0].split("T")[0]   # drop any time component
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse_date_only(value) -> Optional[date]:
    """Like parse_date() but returns a `date` (or None)."""
    dt = parse_date(value)
    return dt.date() if dt else None


def biz_now() -> datetime:
    """Aware 'now' in the business timezone (Asia/Kolkata by default).

    Use this — NOT `datetime.now()`/`datetime.today()` — whenever you need the
    merchant's wall-clock, so the result is correct no matter what timezone the
    server process runs in.
    """
    if _BIZ_TZ is not None:
        return datetime.now(_BIZ_TZ)
    # Fallback: explicit +05:30 so we never accidentally emit server-local time.
    return datetime.now(timezone(_IST_OFFSET))


def biz_today_str() -> str:
    """Today's business calendar date as 'YYYY-MM-DD' in the business timezone.

    The single source of truth for the default date stamped on invoices,
    payment receipts, and journal entries. Server-timezone-independent.
    """
    return biz_now().strftime("%Y-%m-%d")


def utc_now() -> datetime:
    """Naive UTC "now" — drop-in replacement for the deprecated `datetime.utcnow()`.

    Deliberately NAIVE: every stored timestamp and comparison in the app is
    naive-UTC (SQLite hands back naive datetimes; all column defaults are
    naive), so returning an aware datetime here would raise on the first
    aware-vs-naive comparison. This helper isolates the Python-3.12+
    deprecation in ONE place; the aware-everywhere migration is a schema
    project (MASTER_REVIEW §2.5), not a find-and-replace.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
