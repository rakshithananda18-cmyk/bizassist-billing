"""
services/tools/ package
========================
Exposes: execute_tool, schemas, query_semantic_index
"""
import json
import logging

from ._utils import safe_int
from .invoices import (
    get_invoice_summary, get_invoice_list, get_top_customers, get_top_debtors,
    get_overdue_aging_summary, get_revenue_trend, get_product_performance,
    get_product_margins, get_sales_growth, get_dso, get_dormant_customers,
    get_customer_margins, SCHEMAS as _INV,
)
from .inventory import get_inventory_status, SCHEMAS as _STOCK
from .payments import get_payment_list, SCHEMAS as _PAY
from .business import get_business_overview, SCHEMAS as _BIZ
from .search import search_exact_keywords, query_semantic_index, SCHEMAS as _SEARCH

logger = logging.getLogger("bizassist.tools")

schemas = [*_INV, *_STOCK, *_PAY, *_BIZ, *_SEARCH]

_TOOL_MAP = {
    "summarize_invoices":       lambda u, a: get_invoice_summary(u),
    "list_invoices":            lambda u, a: get_invoice_list(u, a.get("status"), a.get("customer"), safe_int(a.get("limit"), 15)),
    "rank_top_customers":       lambda u, a: get_top_customers(u, safe_int(a.get("limit"), 5)),
    "rank_top_debtors":         lambda u, a: get_top_debtors(u, safe_int(a.get("limit"), 5)),
    "overdue_aging_summary":    lambda u, a: get_overdue_aging_summary(u),
    "revenue_trend":            lambda u, a: get_revenue_trend(u, safe_int(a.get("months"), 12)),
    "product_performance":      lambda u, a: get_product_performance(u, safe_int(a.get("limit"), 10)),
    "product_margins":          lambda u, a: get_product_margins(u, safe_int(a.get("limit"), 10)),
    "sales_growth":             lambda u, a: get_sales_growth(u),
    "dso":                      lambda u, a: get_dso(u),
    "dormant_customers":        lambda u, a: get_dormant_customers(u, safe_int(a.get("days"), 90)),
    "customer_margins":         lambda u, a: get_customer_margins(u),
    "check_inventory_stock": lambda u, a: get_inventory_status(u, safe_int(a.get("filter_stock_under")), safe_int(a.get("filter_expiry_days"))),
    "list_payment_records":  lambda u, a: get_payment_list(u, a.get("paid_status"), a.get("customer"), safe_int(a.get("limit"), 15)),
    "view_business_metrics": lambda u, a: get_business_overview(u),
    "search_exact_keywords": lambda u, a: search_exact_keywords(u, a.get("query")),
    "query_semantic_index":  lambda u, a: query_semantic_index(u, a.get("query"), a.get("limit")),
}


def execute_tool(name: str, args: dict, user_id: int) -> str:
    fn = _TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": "Tool not found: " + name})
    # The model may call a no-arg tool with arguments `null` (→ None) or a non-dict;
    # every tool lambda does args.get(...), so coerce to a dict defensively.
    if not isinstance(args, dict):
        args = {}
    try:
        return fn(user_id, args)
    except Exception as exc:
        msg = "Error running tool " + name + ": " + str(exc)
        logger.error(msg, exc_info=True)
        return json.dumps({"error": msg})
