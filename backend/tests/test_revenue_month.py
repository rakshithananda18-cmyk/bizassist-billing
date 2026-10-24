"""
tests/test_revenue_month.py — "how much did I sell this month?" gets an answer
==============================================================================
The monthly revenue lookup (services/handlers/invoices.py) read only the exact
text 'revenue in <Mon> <YY>' and ignored the LLM router's `month` entity, so
every other phrasing the routers send it answered "Invalid monthly revenue
query." - including "How much did I sell this month?" on the live web app
(2026-10-24), and the keyword router's own examples ("sales for January",
"how much did we sell in December 2025").

Now the question's words decide (this/last month, a month name with or
without a year, 2026-10, 10/2026) and the router's month is the fallback.
"""
import datetime as dt
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import services.handlers.invoices as inv

TODAY = dt.datetime(2026, 10, 24, 21, 30)          # a Saturday, India time


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(inv, "biz_now", lambda: TODAY)


@pytest.mark.parametrize("question, expected", [
    # what failed live, and the keyword router's own examples for this lookup
    ("How much did I sell this month?",            (2026, 10)),
    ("sales last month",                           (2026, 9)),
    ("revenue for the previous month",             (2026, 9)),
    ("month to date sales",                        (2026, 10)),
    ("sales for January",                          (2026, 1)),
    ("income in Feb",                              (2026, 2)),
    ("how much did we sell in December 2025",      (2025, 12)),
    ("revenue month-wise for October",             (2026, 10)),
    ("sales overview for April",                   (2026, 4)),
    ("sales overview for November",                (2025, 11)),   # not started yet this year -> last year's
    # the dashboard's own phrasing keeps working
    ("Tell me about revenue in Oct 2025",          (2025, 10)),
    ("Tell me about revenue in Apr 26",            (2026, 4)),
    ("revenue in Sept 2026",                       (2026, 9)),
    ("Dec'25 revenue",                             (2025, 12)),
    # numbers
    ("revenue in 2026-03",                         (2026, 3)),
    ("sales 03/2026",                              (2026, 3)),
    # May the month, may the verb
    ("revenue for May",                            (2026, 5)),
    ("May 2026 sales",                             (2026, 5)),
    ("may I know my revenue",                      None),
    # words that merely contain a month's letters
    ("market revenue",                             None),
    ("decrease in sales",                          None),
])
def test_the_month_a_question_asks_about(question, expected):
    assert inv._resolve_month(question) == expected


def test_last_month_crosses_the_year():
    assert inv._resolve_month("sales last month", today=dt.datetime(2026, 1, 5)) == (2025, 12)


def test_the_routers_month_is_the_fallback():
    assert inv._resolve_month("show me that month's revenue", month="2026-07") == (2026, 7)
    assert inv._resolve_month("show me that month's revenue", month="2026-13") is None
    assert inv._resolve_month("show me that month's revenue", month="Oct") is None


def test_the_words_beat_the_routers_month():
    """The live bug: the router, not knowing the date, sent 2024-05 for 'this month'."""
    assert inv._resolve_month("How much did I sell this month?", month="2024-05") == (2026, 10)
    assert inv._resolve_month("revenue in Oct 2025", month="2026-01") == (2025, 10)


# ── against the database ────────────────────────────────────────────────────

@pytest.fixture
def shop():
    """A business with invoices in October and September 2026, in the date
    shapes billing stores."""
    from database.db import SessionLocal
    from database.models import Invoice
    bid = 900000 + uuid.uuid4().int % 90000
    rows = [("2026-10-03", 1000), ("2026-10-24T11:00:00", 250), ("15/10/2026", 500),
            ("2026-09-30", 4000), ("12-09-2026", 600), ("2025-10-10", 99999)]
    with SessionLocal() as db:
        for i, (date, amount) in enumerate(rows):
            db.add(Invoice(business_id=bid, invoice_id=f"RM-{bid}-{i}", customer="Sri Lakshmi Medicals",
                           amount=amount, status="Paid", invoice_date=date))
        db.commit()
    return bid


def test_this_month_on_real_rows(shop):
    out = inv._revenue_month_detail(shop, "How much did I sell this month?")
    assert "**Revenue in Oct 2026**" in out
    assert "₹1,750" in out and "**3 invoices**" in out, out


def test_last_month_on_real_rows(shop):
    out = inv._revenue_month_detail(shop, "sales last month")
    assert "Sep 2026" in out and "₹4,600" in out and "**2 invoices**" in out, out


def test_the_dashboard_phrasing_on_real_rows(shop):
    out = inv._revenue_month_detail(shop, "Tell me about revenue in Oct 25")
    assert "Oct 2025" in out and "₹99,999" in out, out


def test_no_month_asks_which_instead_of_invalid(shop):
    out = inv._revenue_month_detail(shop, "how is my revenue")
    assert "Which month?" in out and "Invalid" not in out


def test_the_dispatcher_hands_over_the_routers_month(shop):
    from services.direct_query_handler import handle
    out = handle("revenue_month_detail", "show me revenue for that month", shop, params={"month": "2026-09"})
    assert "Sep 2026" in out and "₹4,600" in out, out
