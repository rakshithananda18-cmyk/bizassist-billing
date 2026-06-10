"""Payments tool function + schema."""
import json
import logging
from database.db import SessionLocal
from database.models import Payment

logger = logging.getLogger("bizassist.tools.payments")


def get_payment_list(user_id: int, paid_status: str = None, customer: str = None, limit: int = 15) -> str:
    """Retrieves payments, filtering by paid status (Yes/No) or customer name."""
    db = SessionLocal()
    try:
        query = db.query(Payment).filter(Payment.business_id == user_id)
        if paid_status:
            query = query.filter(Payment.paid.ilike(paid_status))
        if customer:
            query = query.filter(Payment.customer.ilike(f"%{customer}%"))

        payments = query.order_by(Payment.due_date.asc()).limit(limit).all()
        result = [
            {"customer": p.customer, "amount": float(p.amount or 0), "due_date": p.due_date, "paid": p.paid}
            for p in payments
        ]
        return json.dumps(result)
    except Exception as e:
        logger.error("get_payment_list failed: %s", e)
        return json.dumps({"error": f"Failed to fetch payments: {e}"})
    finally:
        db.close()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_payment_records",
            "description": "Returns payment details, optionally filtered by paid status ('Yes' or 'No') or customer name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paid_status": {"type": "string", "description": "Filter status: 'Yes' (paid) or 'No' (unpaid)."},
                    "customer":    {"type": "string", "description": "Filter by customer name (partial match)."},
                    "limit":       {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max rows to return. Defaults to 15."},
                },
            },
        },
    },
]
