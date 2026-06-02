"""
context_cache.py
================
Layer 3 of the hybrid engine.

Caches the AI system context so it is NOT rebuilt on every
request. Cache is invalidated only when:

  1. A new file is uploaded       → call invalidate()
  2. A file is deleted            → call invalidate()
  3. TTL expires (default 10 min) → auto-refreshed

This is the fix for the Groq rate limit problem.
Before: every /ask rebuilt ~2000 tokens of context.
After:  context is built once and reused until data changes.
"""

import time
from threading import Lock
from sqlalchemy import func
from datetime import datetime, timedelta

from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment


# ── Cache store ─────────────────────────────────────────────────────

_cache: dict = {}  # user_id -> { "context": str, "built_at": float }
_query_response_cache: dict = {}  # user_id -> { q_hash: { "response": dict, "cached_at": float } }

_lock = Lock()

# How long (seconds) before cache auto-refreshes even without a change
CACHE_TTL = 600   # 10 minutes


# ── Public API ──────────────────────────────────────────────────────

def invalidate():
    """
    Call this whenever the DB changes (upload, delete).
    Forces contexts and cached queries to be rebuilt.
    """
    with _lock:
        _cache.clear()
        _query_response_cache.clear()


def get_context(user_id: int) -> str:
    """
    Returns cached context string, rebuilding only if stale.
    Thread-safe.
    """
    with _lock:
        now = time.time()
        if user_id not in _cache:
            _cache[user_id] = {"context": None, "built_at": 0}
        
        user_cache = _cache[user_id]
        age = now - user_cache["built_at"]
        is_stale = (user_cache["context"] is None) or (age > CACHE_TTL)

        if is_stale:
            user_cache["context"]  = _build_context(user_id)
            user_cache["built_at"] = now

        return user_cache["context"]


def get_cached_query_response(user_id: int, query: str) -> dict:
    """
    Retrieves a cached AI response for the user + query if valid.
    """
    import hashlib
    q_hash = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
    with _lock:
        user_responses = _query_response_cache.get(user_id)
        if not user_responses or q_hash not in user_responses:
            return None
        
        entry = user_responses[q_hash]
        if time.time() - entry["cached_at"] > CACHE_TTL:
            del user_responses[q_hash]
            return None
        
        return entry["response"]


def set_cached_query_response(user_id: int, query: str, response: dict):
    """
    Caches an AI response for a user query.
    """
    import hashlib
    q_hash = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
    with _lock:
        if user_id not in _query_response_cache:
            _query_response_cache[user_id] = {}
        _query_response_cache[user_id][q_hash] = {
            "response": response,
            "cached_at": time.time()
        }


def get_focused_context(query: str, user_id: int) -> str:
    """
    Returns base summary context + focused extra data
    for the specific query topic. This keeps token count
    low while still giving the AI what it needs.
    """
    base  = get_context(user_id)
    extra = _get_focused_extra(query, user_id)
    return base + extra if extra else base


# ── Context builder ─────────────────────────────────────────────────

def _build_context(user_id: int) -> str:
    """
    Queries DB and builds a compact but complete business
    summary. Designed to stay under 800 tokens.
    """
    db    = SessionLocal()
    lines = ["=== BIZASSIST BUSINESS DATA ===\n"]

    try:

        # --- Invoice summary (aggregates only, no raw rows) ---
        total_inv  = db.query(Invoice).filter(Invoice.business_id == user_id).count()
        total_rev  = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        paid_amt   = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar()    or 0
        pending_ct = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        pending_amt= db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Pending").scalar() or 0
        overdue_ct = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").count()
        overdue_amt= db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0

        lines.append("INVOICES:")
        lines.append(f"  Total={total_inv} | Revenue=₹{total_rev:,.0f}")
        lines.append(f"  Paid=₹{paid_amt:,.0f} | Pending({pending_ct})=₹{pending_amt:,.0f} | Overdue({overdue_ct})=₹{overdue_amt:,.0f}")

        # --- Top 5 customers (compact) ---
        top = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("t")
            )
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(5).all()
        )
        if top:
            lines.append("\nTOP CUSTOMERS:")
            for i, c in enumerate(top, 1):
                lines.append(f"  {i}. {c.customer} ₹{c.t:,.0f}")

        # --- Inventory summary ---
        inv_count = db.query(Inventory).filter(Inventory.business_id == user_id).count()
        today     = datetime.today()
        soon      = today + timedelta(days=30)

        expiring_ct = 0
        low_stock_ct = 0
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()

        for item in items:
            if item.stock is not None:
                try:
                    if int(item.stock) <= 10:
                        low_stock_ct += 1
                except (ValueError, TypeError):
                    pass
            if item.expiry_date:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        exp = datetime.strptime(str(item.expiry_date), fmt)
                        if today <= exp <= soon:
                            expiring_ct += 1
                        break
                    except ValueError:
                        continue

        lines.append(f"\nINVENTORY: Total={inv_count} | Expiring30d={expiring_ct} | LowStock={low_stock_ct}")

        # --- Overdue list (compact, top 10 only) ---
        overdue_rows = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .order_by(Invoice.amount.desc())
            .limit(10).all()
        )
        if overdue_rows:
            lines.append("\nOVERDUE (top 10):")
            for r in overdue_rows:
                lines.append(f"  {r.customer} ₹{r.amount:,.0f}{f' due:{r.due_date}' if r.due_date else ''}")

        lines.append("\n=== END ===")
        return "\n".join(lines)

    except Exception as e:
        return f"[Context build error: {e}]"

    finally:
        db.close()


def _get_focused_extra(query: str, user_id: int) -> str:
    """
    Adds targeted extra rows only for specific query topics.
    Keeps tokens lean — only fetches what the question needs.
    """
    q  = query.lower()
    db = SessionLocal()

    try:
        extra = []

        # Full inventory detail for stock/expiry questions
        if any(kw in q for kw in ["expir", "stock", "medicine", "product", "inventory", "reorder"]):
            items = db.query(Inventory).filter(Inventory.business_id == user_id).order_by(Inventory.expiry_date).limit(30).all()
            if items:
                extra.append("\nINVENTORY DETAIL:")
                for i in items:
                    extra.append(
                        f"  {i.product_name} | stock:{i.stock} | expiry:{i.expiry_date}"
                        f"{f' | supplier:{i.supplier}' if i.supplier else ''}"
                    )

        # More invoice rows for customer/payment questions
        if any(kw in q for kw in ["invoice", "customer", "client", "who owes", "payment", "due"]):
            rows = (
                db.query(Invoice)
                .filter(Invoice.business_id == user_id)
                .order_by(Invoice.amount.desc())
                .limit(25).all()
            )
            if rows:
                extra.append("\nINVOICE DETAIL (top 25):")
                for r in rows:
                    extra.append(
                        f"  {r.customer} | ₹{r.amount:,.0f} | {r.status}"
                        f"{f' | due:{r.due_date}' if r.due_date else ''}"
                    )

        return "\n".join(extra)

    except Exception:
        return ""

    finally:
        db.close()