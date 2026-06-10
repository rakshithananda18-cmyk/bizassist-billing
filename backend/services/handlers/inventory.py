"""
inventory.py  —  Inventory & Stock Handlers
Domain handler for BizAssist Tier-0 intent engine.

Each function takes (user_id, ...) and returns a formatted markdown string
ready to send to the frontend. Returns None on DB error (caller falls through to AI).

To add a new handler:
  1. Add a function here
  2. Register it in services/direct_query_handler.py HANDLERS dict
  3. Add intent mapping in services/intents.py INTENT_MAP
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment
from services.dates import parse_date

logger = logging.getLogger("bizassist.handlers.inventory")

def _inventory_count(user_id: int) -> str:
    db = SessionLocal()
    try:
        total = db.query(Inventory).filter(Inventory.business_id == user_id).count()
        return f"**Inventory Count**\n\nYou have **{total} product{'s' if total != 1 else ''}** tracked in inventory."
    finally:
        db.close()

def _low_stock(user_id: int) -> str:
    db = SessionLocal()
    try:
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        low   = [i for i in items if i.stock is not None and int(i.stock) <= 10]

        if not low:
            return "✅ All products have sufficient stock (above 10 units)."

        low.sort(key=lambda x: int(x.stock))
        lines = [
            f"There are **{len(low)}** products with low stock (≤ 10 units):\n",
            "| Product Name | Stock | Supplier |",
            "|:---|:---|:---|"
        ]
        for item in low:
            lines.append(f"| **{item.product_name}** | `{item.stock}` units | {item.supplier or '—'} |")
        return "\n".join(lines)
    finally:
        db.close()

def _expiring_soon(user_id: int) -> str:
    db = SessionLocal()
    try:
        today = datetime.today()
        soon  = today + timedelta(days=30)
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()

        expiring = []
        for item in items:
            if not item.expiry_date:
                continue
            exp = parse_date(item.expiry_date)
            if exp is None:
                continue
            if today <= exp <= soon:
                expiring.append((item, exp))

        if not expiring:
            return "✅ No products expiring within the next 30 days."

        expiring.sort(key=lambda x: x[1])
        lines = [
            f"There are **{len(expiring)}** products expiring within the next 30 days:\n",
            "| Product Name | Expiry Date | Days Left | Stock |",
            "|:---|:---|:---|:---|"
        ]
        for item, exp in expiring:
            days_left = (exp - today).days
            lines.append(f"| **{item.product_name}** | {item.expiry_date} | {days_left} days left | `{item.stock}` units |")
        return "\n".join(lines)
    finally:
        db.close()
