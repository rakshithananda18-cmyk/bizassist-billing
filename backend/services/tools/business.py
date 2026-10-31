"""Business overview tool function + schema."""
import json
import logging
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory

logger = logging.getLogger("bizassist.tools.business")


def get_business_overview(user_id: int) -> str:
    """Returns a high-level summary overview of business metrics."""
    db = SessionLocal()
    try:
        from core.billing.balances import business_revenue_summary
        metrics = business_revenue_summary(db, user_id)
        inv_items = db.query(Inventory).filter(Inventory.business_id == user_id).count()

        from core.billing.balances import customer_revenue_rows
        ranked = customer_revenue_rows(db, user_id)
        top = ranked[0] if ranked else None

        return json.dumps({
            "total_revenue":               metrics["net_revenue"],
            "collected_revenue":           metrics["collected_revenue"],
            "overdue_revenue":             metrics["overdue_revenue"],
            "collection_rate_pct":         metrics["collection_rate_pct"],
            "pending_invoice_count":       metrics["pending_invoice_count"],
            "inventory_products_tracked":  inv_items,
            "top_customer":                top.customer if top else None,
            "top_customer_revenue":        float(top.total_amount or 0) if top else 0,
        })
    except Exception as e:
        logger.error("get_business_overview failed: %s", e)
        return json.dumps({"error": f"Failed to fetch business overview: {e}"})
    finally:
        db.close()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "view_business_metrics",
            "description": "Returns a high-level overview of overall business health, revenue metrics, collection rate, and outstanding dues.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]
