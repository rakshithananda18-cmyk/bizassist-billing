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
        total_rev   = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        paid_amt    = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar() or 0
        overdue_amt = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0
        pending_ct  = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        inv_items   = db.query(Inventory).filter(Inventory.business_id == user_id).count()

        top = (
            db.query(Invoice.customer, func.sum(Invoice.amount).label("total_amount"))
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .first()
        )

        return json.dumps({
            "total_revenue":               float(total_rev),
            "collected_revenue":           float(paid_amt),
            "overdue_revenue":             float(overdue_amt),
            "collection_rate_pct":         round((paid_amt / total_rev) * 100) if total_rev else 0,
            "pending_invoice_count":       pending_ct,
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
