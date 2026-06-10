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
import logging
from collections import OrderedDict
from threading import Lock
from sqlalchemy import func
from datetime import datetime, timedelta

from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment
from services.dates import parse_date

logger = logging.getLogger("bizassist.context_cache")


# ── Cache store ─────────────────────────────────────────────────────
# LRU-bounded so memory can't grow without limit (C5). Both caches are keyed
# by user_id; the query cache holds a bounded OrderedDict of responses per user.

_cache: "OrderedDict[int, dict]" = OrderedDict()            # user_id -> { "context": str, "built_at": float }
_query_response_cache: "OrderedDict[int, OrderedDict]" = OrderedDict()  # user_id -> { q_hash: { "response", "cached_at" } }

_lock = Lock()

# How long (seconds) before cache auto-refreshes even without a change
CACHE_TTL = 600   # 10 minutes

# LRU capacity bounds (evict least-recently-used when exceeded)
MAX_CACHE_USERS       = 500   # distinct users held in each cache
MAX_QUERIES_PER_USER  = 200   # cached responses retained per user


def _evict_lru(store: "OrderedDict", cap: int) -> None:
    """Drop oldest entries until `store` is within `cap`. Caller holds _lock."""
    while len(store) > cap:
        store.popitem(last=False)


# ── Public API ──────────────────────────────────────────────────────

def invalidate():
    """
    Call this whenever the DB changes (upload, delete).
    Forces contexts and cached queries to be rebuilt.
    """
    with _lock:
        _cache.clear()
        _query_response_cache.clear()
    logger.info("[CACHE] Global cache invalidated (all users).")


def invalidate_user_cache(user_id: int):
    """
    Forces the cache for a specific user to be cleared/rebuilt.
    """
    with _lock:
        if user_id in _cache:
            del _cache[user_id]
        if user_id in _query_response_cache:
            del _query_response_cache[user_id]
    logger.info(f"[CACHE] Cache invalidated for user {user_id}.")


def get_cache_stats() -> dict:
    """
    Returns metrics on the current caches (contexts and queries) for visualization.
    """
    with _lock:
        context_stats = []
        for user_id, entry in _cache.items():
            context_stats.append({
                "user_id": user_id,
                "built_at": entry["built_at"],
                "size_chars": len(entry["context"]) if entry["context"] else 0
            })
            
        query_stats = []
        for user_id, responses in _query_response_cache.items():
            query_stats.append({
                "user_id": user_id,
                "query_count": len(responses)
            })
            
        return {
            "context_cache": context_stats,
            "query_cache": query_stats
        }


def get_context(user_id: int) -> str:
    """
    Returns cached context string, rebuilding only if stale.
    Thread-safe.
    """
    with _lock:
        now = time.time()
        if user_id not in _cache:
            _cache[user_id] = {"context": None, "built_at": 0}
        _cache.move_to_end(user_id)          # LRU: most-recently-used
        _evict_lru(_cache, MAX_CACHE_USERS)

        user_cache = _cache[user_id]
        age = now - user_cache["built_at"]
        is_stale = (user_cache["context"] is None) or (age > CACHE_TTL)

        if is_stale:
            logger.info(f"[CACHE] Cache miss / stale for user {user_id}. Rebuilding context...")
            user_cache["context"]  = _build_context(user_id)
            user_cache["built_at"] = now
        else:
            logger.debug(f"[CACHE] Cache hit for user {user_id} (age={age:.1f}s).")

        return user_cache["context"]


def get_cached_query_response(user_id: int, query: str, history_salt: str = "") -> dict:
    """
    Retrieves a cached AI response. Cache key is history_salt only.
    For AI_SIMPLE: salt = MD5(user_id+topic)  → topic-level hit (intent variants match)
    For AI_COMPLEX: salt = MD5(user_id+query) → exact query match
    """
    import hashlib
    # Use salt alone — query text already encoded in salt for AI_COMPLEX,
    # and omitting it here lets AI_SIMPLE hit cache across semantic variants.
    q_hash = hashlib.md5(history_salt.encode("utf-8")).hexdigest() if history_salt else hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
    with _lock:
        user_responses = _query_response_cache.get(user_id)
        if not user_responses or q_hash not in user_responses:
            return None

        entry = user_responses[q_hash]
        if time.time() - entry["cached_at"] > CACHE_TTL:
            del user_responses[q_hash]
            return None

        # LRU: mark this user and this query as most-recently-used
        _query_response_cache.move_to_end(user_id)
        user_responses.move_to_end(q_hash)
        return entry["response"]


def set_cached_query_response(user_id: int, query: str, response: dict, history_salt: str = ""):
    """
    Caches an AI response. Key matches get_cached_query_response.
    """
    import hashlib
    q_hash = hashlib.md5(history_salt.encode("utf-8")).hexdigest() if history_salt else hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
    with _lock:
        if user_id not in _query_response_cache:
            _query_response_cache[user_id] = OrderedDict()
        user_responses = _query_response_cache[user_id]
        user_responses[q_hash] = {
            "response": response,
            "cached_at": time.time()
        }
        # LRU bookkeeping: newest user/query to the end, then trim to bounds
        user_responses.move_to_end(q_hash)
        _query_response_cache.move_to_end(user_id)
        _evict_lru(user_responses, MAX_QUERIES_PER_USER)
        _evict_lru(_query_response_cache, MAX_CACHE_USERS)


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
                func.sum(Invoice.amount).label("total_amount")
            )
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(5).all()
        )
        if top:
            lines.append("\nTOP CUSTOMERS:")
            for i, c in enumerate(top, 1):
                lines.append(f"  {i}. {c.customer} ₹{c.total_amount:,.0f}")

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
            exp = parse_date(item.expiry_date)
            if exp is not None and today <= exp <= soon:
                expiring_ct += 1

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
        context_str = "\n".join(lines)
        logger.info(f"[CACHE] Context built for user {user_id} ({len(context_str)} chars).")
        return context_str

    except Exception as e:
        logger.error(f"[CACHE] Failed to build context for user {user_id}: {e}", exc_info=True)
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