"""Keyword and semantic search tool functions + schemas."""
import json
import logging
from sqlalchemy import or_
from database.db import SessionLocal
from database.models import Invoice, Inventory
from services.embeddings import semantic_search_records
from ._utils import safe_int

logger = logging.getLogger("bizassist.tools.search")


def search_exact_keywords(user_id: int, query: str) -> str:
    """Searches products, customers, and suppliers across all tables using exact matches."""
    db = SessionLocal()
    try:
        inv_matches = db.query(Invoice).filter(
            Invoice.business_id == user_id,
            or_(Invoice.customer.ilike(f"%{query}%"), Invoice.product.ilike(f"%{query}%")),
        ).limit(10).all()

        item_matches = db.query(Inventory).filter(
            Inventory.business_id == user_id,
            or_(Inventory.product_name.ilike(f"%{query}%"), Inventory.supplier.ilike(f"%{query}%")),
        ).limit(10).all()

        result = {
            "invoice_matches": [
                {"customer": i.customer, "product": i.product, "amount": i.amount, "status": i.status}
                for i in inv_matches
            ],
            "inventory_matches": [
                {"product_name": i.product_name, "stock": i.stock, "supplier": i.supplier}
                for i in item_matches
            ],
        }
        return json.dumps(result)
    except Exception as e:
        logger.error("search_exact_keywords failed: %s", e)
        return json.dumps({"error": f"Failed search: {e}"})
    finally:
        db.close()


def query_semantic_index(user_id: int, query: str, limit: int = 5) -> str:
    """Searches business records semantically using local embeddings (all-MiniLM-L6-v2)."""
    try:
        results = semantic_search_records(user_id, query, safe_int(limit, 5))
        return json.dumps(results)
    except Exception as e:
        logger.error("query_semantic_index failed: %s", e)
        return json.dumps({"error": f"Semantic search failed: {e}"})


# ── Schemas ──────────────────────────────────────────────────────────────────

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_exact_keywords",
            "description": "Searches for matching keywords across customers, product names, and suppliers in all tables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword (e.g. a specific product, customer name, or supplier name)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_semantic_index",
            "description": "Searches the business database semantically using local embeddings (all-MiniLM-L6-v2). Ideal for conceptual queries and natural language questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query expressing the concept to find (e.g. 'unpaid clients', 'medicines expiring soon')."},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max matching records to return. Defaults to 5."},
                },
                "required": ["query"],
            },
        },
    },
]
