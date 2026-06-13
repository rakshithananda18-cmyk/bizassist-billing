"""
services/intent_router.py  — Phase 1 (semantic routing)
=======================================================
An embedding-based replacement for the brittle regex `query_router` + keyword
`_detect_topic`. Instead of enumerating phrasings, we embed a handful of seed
examples per intent (with the already-loaded local MiniLM model) and classify a
query by its nearest example in vector space.

    classify("overdues people only top 15")  -> ("DIRECT", "overdue_list", 0.71)
    classify("draft a payment reminder")      -> ("AI_SIMPLE", None, 0.55)
    classify("why is my collection rate low")  -> ("AI_COMPLEX", None, 0.63)
    classify("hi there")                       -> ("CONVERSATIONAL", None, 0.80)

Notes
-----
* The model only classifies the *type* of request. Entities (customer names) are
  still resolved against the DB by the handlers — the model never invents them.
* Below a confidence threshold we fall back to AI_SIMPLE (the safe, cheap tier),
  exactly like the regex router's default.
* The encoder and the seed set are injectable so the mechanics are unit-testable
  without loading the embedding model.

This module is intentionally NOT wired into the request path yet (Phase 1 Step 1).
"""
import logging
from typing import Callable, Optional, Tuple, Dict, List

import numpy as np

logger = logging.getLogger("bizassist.intent_router")

# Below this cosine similarity, we don't trust the match → AI_SIMPLE fallback.
CONFIDENCE_THRESHOLD = 0.45

# label -> (tier, intent_key). DB-backed intents carry their handler key; the
# three buckets carry None (the tier alone decides routing).
_LABEL_TIER: Dict[str, Tuple[str, Optional[str]]] = {
    "invoice_count":        ("DIRECT", "invoice_count"),
    "total_revenue":        ("DIRECT", "total_revenue"),
    "revenue_month_detail": ("DIRECT", "revenue_month_detail"),
    "overdue_list":         ("DIRECT", "overdue_list"),
    "overdue_amount":       ("DIRECT", "overdue_amount"),
    "overdue_range_detail": ("DIRECT", "overdue_range_detail"),
    "pending_list":         ("DIRECT", "pending_list"),
    "top_customers":        ("DIRECT", "top_customers"),
    "top_debtors":          ("DIRECT", "top_debtors"),
    "inventory_count":      ("DIRECT", "inventory_count"),
    "low_stock":            ("DIRECT", "low_stock"),
    "expiring_soon":        ("DIRECT", "expiring_soon"),
    "client_summary":       ("DIRECT", "client_summary"),
    "customer_invoices":    ("DIRECT", "customer_invoices"),
    "invoice_detail":       ("DIRECT", "invoice_detail"),
    "product_performance":  ("DIRECT", "product_performance"),
    "profit_summary":       ("DIRECT", "profit_summary"),
    "sales_growth":         ("DIRECT", "sales_growth"),
    "dso_summary":          ("DIRECT", "dso_summary"),
    "dormant_customers":    ("DIRECT", "dormant_customers"),
    "customer_margins":     ("DIRECT", "customer_margins"),
    "business_summary":     ("DIRECT", "business_summary"),
    "conversational":       ("CONVERSATIONAL", None),
    "ai_simple":            ("AI_SIMPLE", None),
    "ai_complex":           ("AI_COMPLEX", None),
}

# 8–12 seed phrases per label. Add a new intent by adding a label here + in
# _LABEL_TIER — no code change. New phrasings are handled by similarity, not rules.
_SEED: Dict[str, List[str]] = {
    "invoice_count": [
        "how many invoices do I have", "invoice count", "total invoices",
        "number of invoices", "count of invoices", "how many bills",
        "what is my total invoice count", "how many client invoices exist",
        "how many bills in database",
    ],
    "total_revenue": [
        "total revenue", "what is my total revenue", "total sales",
        "how much revenue", "revenue so far", "total turnover",
        "how much have I earned", "what's my income", "total revenue this year",
        "how much money did we make", "what were my total sales this period",
    ],
    "revenue_month_detail": [
        "revenue in March 2026", "sales for January", "income in Feb",
        "how much did we sell in December 2025", "revenue month-wise for October",
        "sales overview for April",
    ],
    "overdue_list": [
        "show overdue invoices", "who hasn't paid me", "who owes me money",
        "list overdue customers", "outstanding payments", "show me my debtors",
        "what's overdue", "customers who still owe me", "unpaid overdue accounts",
        "what's my collection situation", "show me everyone who is behind on payments",
        "which clients still haven't cleared their dues", "who is overdue",
        "list overdue", "overdue people only top 15", "what's outstanding from clients",
        "outstanding from clients",
    ],
    "overdue_amount": [
        "how much is overdue", "total overdue amount", "total outstanding amount",
        "how much money is overdue", "value of overdue invoices",
        "what's the total value of unpaid overdue bills",
        "what is the total amount overdue", "how much money is outstanding",
    ],
    "overdue_range_detail": [
        "overdue in range 30-60 days", "outstanding invoices 90+ days",
        "overdue payments 61-90 days", "bills overdue for more than 90 days",
        "list overdue invoices older than 60 days",
    ],
    "pending_list": [
        "show pending invoices", "list pending payments", "unpaid invoices",
        "what's pending", "invoices not yet paid", "awaiting payment",
        "list the invoices still awaiting payment", "pending payment",
        "not paid", "unpaid invoices list",
    ],
    "top_customers": [
        "top customers", "best customers", "highest paying customers",
        "biggest buyers", "who are my biggest customers", "most valuable clients",
        "who spends the most with me", "customers by purchase volume",
        "my biggest spenders", "who purchases the most", "who buys the most from me",
    ],
    "top_debtors": [
        "top debtors", "who owes me the most", "biggest debtor",
        "largest outstanding customer", "worst paying customers",
        "which customer has the largest unpaid balance", "who owes the most money",
    ],
    "inventory_count": [
        "how many products", "inventory count", "stock count",
        "number of items in stock", "how many SKUs", "total products",
        "how many distinct products do I stock", "how many items in inventory",
    ],
    "low_stock": [
        "low stock items", "what's running low", "out of stock",
        "items to reorder", "which products are almost out", "what should I restock",
        "what items do I need to restock", "low stock",
    ],
    "expiring_soon": [
        "expiring products", "items about to expire", "what's expiring soon",
        "near expiry stock", "products expiring this month", "stock close to expiry",
        "which goods will expire shortly", "expiring soon",
    ],
    "business_summary": [
        "business summary", "give me an overview", "dashboard snapshot",
        "how's my business doing", "business health", "quick snapshot of my business",
        "is my business doing well", "business health check",
        "how is the business performing overall", "give me the key numbers at a glance",
        "give me a quick health check of the business",
    ],
    "client_summary": [
        "tell me about this customer", "do you know this client",
        "details about a customer", "customer profile", "what's the status of a client",
        "info on a buyer",
        # Name-bearing lookups. Real queries carry a proper noun ("do you know
        # srinivas kirana") whose embedding sits far from the name-less phrasings
        # above — so these anchor the "look up a NAMED account" shape and lift
        # real customer lookups above the confidence threshold.
        "do you know Rajesh Traders", "tell me about Sharma Stores",
        "info on Patel Kirana", "what's the status of Krishna Enterprises",
        "details of Anand Provisions", "how is Gupta Trading doing",
        "do you know about Reddy Wholesale", "give me a summary for Mehta Mart",
        "tell me about Nilgiris Fresh",
    ],
    "customer_invoices": [
        "invoices for Nilgiris Fresh", "bills of Daily Needs Store",
        "show me all invoices of Big Basket Retail", "list invoices for Lakshmi General Store",
        "invoices outstanding for Srinivas Kirana",
    ],
    "invoice_detail": [
        "invoice details for INV-0002", "tell me about INV-0007",
        "details of bill INV-0138", "status of invoice INV-0415",
        "lookup invoice INV-0343", "give details about this invoice",
        "invoice ID details",
    ],
    "product_performance": [
        "best selling products", "worst selling products", "product performance",
        "fast moving items", "slow moving goods", "what sells best",
        "sales by product", "best and worst selling products",
    ],
    "profit_summary": [
        "profit margin", "gross profit", "profitability overview",
        "what is my profit", "show my margins", "profit summary",
    ],
    "sales_growth": [
        "sales growth rate", "revenue growth", "YoY growth",
        "growing products", "how fast is sales growing", "month over month growth",
    ],
    "dso_summary": [
        "days sales outstanding", "DSO summary", "collection period",
        "how long to collect payments", "average payment time",
    ],
    "dormant_customers": [
        "dormant customers", "inactive clients", "lapsed accounts",
        "customers who stopped buying", "win back customers",
    ],
    "customer_margins": [
        "customer profitability", "margins by customer", "most profitable clients",
        "customer gross margins", "which customer makes the most profit",
    ],
    "conversational": [
        "hi", "hello", "hey there", "thanks", "thank you", "okay got it",
        "great", "cool", "bye", "sounds good", "noted", "perfect",
        "thanks a lot", "hey", "okay",
    ],
    "ai_simple": [
        "draft a payment reminder message", "write a message to a customer",
        "which customer should I call first", "explain my cash flow situation",
        "what payment terms should I offer", "help me write a follow-up email",
        "compose a thank you note to a client", "write a polite reminder to a late payer",
        "help me phrase a follow up to a client", "who is my most reliable supplier?",
    ],
    "ai_complex": [
        "analyse my business and give me a recovery plan",
        "why is my collection rate low and how do I fix it",
        "give me a recovery strategy for overdue accounts",
        "compare my revenue trends and give insights",
        "what should I do to improve my profitability",
        "what are the root causes of my overdue problem",
        "create a 30 day collection plan",
        "do a deep dive analysis of my business with recommendations",
        "diagnose my cash flow problems and recommend fixes",
        "what is causing my poor collections and how do I fix it",
        "figure out why money is tight and suggest a plan",
        "diagnose why my cash flow is tight and suggest fixes",
        "build me a plan to recover overdue money over the next month",
        "what should I focus on today",
    ],
}


def _l2_normalize(m: np.ndarray) -> np.ndarray:
    """Row-normalize so a dot product equals cosine similarity."""
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class SemanticRouter:
    """Nearest-seed-example classifier over sentence embeddings (vectorized)."""

    def __init__(self, encode: Optional[Callable[[str], List[float]]] = None,
                 seed: Optional[Dict[str, List[str]]] = None,
                 threshold: float = CONFIDENCE_THRESHOLD,
                 margin_threshold: float = 0.05):
        self._encode_override = encode
        self._seed = seed if seed is not None else _SEED
        self._threshold = threshold
        self._margin_threshold = margin_threshold
        self._matrix: Optional[np.ndarray] = None   # (N, D) row-normalized seed embeddings
        self._labels: List[str] = []                # length-N label per row

    def _encoder(self) -> Callable[[str], List[float]]:
        if self._encode_override is not None:
            return self._encode_override
        from services.embeddings import generate_embedding
        return generate_embedding

    def _ensure_examples(self) -> None:
        if self._matrix is None:
            enc = self._encoder()
            labels, vecs = [], []
            for label, phrases in self._seed.items():
                for phrase in phrases:
                    labels.append(label)
                    vecs.append(enc(phrase))
            self._matrix = _l2_normalize(np.asarray(vecs, dtype=float))
            self._labels = labels
            logger.info(f"[ROUTER] Semantic router warm — {len(labels)} seed examples")

    def classify(self, query: str) -> Tuple[str, Optional[str], float]:
        """Return (tier, intent_key, confidence). Empty/low-confidence → AI_SIMPLE."""
        q = (query or "").strip()
        if not q:
            return ("AI_SIMPLE", None, 0.0)

        self._ensure_examples()
        qv = np.asarray(self._encoder()(q), dtype=float)
        nq = np.linalg.norm(qv)
        if nq == 0:
            return ("AI_SIMPLE", None, 0.0)

        # One matrix-vector product = cosine against every seed at once.
        sims = self._matrix @ (qv / nq)
        idx = int(np.argmax(sims))
        best_sim = float(sims[idx])
        best_label = self._labels[idx]

        if best_sim < self._threshold:
            logger.info(f"[ROUTER] low-confidence ({best_sim:.2f}) → AI_SIMPLE: '{q}'")
            return ("AI_SIMPLE", None, best_sim)

        # Margin check: find max similarity for any label OTHER than best_label
        other_sims = [sims[i] for i in range(len(sims)) if self._labels[i] != best_label]
        second_best_sim = float(max(other_sims)) if other_sims else 0.0
        margin = best_sim - second_best_sim

        if margin < self._margin_threshold:
            logger.info(f"[ROUTER] ambiguous match (margin {margin:.2f} < {self._margin_threshold:.2f}, "
                        f"best {best_label} {best_sim:.2f}, second best {second_best_sim:.2f}) → AI_SIMPLE: '{q}'")
            return ("AI_SIMPLE", None, best_sim)

        tier, intent_key = _LABEL_TIER[best_label]
        logger.info(f"[ROUTER] {tier} ({best_label}, {best_sim:.2f}): '{q}'")
        return (tier, intent_key, best_sim)


_router: Optional[SemanticRouter] = None


def get_router() -> SemanticRouter:
    global _router
    if _router is None:
        _router = SemanticRouter()
    return _router


def classify(query: str) -> Tuple[str, Optional[str], float]:
    """Module-level convenience over the shared singleton router."""
    return get_router().classify(query)
