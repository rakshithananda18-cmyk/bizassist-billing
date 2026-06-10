"""Inventory tool function + schema."""
import json
import logging
from datetime import datetime
from database.db import SessionLocal
from database.models import Inventory
from services.dates import parse_date

logger = logging.getLogger("bizassist.tools.inventory")


def get_inventory_status(user_id: int, filter_stock_under: int = None, filter_expiry_days: int = None) -> str:
    """Queries inventory, optionally filtering by low stock threshold or upcoming expiration."""
    db = SessionLocal()
    try:
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        today = datetime.today()
        filtered = []

        for item in items:
            match = True

            if filter_stock_under is not None:
                stock_val = int(item.stock) if (item.stock is not None and str(item.stock).isdigit()) else 9999
                if stock_val > filter_stock_under:
                    match = False

            if filter_expiry_days is not None and item.expiry_date:
                exp = parse_date(item.expiry_date)
                days_left = (exp - today).days if exp is not None else 9999
                if days_left < 0 or days_left > filter_expiry_days:
                    match = False

            if match:
                filtered.append({
                    "product_name": item.product_name,
                    "stock":        item.stock,
                    "expiry_date":  item.expiry_date,
                    "supplier":     item.supplier,
                })

        return json.dumps(filtered[:30])  # cap at 30 for token efficiency
    except Exception as e:
        logger.error("get_inventory_status failed: %s", e)
        return json.dumps({"error": f"Failed to fetch inventory: {e}"})
    finally:
        db.close()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "check_inventory_stock",
            "description": "Returns stock items, optionally filtering for low stock levels or products expiring soon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_stock_under":  {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Filter products with stock level below or equal to this count."},
                    "filter_expiry_days":  {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Filter products expiring within this number of days from today."},
                },
            },
        },
    },
]
