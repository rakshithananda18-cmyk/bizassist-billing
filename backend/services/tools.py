import json
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment
from services.embeddings import semantic_search_records

def safe_int(val, default=None):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

# ==========================================
# TOOL FUNCTIONS
# ==========================================

def get_invoice_summary(user_id: int) -> str:
    """Returns counts and total amounts of invoices grouped by status."""
    db = SessionLocal()
    try:
        results = db.query(
            Invoice.status,
            func.count(Invoice.id).label("count"),
            func.sum(Invoice.amount).label("total")
        ).filter(Invoice.business_id == user_id).group_by(Invoice.status).all()
        
        summary = {}
        for row in results:
            summary[row.status] = {
                "count": row.count,
                "total_amount": float(row.total or 0)
            }
        return json.dumps(summary)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch invoice summary: {str(e)}"})
    finally:
        db.close()

def get_invoice_list(user_id: int, status: str = None, customer: str = None, limit: int = 15) -> str:
    """Gets a filtered list of invoices. Defaults to a limit of 15 to conserve tokens."""
    db = SessionLocal()
    try:
        query = db.query(Invoice).filter(Invoice.business_id == user_id)
        if status:
            query = query.filter(Invoice.status.ilike(status))
        if customer:
            query = query.filter(Invoice.customer.ilike(f"%{customer}%"))
        
        invoices = query.order_by(Invoice.amount.desc()).limit(limit).all()
        result = []
        for inv in invoices:
            result.append({
                "invoice_id": inv.invoice_id,
                "customer": inv.customer,
                "amount": float(inv.amount or 0),
                "status": inv.status,
                "invoice_date": inv.invoice_date,
                "due_date": inv.due_date
            })
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch invoice list: {str(e)}"})
    finally:
        db.close()

def get_top_customers(user_id: int, limit: int = 5) -> str:
    """Returns top N customers sorted by revenue."""
    db = SessionLocal()
    try:
        rows = db.query(
            Invoice.customer,
            func.sum(Invoice.amount).label("total_revenue"),
            func.count(Invoice.id).label("invoice_count")
        ).filter(Invoice.business_id == user_id)\
         .group_by(Invoice.customer)\
         .order_by(func.sum(Invoice.amount).desc())\
         .limit(limit).all()
         
        result = []
        for r in rows:
            result.append({
                "customer": r.customer,
                "total_revenue": float(r.total_revenue or 0),
                "invoice_count": r.invoice_count
            })
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch top customers: {str(e)}"})
    finally:
        db.close()

def get_inventory_status(user_id: int, filter_stock_under: int = None, filter_expiry_days: int = None) -> str:
    """Queries inventory, optionally filtering by low stock threshold or upcoming expiration."""
    db = SessionLocal()
    try:
        query = db.query(Inventory).filter(Inventory.business_id == user_id)
        items = query.all()
        
        filtered = []
        today = datetime.today()
        
        for item in items:
            match = True
            
            # Low stock check
            if filter_stock_under is not None:
                stock_val = int(item.stock) if (item.stock is not None and str(item.stock).isdigit()) else 9999
                if stock_val > filter_stock_under:
                    match = False
                    
            # Expiry check
            if filter_expiry_days is not None and item.expiry_date:
                days_left = 9999
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        exp = datetime.strptime(str(item.expiry_date), fmt)
                        days_left = (exp - today).days
                        break
                    except ValueError:
                        continue
                if days_left < 0 or days_left > filter_expiry_days:
                    match = False
            
            if match:
                filtered.append({
                    "product_name": item.product_name,
                    "stock": item.stock,
                    "expiry_date": item.expiry_date,
                    "supplier": item.supplier
                })
        return json.dumps(filtered[:30]) # cap at 30 items for token efficiency
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch inventory: {str(e)}"})
    finally:
        db.close()

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
        result = []
        for p in payments:
            result.append({
                "customer": p.customer,
                "amount": float(p.amount or 0),
                "due_date": p.due_date,
                "paid": p.paid
            })
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch payments: {str(e)}"})
    finally:
        db.close()

def get_business_overview(user_id: int) -> str:
    """Returns a high-level summary overview of business metrics."""
    db = SessionLocal()
    try:
        total_rev = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        paid_amt = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar() or 0
        overdue_amt = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0
        pending_ct = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        inv_items = db.query(Inventory).filter(Inventory.business_id == user_id).count()
        
        top = db.query(Invoice.customer, func.sum(Invoice.amount).label("t"))\
                .filter(Invoice.business_id == user_id)\
                .group_by(Invoice.customer)\
                .order_by(func.sum(Invoice.amount).desc()).first()
                
        return json.dumps({
            "total_revenue": float(total_rev),
            "collected_revenue": float(paid_amt),
            "overdue_revenue": float(overdue_amt),
            "collection_rate_pct": round((paid_amt / total_rev) * 100) if total_rev else 0,
            "pending_invoice_count": pending_ct,
            "inventory_products_tracked": inv_items,
            "top_customer": top.customer if top else None,
            "top_customer_revenue": float(top.t or 0) if top else 0
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch business overview: {str(e)}"})
    finally:
        db.close()

def search_exact_keywords(user_id: int, query: str) -> str:
    """Searches products, customers, and suppliers across all tables using exact matches."""
    db = SessionLocal()
    try:
        inv_matches = db.query(Invoice).filter(
            Invoice.business_id == user_id,
            or_(Invoice.customer.ilike(f"%{query}%"), Invoice.product.ilike(f"%{query}%"))
        ).limit(10).all()
        
        item_matches = db.query(Inventory).filter(
            Inventory.business_id == user_id,
            or_(Inventory.product_name.ilike(f"%{query}%"), Inventory.supplier.ilike(f"%{query}%"))
        ).limit(10).all()
        
        result = {
            "invoice_matches": [
                {"customer": i.customer, "product": i.product, "amount": i.amount, "status": i.status}
                for i in inv_matches
            ],
            "inventory_matches": [
                {"product_name": i.product_name, "stock": i.stock, "supplier": i.supplier}
                for i in item_matches
            ]
        }
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed search: {str(e)}"})
    finally:
        db.close()

# ==========================================
# TOOL DISPATCHER
# ==========================================

def execute_tool(name: str, args: dict, user_id: int) -> str:
    """Executes a tool function by name with parsed arguments and user_id."""
    tool_map = {
        "summarize_invoices": lambda u, a: get_invoice_summary(u),
        "list_invoices": lambda u, a: get_invoice_list(u, a.get("status"), a.get("customer"), safe_int(a.get("limit"), 15)),
        "rank_top_customers": lambda u, a: get_top_customers(u, safe_int(a.get("limit"), 5)),
        "check_inventory_stock": lambda u, a: get_inventory_status(u, safe_int(a.get("filter_stock_under")), safe_int(a.get("filter_expiry_days"))),
        "list_payment_records": lambda u, a: get_payment_list(u, a.get("paid_status"), a.get("customer"), safe_int(a.get("limit"), 15)),
        "view_business_metrics": lambda u, a: get_business_overview(u),
        "search_exact_keywords": lambda u, a: search_exact_keywords(u, a.get("query")),
        "query_semantic_index": lambda u, a: query_semantic_index(u, a.get("query"), a.get("limit"))
    }
    
    fn = tool_map.get(name)
    if not fn:
        return json.dumps({"error": f"Tool '{name}' not found."})
    try:
        return fn(user_id, args)
    except Exception as e:
        return json.dumps({"error": f"Error running tool '{name}': {str(e)}"})

def query_semantic_index(user_id: int, query: str, limit: int = 5) -> str:
    """Searches the business records (invoices, inventory, payments) semantically using OpenAI embeddings and cosine similarity."""
    try:
        limit_val = safe_int(limit, 5)
        results = semantic_search_records(user_id, query, limit_val)
        return json.dumps(results)
    except Exception as e:
        return json.dumps({"error": f"Semantic search failed: {str(e)}"})

# ==========================================
# TOOL SCHEMAS FOR LLM
# ==========================================

schemas = [
    {
        "type": "function",
        "function": {
            "name": "summarize_invoices",
            "description": "Returns counts and total amounts of invoices grouped by status (Paid, Pending, Overdue).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_invoices",
            "description": "Returns a list of invoices, optionally filtered by status or customer name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: 'Paid', 'Pending', or 'Overdue'."
                    },
                    "customer": {
                        "type": "string",
                        "description": "Filter by customer name (partial match)."
                    },
                    "limit": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Max invoices to return. Defaults to 15."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rank_top_customers",
            "description": "Returns top customers ranked by total billing revenue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Max customers to return. Defaults to 5."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_inventory_stock",
            "description": "Returns stock items, optionally filtering for low stock levels or products expiring soon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_stock_under": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Filter products with stock level below or equal to this count."
                    },
                    "filter_expiry_days": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Filter products expiring within this number of days from today."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_payment_records",
            "description": "Returns payment details, optionally filtered by paid status ('Yes' or 'No') or customer name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paid_status": {
                        "type": "string",
                        "description": "Filter status: 'Yes' (paid) or 'No' (unpaid)."
                    },
                    "customer": {
                        "type": "string",
                        "description": "Filter by customer name (partial match)."
                    },
                    "limit": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Max rows to return. Defaults to 15."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_business_metrics",
            "description": "Returns a high-level overview of overall business health, revenue metrics, collection rate, and outstanding dues.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_exact_keywords",
            "description": "Searches for matching keywords across customers, product names, and suppliers in all tables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword (e.g. a specific product, customer name, or supplier name)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_semantic_index",
            "description": "Searches the business database semantically using OpenAI embeddings and cosine similarity. Ideal for conceptual queries, natural language, and questions that do not have exact keywords matching the records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query expressing the concept to find (e.g. 'unpaid clients', 'medicines expiring soon')."
                    },
                    "limit": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Max matching records to return. Defaults to 5."
                    }
                },
                "required": ["query"]
            }
        }
    }
]
