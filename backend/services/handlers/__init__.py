"""
handlers/__init__.py
====================
Exports all domain handler functions for use by direct_query_handler.py.

Domain organisation:
  payments.py   — overdue, pending, top debtors
  invoices.py   — invoice count, revenue, monthly detail
  inventory.py  — stock count, low stock, expiry checks
  clients.py    — top customers, client summary
  dashboard.py  — business snapshot

Adding a new handler:
  1. Write the function in the relevant domain .py file
  2. Register it in direct_query_handler.HANDLERS
  3. Add intent mapping in services/intents.py INTENT_MAP
"""
from .clients import _client_summary, _top_customers
from .dashboard import _business_summary
from .inventory import _expiring_soon, _inventory_count, _low_stock
from .invoices import _invoice_count, _overdue_range_detail, _revenue_month_detail, _total_revenue
from .payments import _overdue_amount, _overdue_list, _pending_list, _top_debtors

# Optional convenience registry (mirrors direct_query_handler.HANDLERS)
HANDLER_REGISTRY = {
    "_business_summary": _business_summary,
    "_client_summary": _client_summary,
    "_expiring_soon": _expiring_soon,
    "_inventory_count": _inventory_count,
    "_invoice_count": _invoice_count,
    "_low_stock": _low_stock,
    "_overdue_amount": _overdue_amount,
    "_overdue_list": _overdue_list,
    "_overdue_range_detail": _overdue_range_detail,
    "_pending_list": _pending_list,
    "_revenue_month_detail": _revenue_month_detail,
    "_top_customers": _top_customers,
    "_top_debtors": _top_debtors,
    "_total_revenue": _total_revenue,
}
