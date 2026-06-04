import logging
from typing import Optional
from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment
from sqlalchemy import func, and_
from datetime import datetime, timedelta
import hashlib
import time

logger = logging.getLogger("bizassist.context_engine")

# ============================================================
#  CACHE SYSTEM  —  Reduces DB queries for same request
# ============================================================

_context_cache = {}  # In-memory cache
CACHE_TTL = 300  # 5 minutes in seconds

def _get_cache_key(query: str) -> str:
    """Generate unique cache key from user query"""
    return hashlib.md5(query.lower().encode()).hexdigest()

def _is_cache_valid(cache_key: str) -> bool:
    """Check if cache entry exists and is still valid"""
    if cache_key not in _context_cache:
        return False
    
    cached_data = _context_cache[cache_key]
    elapsed = time.time() - cached_data['timestamp']
    
    if elapsed > CACHE_TTL:
        del _context_cache[cache_key]  # Remove expired cache
        return False
    
    return True

def _get_from_cache(cache_key: str) -> Optional[str]:
    """Get cached context if valid"""
    if _is_cache_valid(cache_key):
        return _context_cache[cache_key]['data']
    return None

def _save_to_cache(cache_key: str, data: str):
    """Save context to cache with timestamp"""
    _context_cache[cache_key] = {
        'data': data,
        'timestamp': time.time()
    }

# ============================================================
#  BUILD_CONTEXT  —  OPTIMIZED for minimal token usage
#  Only includes essential summaries (no full lists).
# ============================================================

def build_context(db) -> str:
    """
    Queries live SQLite data and returns a minimal but complete
    business summary. Optimized to reduce token count.
    """

    lines = ["=== BUSINESS DATA ===\n"]

    # --------------------------------------------------------
    # 1. INVOICE SUMMARY (stats only, no lists)
    # --------------------------------------------------------

    try:
        total_invoices = db.query(Invoice).count()
        total_revenue = db.query(func.sum(Invoice.amount)).scalar() or 0
        
        paid_total = db.query(func.sum(Invoice.amount))\
            .filter(Invoice.status == "Paid").scalar() or 0
        
        pending_count = db.query(Invoice)\
            .filter(Invoice.status == "Pending").count()
        pending_total = db.query(func.sum(Invoice.amount))\
            .filter(Invoice.status == "Pending").scalar() or 0
        
        overdue_count = db.query(Invoice)\
            .filter(Invoice.status == "Overdue").count()
        overdue_total = db.query(func.sum(Invoice.amount))\
            .filter(Invoice.status == "Overdue").scalar() or 0

        lines.append("Invoices: Total ₹{:,.0f} | Paid ₹{:,.0f} | Pending {} (₹{:,.0f}) | Overdue {} (₹{:,.0f})".format(
            total_revenue, paid_total, pending_count, pending_total, overdue_count, overdue_total
        ))

    except Exception as e:
        lines.append(f"[Invoice error: {e}]")

    # --------------------------------------------------------
    # 2. TOP 3 CUSTOMERS (compact)
    # --------------------------------------------------------

    try:
        top_customers = db.query(
            Invoice.customer,
            func.sum(Invoice.amount).label("total")
        ).group_by(Invoice.customer)\
         .order_by(func.sum(Invoice.amount).desc())\
         .limit(3).all()

        if top_customers:
            top_str = " | ".join([f"{c.customer} (₹{c.total:,.0f})" for c in top_customers])
            lines.append(f"Top Customers: {top_str}")

    except Exception as e:
        lines.append(f"[Customers error: {e}]")

    # --------------------------------------------------------
    # 3. CRITICAL ALERTS (only top 5 overdue)
    # --------------------------------------------------------

    try:
        # OPTIMIZATION: Only load top 5 overdue, not all
        critical_overdue = db.query(Invoice)\
            .filter(Invoice.status == "Overdue")\
            .order_by(Invoice.amount.desc())\
            .limit(5).all()

        if critical_overdue:
            alerts = " | ".join([f"{inv.customer} (₹{inv.amount:,.0f})" for inv in critical_overdue])
            lines.append(f"⚠ Overdue: {alerts}")
        else:
            lines.append("✓ No overdue invoices")

    except Exception as e:
        lines.append(f"[Overdue error: {e}]")

    # --------------------------------------------------------
    # 4. INVENTORY SUMMARY (minimal)
    # --------------------------------------------------------

    try:
        total_items = db.query(Inventory).count()
        
        if total_items > 0:
            # OPTIMIZATION: Use DB queries instead of Python loops
            today = datetime.today()
            soon = today + timedelta(days=30)
            
            low_stock_count = db.query(Inventory)\
                .filter(Inventory.stock <= 10).count()
            
            lines.append(f"Inventory: {total_items} total | Low stock: {low_stock_count} items")
        else:
            lines.append("Inventory: Empty")

    except Exception as e:
        lines.append(f"[Inventory error: {e}]")

    lines.append("=== END DATA ===")

    return "\n".join(lines)


# ============================================================
#  GET_RELEVANT_CONTEXT  —  CACHED + SMART context loading
#  Checks cache first. Loads full data if requested.
# ============================================================

def get_relevant_context(user_query: str) -> str:

    db    = SessionLocal()
    query = user_query.lower()
    cache_key = _get_cache_key(user_query)

    try:
        # CHECK CACHE FIRST (saves DB queries)
        cached_result = _get_from_cache(cache_key)
        if cached_result:
            return cached_result

        # Always start with minimal base context
        context = build_context(db)

        extra = []

        # Check if user wants ALL/COMPLETE/EVERYTHING data
        load_all = any(kw in query for kw in [
            "all", "complete", "everything", "list all",
            "show all", "full", "entire", "total"
        ])

        # --- DETAILED INVENTORY --- only if asked about stock/expiry
        if any(kw in query for kw in [
            "inventory", "stock", "expiry", "expired",
            "medicine", "product", "item", "reorder", "pharmacy"
        ]):
            if load_all:
                # LOAD ALL INVENTORY
                all_inv = db.query(Inventory)\
                    .order_by(Inventory.product_name).all()
                
                if all_inv:
                    extra.append(f"\nAll Inventory ({len(all_inv)} items):")
                    for item in all_inv:
                        extra.append(
                            f"  {item.product_name}: Stock {item.stock}, Expiry {item.expiry_date}, Supplier {item.supplier}"
                        )
            
            elif any(kw in query for kw in ["low", "stock", "reorder"]):
                # Only show low stock (top 10)
                low_stock_items = db.query(Inventory)\
                    .filter(Inventory.stock <= 10)\
                    .order_by(Inventory.stock)\
                    .limit(10).all()
                
                if low_stock_items:
                    extra.append(f"\nLow Stock Items (Top 10):")
                    for item in low_stock_items:
                        extra.append(
                            f"  {item.product_name}: {item.stock} units"
                        )
            else:
                # General inventory detail (top 10 items)
                top_inv = db.query(Inventory)\
                    .order_by(Inventory.product_name)\
                    .limit(10).all()

                if top_inv:
                    extra.append("\nInventory (Top 10):")
                    for item in top_inv:
                        extra.append(
                            f"  {item.product_name}: Stock {item.stock}, Expiry {item.expiry_date}"
                        )

        # --- DETAILED INVOICES --- only if asked about invoices/customers
        if any(kw in query for kw in [
            "invoice", "customer", "client", "who owes",
            "payment", "pending", "overdue", "due", "revenue"
        ]):
            if load_all:
                # LOAD ALL INVOICES
                all_invoices = db.query(Invoice)\
                    .order_by(Invoice.amount.desc()).all()
                
                if all_invoices:
                    extra.append(f"\nAll Invoices ({len(all_invoices)} total):")
                    for inv in all_invoices:
                        extra.append(
                            f"  {inv.customer}: ₹{inv.amount:,.0f} | {inv.status} | Due {inv.due_date} | Invoice {inv.invoice_id}"
                        )
            
            elif "overdue" in query:
                # Only show overdue (top 10)
                overdue = db.query(Invoice)\
                    .filter(Invoice.status == "Overdue")\
                    .order_by(Invoice.amount.desc())\
                    .limit(10).all()
                
                if overdue:
                    extra.append(f"\nOverdue Invoices (Top 10):")
                    for inv in overdue:
                        extra.append(
                            f"  {inv.customer}: ₹{inv.amount:,.0f} (Due {inv.due_date})"
                        )
            
            elif "pending" in query:
                # Only show pending (top 10)
                pending = db.query(Invoice)\
                    .filter(Invoice.status == "Pending")\
                    .order_by(Invoice.amount.desc())\
                    .limit(10).all()
                
                if pending:
                    extra.append(f"\nPending Invoices (Top 10):")
                    for inv in pending:
                        extra.append(
                            f"  {inv.customer}: ₹{inv.amount:,.0f}"
                        )
            
            else:
                # General invoice detail (top 10 by amount)
                top_invoices = db.query(Invoice)\
                    .order_by(Invoice.amount.desc())\
                    .limit(10).all()

                if top_invoices:
                    extra.append("\nTop 10 Invoices by Amount:")
                    for inv in top_invoices:
                        extra.append(
                            f"  {inv.customer}: ₹{inv.amount:,.0f} ({inv.status})"
                        )

        if extra:
            context += "\n" + "\n".join(extra)

        # SAVE TO CACHE before returning
        _save_to_cache(cache_key, context)

        return context

    except Exception as e:
        return f"[Context error: {e}]"

    finally:
        db.close()