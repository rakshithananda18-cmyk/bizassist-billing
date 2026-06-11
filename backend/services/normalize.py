"""
services/normalize.py
=====================
Normalize messy upload values to canonical forms AT INGEST (H3), so the database
holds consistent data and downstream code doesn't have to second-guess formats.

- `to_iso()`   — any recognised date string → ISO `YYYY-MM-DD`. Unparseable input
                 is returned unchanged (never lose data).
- `normalize_status()` — fix the casing of the known invoice statuses so the
                 exact-match checks (`status == "Overdue"`) downstream are reliable.
                 Unknown statuses are passed through untouched.
"""
from services.dates import parse_date_only

# Canonical casing for the statuses the app reasons about. Conservative: we only
# fix case for these; anything else is left exactly as given.
_STATUS_CANON = {
    "paid":     "Paid",
    "pending":  "Pending",
    "overdue":  "Overdue",
    "disputed": "Disputed",
}


def to_iso(value):
    """Normalize a date to ISO 'YYYY-MM-DD'. Returns the original value if it
    can't be parsed (so non-date / unparseable cells aren't silently dropped)."""
    d = parse_date_only(value)
    return d.isoformat() if d else value


def normalize_status(value):
    """Canonical-case a known status; pass anything else through unchanged."""
    if value is None:
        return value
    s = str(value).strip()
    if not s:
        return value
    return _STATUS_CANON.get(s.lower(), s)
