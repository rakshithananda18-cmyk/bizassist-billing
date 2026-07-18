"""
services/ai_router_cache.py
===========================
Query-cache key construction split out of ai_router.py (MASTER_REVIEW §2.5).
Pure functions — no DB, no LLM. See _cache_salt for the discriminator rules.
"""
import hashlib
from datetime import date

def _safe_int(v) -> int:
    """Coerce a token count to int. Mock/None usage objects collapse to 0."""
    return int(v) if isinstance(v, (int, float)) else 0


def _cache_salt(user_id: int, route: str, user_query: str, topic: str,
                handler_key: str = None, *, is_writing: bool = False, day: str = None) -> str:
    """
    Build the query-cache key. The DISCRIMINATOR must match the *resolved intent*
    so two different intents never share a cache entry — otherwise a coarse
    `_detect_topic` collapses distinct questions onto one key (e.g. "how many
    invoices" and "total revenue" both detect topic 'total_revenue', which made
    "total revenue" return the cached invoice answer).

      - AI_COMPLEX / writing task → exact query (each is unique; a "draft a
        reminder" must not be served a cached data list)
      - DIRECT                    → the precise `handler_key`
      - else (AI_SIMPLE / intent) → the detected topic, so semantic variants of
        the same intent ("show overdue" == "who owes me") still share a hit

    The current DATE is folded in (C6) so day-sensitive answers refresh daily.
    """
    day = day or date.today().isoformat()
    disc = _cache_disc(route, user_query, topic, handler_key, is_writing)
    return hashlib.md5(f"{user_id}:{day}:{disc}".encode("utf-8")).hexdigest()


def _cache_disc(route: str, user_query: str, topic: str, handler_key, is_writing: bool) -> str:
    """The cache discriminator (the part that decides which answers share an entry)."""
    if route == "AI_COMPLEX" or is_writing:
        return f"q:{(user_query or '').strip().lower()}"
    if route == "DIRECT" and handler_key:
        # These are parameterised by the customer/ID named IN the query, so keying
        # on the handler alone would make every customer (or invoice) share one
        # entry. Key on the query so each distinct lookup runs its own handler.
        if handler_key in ("client_summary", "customer_invoices", "invoice_detail"):
            return f"q:{(user_query or '').strip().lower()}"
        return handler_key
    # AI_SIMPLE on the catch-all topic: `business_summary` is also `_detect_topic`'s
    # safe default, so unrelated fallback queries ("do yo know Rahul traders", "what
    # about my pricing") would all collide on it and serve each other's cached
    # answer. Too coarse to share — key on the query.
    if route == "AI_SIMPLE" and topic == "business_summary":
        return f"q:{(user_query or '').strip().lower()}"
    return topic

