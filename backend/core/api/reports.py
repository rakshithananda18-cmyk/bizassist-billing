"""
core/api/reports.py — Reports & Analytics HTTP layer (Phase 1B).
================================================================
Per FOUNDATION.md: routes stay thin. Scoped by business_id.

  GET /reports/day-summary      today's sales, collections, and GST summary
  GET /stock/ledger             audit trail of all stock movements across products
"""
import logging
from datetime import datetime
from services.dates import biz_today_str
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, case, and_
from sqlalchemy.orm import Session, joinedload

from database.db import get_db
from database.models import Invoice, Product, PurchaseInvoice, Customer, Vendor, Expense, User, Inventory, InvoiceLineItem
from core.models import StockLedger, InvoicePayment, JournalEntry, JournalLine
from services.auth import get_active_user, restrict_cashier
from core.accounting.posting import (
    ACC_CASH, ACC_AR, ACC_AP, ACC_SALES, ACC_PURCHASES, ACC_GST_OUT, ACC_GST_IN,
    build_sale_lines, build_credit_note_lines, build_purchase_lines, build_debit_note_lines, build_expense_lines
)

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.reports")

# ── Pagination ────────────────────────────────────────────────────────────────
# Unbounded list endpoints (registers, stock ledger, day book) are capped so a
# business with years of history can't blow up memory/latency. Body stays a list;
# the row count is returned in the `X-Total-Count` header so the frontend can
# offer "load more" / export-all without changing the array contract.
DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 2000


def _clamp_page(limit: int, offset: int):
    """Clamp paging params to safe bounds. limit<=0 means 'use default'."""
    if not limit or limit < 1:
        limit = DEFAULT_PAGE_LIMIT
    limit = min(limit, MAX_PAGE_LIMIT)
    offset = max(offset or 0, 0)
    return limit, offset


# ── Schemas ───────────────────────────────────────────────────────────────────

# ── Dependencies ──────────────────────────────────────────────────────────────
# restrict_cashier is the single guard in services.auth (imported above).


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/reports/day-summary")
def day_summary(
    date: Optional[str] = None,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """
    Generate a summary of sales, collections, returns, and GST totals for a specific date (YYYY-MM-DD).
    Defaults to today's date in local time.
    """
    bid = current_user["id"]
    target_date = date or biz_today_str()   # IST business date

    # 1. Sales summary (excluding credit notes)
    sales_row = (
        db.query(
            func.coalesce(func.sum(Invoice.total_amount), 0.0),
            func.coalesce(func.sum(Invoice.cgst_total), 0.0),
            func.coalesce(func.sum(Invoice.sgst_total), 0.0),
            func.coalesce(func.sum(Invoice.igst_total), 0.0),
            func.count(Invoice.id),
        )
        .filter(
            Invoice.business_id == bid,
            Invoice.invoice_date == target_date,
            Invoice.invoice_type != "credit_note",
        )
        .first()
    )
    sales_total, cgst, sgst, igst, sales_count = sales_row

    # 2. Reversals / Credit notes summary
    returns_row = (
        db.query(
            func.coalesce(func.sum(Invoice.total_amount), 0.0),
            func.count(Invoice.id),
        )
        .filter(
            Invoice.business_id == bid,
            Invoice.invoice_date == target_date,
            Invoice.invoice_type == "credit_note",
        )
        .first()
    )
    returns_total, returns_count = returns_row

    # 3. Collections / Payments summary
    col_total_row = (
        db.query(func.coalesce(func.sum(InvoicePayment.amount_paid), 0.0))
        .filter(
            InvoicePayment.business_id == bid,
            InvoicePayment.payment_date == target_date,
        )
        .first()
    )
    total_collections = col_total_row[0] if col_total_row else 0.0

    # Collections by mode
    mode_rows = (
        db.query(
            InvoicePayment.payment_mode,
            func.coalesce(func.sum(InvoicePayment.amount_paid), 0.0),
        )
        .filter(
            InvoicePayment.business_id == bid,
            InvoicePayment.payment_date == target_date,
        )
        .group_by(InvoicePayment.payment_mode)
        .all()
    )
    payment_modes = {mode or "Unknown": round(amt, 2) for mode, amt in mode_rows}

    return {
        "date": target_date,
        "total_sales": round(float(sales_total or 0.0), 2),
        "sales_count": sales_count,
        "total_collections": round(float(total_collections or 0.0), 2),
        "payment_modes": payment_modes,
        "total_returns": round(float(returns_total or 0.0), 2),
        "returns_count": returns_count,
        "gst_summary": {
            "cgst": round(float(cgst or 0.0), 2),
            "sgst": round(float(sgst or 0.0), 2),
            "igst": round(float(igst or 0.0), 2),
            "total_tax": round(float((cgst or 0.0) + (sgst or 0.0) + (igst or 0.0)), 2),
        }
    }


@router.get("/stock/ledger")
def stock_ledger(
    response: Response,
    q: Optional[str] = None,
    type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """
    Get audit trail of stock movements with filtering options.
    Returns list of matching movements.
    """
    bid = current_user["id"]
    query = db.query(StockLedger).filter(StockLedger.business_id == bid)

    if q:
        # Match product name or sku (subquery/join if needed, or by exact product_name / product_id matching)
        like = f"%{q}%"
        # Find products matching query to filter ledger rows by product_id
        matched_products = (
            db.query(Product.id)
            .filter(Product.business_id == bid, or_(Product.name.ilike(like), Product.sku.ilike(like)))
            .all()
        )
        matched_ids = [r[0] for r in matched_products]
        query = query.filter(
            or_(
                StockLedger.product_name.ilike(like),
                StockLedger.product_id.in_(matched_ids) if matched_ids else False
            )
        )

    if type:
        query = query.filter(StockLedger.movement_type == type)

    # Date filters. StockLedger.created_at is datetime. Convert comparison properly.
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(StockLedger.created_at >= df)
        except ValueError:
            pass

    if date_to:
        try:
            # Include the entire date_to day
            dt = datetime.strptime(date_to + " 23:59:59.999", "%Y-%m-%d %H:%M:%S.%f")
            query = query.filter(StockLedger.created_at <= dt)
        except ValueError:
            pass

    limit, offset = _clamp_page(limit, offset)
    total = query.count()
    response.headers["X-Total-Count"] = str(total)
    movements = (
        query.order_by(StockLedger.created_at.desc(), StockLedger.id.desc())
        .offset(offset).limit(limit).all()
    )
    logger.debug("[REPORT] stock_ledger biz=%s total=%d offset=%d limit=%d",
                 bid, total, offset, limit)

    return [
        {
            "id": m.id,
            "product_id": m.product_id,
            "product_name": m.product_name,
            "movement_type": m.movement_type,
            "qty_delta": m.qty_delta,
            "balance_after": m.balance_after,
            "reference_type": m.reference_type,
            "reference_id": m.reference_id,
            "note": m.note,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in movements
    ]


@router.get("/reports/profit-loss")
def report_pnl(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Profit & Loss overview."""
    bid = current_user["id"]
    
    # 1. Sales revenue & returns (excluding credit notes vs credit notes)
    rev_q = db.query(
        func.coalesce(func.sum(case((func.coalesce(Invoice.invoice_type, "") != "credit_note", Invoice.total_amount), else_=0.0)), 0.0).label("revenue_normal"),
        func.coalesce(func.sum(case((Invoice.invoice_type == "credit_note", Invoice.total_amount), else_=0.0)), 0.0).label("returns_sales")
    ).filter(Invoice.business_id == bid)
    if from_date:
        rev_q = rev_q.filter(Invoice.invoice_date >= from_date)
    if to_date:
        rev_q = rev_q.filter(Invoice.invoice_date <= to_date)
    revenue_normal, returns_sales = rev_q.first() or (0.0, 0.0)
    net_revenue = revenue_normal - returns_sales
    
    # 2. Cost of Goods Sold (COGS) - optimized via join instead of loops
    cogs_query = db.query(
        Invoice.invoice_type,
        InvoiceLineItem.quantity,
        Product.cost_price
    ).join(
        Invoice, Invoice.id == InvoiceLineItem.invoice_id
    ).outerjoin(
        Product, Product.id == InvoiceLineItem.product_id
    ).filter(
        Invoice.business_id == bid
    )
    if from_date:
        cogs_query = cogs_query.filter(Invoice.invoice_date >= from_date)
    if to_date:
        cogs_query = cogs_query.filter(Invoice.invoice_date <= to_date)
        
    cogs = 0.0
    for inv_type, qty, cost_price in cogs_query.all():
        sign = -1.0 if inv_type == "credit_note" else 1.0
        cost = cost_price or 0.0
        cogs += sign * (cost * (qty or 0.0))
            
    # 3. Purchases
    pur_q = db.query(
        func.coalesce(func.sum(case((func.coalesce(PurchaseInvoice.invoice_type, "") != "debit_note", PurchaseInvoice.total_amount), else_=0.0)), 0.0).label("purchases_normal"),
        func.coalesce(func.sum(case((PurchaseInvoice.invoice_type == "debit_note", PurchaseInvoice.total_amount), else_=0.0)), 0.0).label("returns_purchases")
    ).filter(PurchaseInvoice.business_id == bid)
    if from_date:
        pur_q = pur_q.filter(PurchaseInvoice.invoice_date >= from_date)
    if to_date:
        pur_q = pur_q.filter(PurchaseInvoice.invoice_date <= to_date)
    purchases_normal, returns_purchases = pur_q.first() or (0.0, 0.0)
    net_purchases = purchases_normal - returns_purchases

    # 4. Expenses
    exp_q = db.query(
        func.coalesce(func.sum(case((Expense.expense_type == "Direct", Expense.amount), else_=0.0)), 0.0).label("direct_exp"),
        func.coalesce(func.sum(case((Expense.expense_type == "Indirect", Expense.amount), else_=0.0)), 0.0).label("indirect_exp")
    ).filter(Expense.business_id == bid)
    if from_date:
        exp_q = exp_q.filter(Expense.expense_date >= from_date)
    if to_date:
        exp_q = exp_q.filter(Expense.expense_date <= to_date)
    direct_exp, indirect_exp = exp_q.first() or (0.0, 0.0)
    total_exp = direct_exp + indirect_exp
    
    gross_profit = net_revenue - cogs
    net_income = gross_profit - total_exp
    
    return [
        {"metric": "Gross Sales Revenue", "amount": round(revenue_normal, 2)},
        {"metric": "Sales Returns (Credit Notes)", "amount": round(returns_sales, 2)},
        {"metric": "Net Sales Revenue", "amount": round(net_revenue, 2)},
        {"metric": "Cost of Goods Sold (COGS)", "amount": round(cogs, 2)},
        {"metric": "Gross Profit", "amount": round(gross_profit, 2)},
        {"metric": "Direct Expenses (OPEX)", "amount": round(direct_exp, 2)},
        {"metric": "Indirect Expenses (OPEX)", "amount": round(indirect_exp, 2)},
        {"metric": "Total Expenses (OPEX)", "amount": round(total_exp, 2)},
        {"metric": "Net Purchases (Inventory)", "amount": round(net_purchases, 2)},
        {"metric": "Net Income", "amount": round(net_income, 2)},
    ]


@router.get("/reports/gst")
def report_gst(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """GST CGST, SGST, IGST breakdown."""
    bid = current_user["id"]
    inv_query = db.query(Invoice).filter(Invoice.business_id == bid)
    if from_date:
        inv_query = inv_query.filter(Invoice.invoice_date >= from_date)
    if to_date:
        inv_query = inv_query.filter(Invoice.invoice_date <= to_date)
    invoices = inv_query.order_by(Invoice.invoice_date.asc()).all()
    
    result = []
    for inv in invoices:
        cgst = inv.cgst_total or 0.0
        sgst = inv.sgst_total or 0.0
        igst = inv.igst_total or 0.0
        total_gst = cgst + sgst + igst
        taxable_val = (inv.total_amount or 0.0) - total_gst
        
        result.append({
            "invoice_number": inv.invoice_id,
            "invoice_date": inv.invoice_date,
            "customer_name": inv.customer or "Cash Customer",
            "taxable_value": round(taxable_val, 2),
            "cgst_amount": round(cgst, 2),
            "sgst_amount": round(sgst, 2),
            "igst_amount": round(igst, 2),
            "total_gst": round(total_gst, 2),
            "total_amount": round(inv.total_amount or 0.0, 2),
        })
    return result


@router.get("/reports/stock-movement")
def report_stock_movement(
    response: Response,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Complete inventory movement history."""
    bid = current_user["id"]
    query = db.query(StockLedger).filter(StockLedger.business_id == bid)
    if from_date:
        try:
            df = datetime.strptime(from_date, "%Y-%m-%d")
            query = query.filter(StockLedger.created_at >= df)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.strptime(to_date + " 23:59:59.999", "%Y-%m-%d %H:%M:%S.%f")
            query = query.filter(StockLedger.created_at <= dt)
        except ValueError:
            pass
            
    limit, offset = _clamp_page(limit, offset)
    total = query.count()
    response.headers["X-Total-Count"] = str(total)
    movements = (
        query.order_by(StockLedger.created_at.asc(), StockLedger.id.asc())
        .offset(offset).limit(limit).all()
    )
    logger.debug("[REPORT] stock_movement biz=%s total=%d offset=%d limit=%d",
                 bid, total, offset, limit)

    return [
        {
            "date": m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else None,
            "product_name": m.product_name,
            "movement_type": m.movement_type,
            "quantity_change": m.qty_delta,
            "balance_after": m.balance_after,
            "reference": m.reference_type or "manual",
            "note": m.note or "",
        }
        for m in movements
    ]


@router.get("/reports/sales-register")
def report_sales_register(
    response: Response,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Itemized list of all sales invoices."""
    bid = current_user["id"]
    inv_query = db.query(Invoice).filter(Invoice.business_id == bid)
    if from_date:
        inv_query = inv_query.filter(Invoice.invoice_date >= from_date)
    if to_date:
        inv_query = inv_query.filter(Invoice.invoice_date <= to_date)
    limit, offset = _clamp_page(limit, offset)
    total = inv_query.count()
    response.headers["X-Total-Count"] = str(total)
    invoices = (
        inv_query.order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .offset(offset).limit(limit).all()
    )
    logger.debug("[REPORT] sales_register biz=%s total=%d offset=%d limit=%d",
                 bid, total, offset, limit)
    
    result = []
    for inv in invoices:
        cgst = inv.cgst_total or 0.0
        sgst = inv.sgst_total or 0.0
        igst = inv.igst_total or 0.0
        total_gst = cgst + sgst + igst
        taxable_val = (inv.total_amount or 0.0) - total_gst
        
        result.append({
            "invoice_number": inv.invoice_id,
            "invoice_date": inv.invoice_date,
            "customer_name": inv.customer or "Cash Customer",
            "subtotal": round(inv.subtotal or 0.0, 2),
            "discount_total": round(inv.discount_total or 0.0, 2),
            "taxable_value": round(taxable_val, 2),
            "cgst_total": round(cgst, 2),
            "sgst_total": round(sgst, 2),
            "igst_total": round(igst, 2),
            "total_amount": round(inv.total_amount or 0.0, 2),
            "status": inv.status or "Pending",
        })
    return result


@router.get("/reports/shift-reconciliations")
def report_shift_reconciliations(
    response: Response,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Shift & cash-drawer reconciliation history (plan Phase 3): who operated
    the register, when, opening float, expected vs counted cash/UPI, the
    short/over discrepancy, plus paid in/out movements and what was left in
    the drawer vs moved to bank. Owner-only (cashiers see only their own
    current shift via /shifts/current)."""
    from database.models import RegisterShift, ShiftCashMovement
    bid = current_user["id"]
    q = db.query(RegisterShift).filter(RegisterShift.business_id == bid)
    if from_date:
        q = q.filter(RegisterShift.start_time >= from_date)
    if to_date:
        q = q.filter(RegisterShift.start_time <= f"{to_date} 23:59:59")
    limit, offset = _clamp_page(limit, offset)
    total = q.count()
    response.headers["X-Total-Count"] = str(total)
    rows = (
        q.order_by(RegisterShift.start_time.desc())
        .offset(offset).limit(limit).all()
    )

    user_ids = {r.user_id for r in rows}
    names = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            names[u.id] = u.staff_login_name or u.username

    # Movement sums per shift in one grouped query (paid in / out / to bank).
    shift_ids = [r.id for r in rows]
    moves = {}
    if shift_ids:
        mrows = (
            db.query(ShiftCashMovement.shift_id, ShiftCashMovement.movement_type,
                     ShiftCashMovement.category,
                     func.coalesce(func.sum(ShiftCashMovement.amount), 0.0))
            .filter(ShiftCashMovement.business_id == bid,
                    ShiftCashMovement.shift_id.in_(shift_ids))
            .group_by(ShiftCashMovement.shift_id, ShiftCashMovement.movement_type,
                      ShiftCashMovement.category)
            .all()
        )
        for sid, mtype, cat, total in mrows:
            m = moves.setdefault(sid, {"paid_in": 0.0, "paid_out": 0.0, "removed_at_close": 0.0})
            if cat == "closing_removal":
                m["removed_at_close"] += float(total or 0.0)
            elif cat != "opening_variance" and mtype in ("paid_in", "paid_out"):
                m[mtype] += float(total or 0.0)

    result = []
    for s in rows:
        cash_diff = ((s.closing_cash_actual or 0.0) - (s.closing_cash_expected or 0.0)) \
            if s.status == "CLOSED" else None
        upi_diff = ((s.closing_upi_actual or 0.0) - (s.closing_upi_expected or 0.0)) \
            if s.status == "CLOSED" else None
        m = moves.get(s.id, {"paid_in": 0.0, "paid_out": 0.0, "removed_at_close": 0.0})
        result.append({
            "operator": names.get(s.user_id, f"user #{s.user_id}"),
            "start_time": s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else None,
            "end_time": s.end_time.strftime("%Y-%m-%d %H:%M") if s.end_time else None,
            "status": s.status,
            "opening_cash": round(s.opening_cash or 0.0, 2),
            "paid_in": round(m["paid_in"], 2),
            "paid_out": round(m["paid_out"], 2),
            "expected_cash": round(s.closing_cash_expected, 2) if s.closing_cash_expected is not None else None,
            "counted_cash": round(s.closing_cash_actual, 2) if s.closing_cash_actual is not None else None,
            "cash_short_over": round(cash_diff, 2) if cash_diff is not None else None,
            "left_in_drawer": round(s.closing_float, 2) if s.closing_float is not None else None,
            "moved_out_at_close": round(m["removed_at_close"], 2),
            "expected_upi": round(s.closing_upi_expected, 2) if s.closing_upi_expected is not None else None,
            "counted_upi": round(s.closing_upi_actual, 2) if s.closing_upi_actual is not None else None,
            "upi_short_over": round(upi_diff, 2) if upi_diff is not None else None,
            "notes": s.notes,
        })
    return result


@router.get("/reports/purchase-register")
def report_purchase_register(
    response: Response,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Itemized list of all purchase invoices."""
    bid = current_user["id"]
    pur_query = db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == bid)
    if from_date:
        pur_query = pur_query.filter(PurchaseInvoice.invoice_date >= from_date)
    if to_date:
        pur_query = pur_query.filter(PurchaseInvoice.invoice_date <= to_date)
    limit, offset = _clamp_page(limit, offset)
    total = pur_query.count()
    response.headers["X-Total-Count"] = str(total)
    purchases = (
        pur_query.order_by(PurchaseInvoice.invoice_date.asc(), PurchaseInvoice.id.asc())
        .offset(offset).limit(limit).all()
    )
    logger.debug("[REPORT] purchase_register biz=%s total=%d offset=%d limit=%d",
                 bid, total, offset, limit)
    
    result = []
    for p in purchases:
        tax_total = (p.cgst_total or 0.0) + (p.sgst_total or 0.0) + (p.igst_total or 0.0)
        result.append({
            "bill_number": p.invoice_number,
            "bill_date": p.invoice_date,
            "supplier_name": p.supplier_name,
            "subtotal": round(p.subtotal or 0.0, 2),
            "tax_total": round(tax_total, 2),
            "total_amount": round(p.total_amount or 0.0, 2),
            "status": p.status or "Pending",
        })
    return result


@router.get("/reports/outstanding")
def report_outstanding(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Pending receivables from customers and payables to vendors."""
    bid = current_user["id"]
    
    # 1. Customers Outstanding
    customers = db.query(Customer).filter(Customer.business_id == bid).all()
    result = []
    
    cust_aggregates = db.query(
        Invoice.customer_id,
        func.sum(func.coalesce(Invoice.total_amount, 0.0)).label("total_amt"),
        func.sum(func.coalesce(Invoice.paid_amount, 0.0)).label("paid_amt")
    ).filter(
        Invoice.business_id == bid
    ).group_by(Invoice.customer_id).all()
    
    cust_map = {
        row.customer_id: (row.total_amt or 0.0, row.paid_amt or 0.0)
        for row in cust_aggregates if row.customer_id is not None
    }
    
    for c in customers:
        total_amt, paid_amt = cust_map.get(c.id, (0.0, 0.0))
        outstanding = max(total_amt - paid_amt, 0.0)
        
        if outstanding > 0:
            result.append({
                "party_name": c.name,
                "party_type": "Customer",
                "total_amount": round(total_amt, 2),
                "paid_amount": round(paid_amt, 2),
                "outstanding_amount": round(outstanding, 2),
            })
            
    # 2. Vendors Outstanding
    vendors = db.query(Vendor).filter(Vendor.business_id == bid).all()
    
    pur_aggregates = db.query(
        PurchaseInvoice.supplier_id,
        func.sum(func.coalesce(PurchaseInvoice.total_amount, 0.0)).label("total_amt"),
        func.sum(case((PurchaseInvoice.status != "Paid", PurchaseInvoice.total_amount), else_=0.0)).label("outstanding")
    ).filter(
        PurchaseInvoice.business_id == bid
    ).group_by(PurchaseInvoice.supplier_id).all()
    
    pur_map = {
        row.supplier_id: (row.total_amt or 0.0, row.outstanding or 0.0)
        for row in pur_aggregates if row.supplier_id is not None
    }
    
    for v in vendors:
        total_amt, outstanding = pur_map.get(v.id, (0.0, 0.0))
        paid_amt = total_amt - outstanding
        
        if outstanding > 0:
            result.append({
                "party_name": v.name,
                "party_type": "Vendor/Supplier",
                "total_amount": round(total_amt, 2),
                "paid_amount": round(paid_amt, 2),
                "outstanding_amount": round(outstanding, 2),
            })
            
    return result


@router.get("/reports/party-ledger")
def report_party_ledger(
    party_type: str = Query(..., description="customer | vendor"),
    party_id: int = Query(...),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Party Ledger / Account Statement — one customer's or vendor's running
    account, transaction by transaction, with opening + closing balances.

    Built from source documents so it ties exactly to the other books:
      • customer  → Sales (Dr, they owe us) · Receipts (Cr) · Credit Notes (Cr);
                    closing == the party's slice of Balance-Sheet *receivables*.
      • vendor    → Purchases (Cr, we owe them) · Payments (Dr) · Debit Notes (Dr);
                    closing == the party's slice of Balance-Sheet *payables*.

    `from`/`to` window the displayed rows; the opening balance is the running
    balance of everything *before* `from`, so a windowed statement still foots.
    A receipt is taken from the invoice's own `paid_amount` (the receivable
    source of truth) — never double-counted against the payments table.
    """
    bid = current_user["id"]
    ptype = (party_type or "").lower()
    if ptype not in ("customer", "vendor"):
        raise HTTPException(status_code=400, detail="party_type must be 'customer' or 'vendor'")

    # ── Resolve + tenant-scope the party (404 if missing or not yours) ────────
    if ptype == "customer":
        party = db.query(Customer).filter(Customer.id == party_id, Customer.business_id == bid).first()
    else:
        party = db.query(Vendor).filter(Vendor.id == party_id, Vendor.business_id == bid).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    # ── Build the full, unwindowed list of (date, type, ref, debit, credit) ───
    entries = []
    if ptype == "customer":
        invoices = db.query(Invoice).filter(
            Invoice.business_id == bid, Invoice.customer_id == party_id
        ).all()
        for inv in invoices:
            if inv.invoice_type == "credit_note":
                entries.append((inv.invoice_date, "Credit Note", inv.invoice_id or f"CN-{inv.id}",
                                0.0, inv.total_amount or 0.0))
            else:
                entries.append((inv.invoice_date, "Sale", inv.invoice_id or f"INV-{inv.id}",
                                inv.total_amount or 0.0, 0.0))
                if (inv.paid_amount or 0.0) > 0:
                    entries.append((inv.invoice_date, "Receipt", inv.invoice_id or f"INV-{inv.id}",
                                    0.0, inv.paid_amount or 0.0))
    else:
        purchases = db.query(PurchaseInvoice).filter(
            PurchaseInvoice.business_id == bid, PurchaseInvoice.supplier_id == party_id
        ).all()
        for pur in purchases:
            ref = pur.invoice_number or f"PUR-{pur.id}"
            if pur.invoice_type == "debit_note":
                entries.append((pur.invoice_date, "Debit Note", ref, pur.total_amount or 0.0, 0.0))
            else:
                entries.append((pur.invoice_date, "Purchase", ref, 0.0, pur.total_amount or 0.0))
                if pur.status == "Paid":
                    entries.append((pur.invoice_date, "Payment", ref, pur.total_amount or 0.0, 0.0))

    # Chronological; (None dates sort first, treated as oldest).
    entries.sort(key=lambda e: e[0] or "")

    # ── Opening balance (everything strictly before `from`) + windowed rows ───
    opening = 0.0
    rows = []
    running = 0.0
    started = False
    for (date, etype, ref, debit, credit) in entries:
        delta = debit - credit
        if from_date and (date or "") < from_date:
            opening += delta
            continue
        if to_date and (date or "") > to_date:
            continue
        if not started:
            running = opening
            started = True
        running += delta
        rows.append({
            "date": date, "type": etype, "ref_no": ref,
            "debit": round(debit, 2), "credit": round(credit, 2),
            "balance": round(running, 2),
        })

    if not started:           # no rows in window — closing still = opening
        running = opening

    total_debit = round(sum(r["debit"] for r in rows), 2)
    total_credit = round(sum(r["credit"] for r in rows), 2)
    closing = round(running, 2)
    # Customers carry a positive (Dr) receivable; vendors a positive (Cr) payable.
    balance_type = ("Receivable" if closing >= 0 else "Advance") if ptype == "customer" \
        else ("Payable" if closing <= 0 else "Advance")

    logger.info(
        "[REPORT] party-ledger bid=%s type=%s party=%s rows=%d opening=%.2f closing=%.2f",
        bid, ptype, party_id, len(rows), round(opening, 2), closing,
    )

    return {
        "party": {"id": party_id, "name": party.name, "type": ptype},
        "opening_balance": round(opening, 2),
        "entries": rows,
        "summary": {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "closing_balance": closing,
            "balance_type": balance_type,
            "abs_closing": abs(closing),
        },
    }


@router.get("/reports/gstr1-b2b")
def report_gstr1_b2b(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """GSTR-1 B2B outward supplies (sales to registered taxpayers)."""
    bid = current_user["id"]
    # joinedload customer_ref: this report reads inv.customer_ref per row, which is
    # a plain-lazy relationship → eager-load it to avoid an N+1 of Customer queries.
    inv_query = db.query(Invoice).options(joinedload(Invoice.customer_ref)).filter(
        Invoice.business_id == bid, Invoice.invoice_type != "credit_note")
    if from_date and isinstance(from_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date >= from_date)
    if to_date and isinstance(to_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date <= to_date)
    invoices = inv_query.all()
    
    b2b_list = []
    for inv in invoices:
        recipient_gstin = inv.customer_ref.gstin if inv.customer_ref else None
        if not recipient_gstin:
            continue
        
        # Group line items by tax rate
        rates = {}
        for li in inv.line_items:
            rate = (li.cgst_rate or 0.0) + (li.sgst_rate or 0.0) + (li.igst_rate or 0.0)
            if rate not in rates:
                rates[rate] = {
                    "taxable_value": 0.0,
                    "cgst_amount": 0.0,
                    "sgst_amount": 0.0,
                    "igst_amount": 0.0,
                    "cess_amount": 0.0,
                }
            rates[rate]["taxable_value"] += li.taxable_value or 0.0
            rates[rate]["cgst_amount"] += li.cgst_amount or 0.0
            rates[rate]["sgst_amount"] += li.sgst_amount or 0.0
            rates[rate]["igst_amount"] += li.igst_amount or 0.0
            rates[rate]["cess_amount"] += li.cess_amount or 0.0
            
        for rate, totals in rates.items():
            b2b_list.append({
                "recipient_gstin": recipient_gstin,
                "recipient_name": inv.customer_ref.name if inv.customer_ref else inv.customer,
                "invoice_number": inv.invoice_id,
                "invoice_date": inv.invoice_date,
                "invoice_value": round(inv.total_amount or 0.0, 2),
                "place_of_supply": inv.place_of_supply or "29-Karnataka",
                "reverse_charge": "Y" if inv.reverse_charge else "N",
                "tax_rate": round(rate, 2),
                "taxable_value": round(totals["taxable_value"], 2),
                "cgst_amount": round(totals["cgst_amount"], 2),
                "sgst_amount": round(totals["sgst_amount"], 2),
                "igst_amount": round(totals["igst_amount"], 2),
                "cess_amount": round(totals["cess_amount"], 2),
            })
    return b2b_list


@router.get("/reports/gstr1-b2cs")
def report_gstr1_b2cs(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """GSTR-1 B2CS outward supplies (sales to unregistered consumers, aggregated by POS and rate)."""
    bid = current_user["id"]
    # joinedload customer_ref (read per row below) to avoid an N+1 of Customer queries.
    inv_query = db.query(Invoice).options(joinedload(Invoice.customer_ref)).filter(
        Invoice.business_id == bid, Invoice.invoice_type != "credit_note")
    if from_date and isinstance(from_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date >= from_date)
    if to_date and isinstance(to_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date <= to_date)
    invoices = inv_query.all()
    
    b2cs_grouped = {}
    for inv in invoices:
        recipient_gstin = inv.customer_ref.gstin if inv.customer_ref else None
        if recipient_gstin:
            continue
        
        pos = inv.place_of_supply or "29-Karnataka"
        for li in inv.line_items:
            rate = (li.cgst_rate or 0.0) + (li.sgst_rate or 0.0) + (li.igst_rate or 0.0)
            key = (pos, rate)
            if key not in b2cs_grouped:
                b2cs_grouped[key] = {
                    "taxable_value": 0.0,
                    "cgst_amount": 0.0,
                    "sgst_amount": 0.0,
                    "igst_amount": 0.0,
                    "cess_amount": 0.0,
                }
            b2cs_grouped[key]["taxable_value"] += li.taxable_value or 0.0
            b2cs_grouped[key]["cgst_amount"] += li.cgst_amount or 0.0
            b2cs_grouped[key]["sgst_amount"] += li.sgst_amount or 0.0
            b2cs_grouped[key]["igst_amount"] += li.igst_amount or 0.0
            b2cs_grouped[key]["cess_amount"] += li.cess_amount or 0.0
            
    b2cs_list = []
    for (pos, rate), totals in b2cs_grouped.items():
        b2cs_list.append({
            "place_of_supply": pos,
            "tax_rate": round(rate, 2),
            "taxable_value": round(totals["taxable_value"], 2),
            "cgst_amount": round(totals["cgst_amount"], 2),
            "sgst_amount": round(totals["sgst_amount"], 2),
            "igst_amount": round(totals["igst_amount"], 2),
            "cess_amount": round(totals["cess_amount"], 2),
        })
    return b2cs_list


@router.get("/reports/gstr1-hsn")
def report_gstr1_hsn(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """GSTR-1 HSN summary of outward supplies."""
    bid = current_user["id"]
    inv_query = db.query(Invoice).filter(Invoice.business_id == bid)
    if from_date and isinstance(from_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date >= from_date)
    if to_date and isinstance(to_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date <= to_date)
    invoices = inv_query.all()
    
    hsn_grouped = {}
    for inv in invoices:
        sign = -1.0 if inv.invoice_type == "credit_note" else 1.0
        for li in inv.line_items:
            hsn = (li.hsn_sac or "").strip() or "N/A"
            desc = (li.description or li.product_name or "").strip()
            unit = (li.unit or "Nos").strip()
            
            key = (hsn, desc, unit)
            if key not in hsn_grouped:
                hsn_grouped[key] = {
                    "total_quantity": 0.0,
                    "total_value": 0.0,
                    "taxable_value": 0.0,
                    "cgst_amount": 0.0,
                    "sgst_amount": 0.0,
                    "igst_amount": 0.0,
                    "cess_amount": 0.0,
                }
            hsn_grouped[key]["total_quantity"] += sign * (li.quantity or 0.0)
            hsn_grouped[key]["total_value"] += sign * (li.line_total or 0.0)
            hsn_grouped[key]["taxable_value"] += sign * (li.taxable_value or 0.0)
            hsn_grouped[key]["cgst_amount"] += sign * (li.cgst_amount or 0.0)
            hsn_grouped[key]["sgst_amount"] += sign * (li.sgst_amount or 0.0)
            hsn_grouped[key]["igst_amount"] += sign * (li.igst_amount or 0.0)
            hsn_grouped[key]["cess_amount"] += sign * (li.cess_amount or 0.0)
            
    hsn_list = []
    for (hsn, desc, unit), totals in hsn_grouped.items():
        hsn_list.append({
            "hsn_sac": hsn,
            "description": desc,
            "unit": unit,
            "total_quantity": round(totals["total_quantity"], 2),
            "total_value": round(totals["total_value"], 2),
            "taxable_value": round(totals["taxable_value"], 2),
            "cgst_amount": round(totals["cgst_amount"], 2),
            "sgst_amount": round(totals["sgst_amount"], 2),
            "igst_amount": round(totals["igst_amount"], 2),
            "cess_amount": round(totals["cess_amount"], 2),
        })
    return hsn_list


@router.get("/reports/gstr3b")
def report_gstr3b(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """GSTR-3B monthly summary of outward and inward supplies with ITC."""
    bid = current_user["id"]
    inv_query = db.query(Invoice).filter(Invoice.business_id == bid)
    if from_date and isinstance(from_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date >= from_date)
    if to_date and isinstance(to_date, str):
        inv_query = inv_query.filter(Invoice.invoice_date <= to_date)
    invoices = inv_query.all()
    
    # User state code for intra-state logic
    biz = db.query(User).filter(User.id == bid).first()
    business_state = getattr(biz, "state_code", None) if biz else None
    
    outward_normal_taxable = 0.0
    outward_normal_cgst = 0.0
    outward_normal_sgst = 0.0
    outward_normal_igst = 0.0
    outward_normal_cess = 0.0
    
    outward_zero_taxable = 0.0
    outward_zero_igst = 0.0
    
    outward_exempt_taxable = 0.0
    
    for inv in invoices:
        sign = -1.0 if inv.invoice_type == "credit_note" else 1.0
        for li in inv.line_items:
            rate = (li.cgst_rate or 0.0) + (li.sgst_rate or 0.0) + (li.igst_rate or 0.0)
            if rate > 0:
                outward_normal_taxable += sign * (li.taxable_value or 0.0)
                outward_normal_cgst += sign * (li.cgst_amount or 0.0)
                outward_normal_sgst += sign * (li.sgst_amount or 0.0)
                outward_normal_igst += sign * (li.igst_amount or 0.0)
                outward_normal_cess += sign * (li.cess_amount or 0.0)
            else:
                is_inter = (li.igst_rate or 0.0) > 0 or (inv.place_of_supply and business_state and not inv.place_of_supply.startswith(business_state))
                if is_inter:
                    outward_zero_taxable += sign * (li.taxable_value or 0.0)
                    outward_zero_igst += sign * (li.igst_amount or 0.0)
                else:
                    outward_exempt_taxable += sign * (li.taxable_value or 0.0)
                    
    # Purchases
    pur_query = db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == bid)
    if from_date and isinstance(from_date, str):
        pur_query = pur_query.filter(PurchaseInvoice.invoice_date >= from_date)
    if to_date and isinstance(to_date, str):
        pur_query = pur_query.filter(PurchaseInvoice.invoice_date <= to_date)
    purchases = pur_query.all()
    
    rc_taxable = 0.0
    rc_cgst = 0.0
    rc_sgst = 0.0
    rc_igst = 0.0
    rc_cess = 0.0
    
    itc_cgst = 0.0
    itc_sgst = 0.0
    itc_igst = 0.0
    itc_cess = 0.0
    
    reversal_cgst = 0.0
    reversal_sgst = 0.0
    reversal_igst = 0.0
    reversal_cess = 0.0
    
    for p in purchases:
        sign = -1.0 if p.invoice_type == "debit_note" else 1.0
        
        if p.reverse_charge:
            rc_taxable += sign * (p.subtotal or 0.0)
            rc_cgst += sign * (p.cgst_total or 0.0)
            rc_sgst += sign * (p.sgst_total or 0.0)
            rc_igst += sign * (p.igst_total or 0.0)
            rc_cess += sign * (p.cess_total or 0.0)
            
        if p.invoice_type != "debit_note":
            itc_cgst += p.cgst_total or 0.0
            itc_sgst += p.sgst_total or 0.0
            itc_igst += p.igst_total or 0.0
            itc_cess += p.cess_total or 0.0
        else:
            reversal_cgst += p.cgst_total or 0.0
            reversal_sgst += p.sgst_total or 0.0
            reversal_igst += p.igst_total or 0.0
            reversal_cess += p.cess_total or 0.0
            
    net_itc_cgst = max(itc_cgst - reversal_cgst, 0.0)
    net_itc_sgst = max(itc_sgst - reversal_sgst, 0.0)
    net_itc_igst = max(itc_igst - reversal_igst, 0.0)
    net_itc_cess = max(itc_cess - reversal_cess, 0.0)
    
    gstr3b_data = [
        {
            "gstr3b_section": "3.1(a) Outward Taxable Supplies",
            "taxable_value": round(outward_normal_taxable, 2),
            "cgst_amount": round(outward_normal_cgst, 2),
            "sgst_amount": round(outward_normal_sgst, 2),
            "igst_amount": round(outward_normal_igst, 2),
            "cess_amount": round(outward_normal_cess, 2),
        },
        {
            "gstr3b_section": "3.1(b) Outward Zero-Rated Supplies",
            "taxable_value": round(outward_zero_taxable, 2),
            "cgst_amount": 0.0,
            "sgst_amount": 0.0,
            "igst_amount": round(outward_zero_igst, 2),
            "cess_amount": 0.0,
        },
        {
            "gstr3b_section": "3.1(c) Other Outward Supplies (Exempt/Nil)",
            "taxable_value": round(outward_exempt_taxable, 2),
            "cgst_amount": 0.0,
            "sgst_amount": 0.0,
            "igst_amount": 0.0,
            "cess_amount": 0.0,
        },
        {
            "gstr3b_section": "3.1(d) Inward Supplies (Reverse Charge)",
            "taxable_value": round(rc_taxable, 2),
            "cgst_amount": round(rc_cgst, 2),
            "sgst_amount": round(rc_sgst, 2),
            "igst_amount": round(rc_igst, 2),
            "cess_amount": round(rc_cess, 2),
        },
        {
            "gstr3b_section": "4(A)(5) Eligible ITC Available",
            "taxable_value": 0.0,
            "cgst_amount": round(itc_cgst, 2),
            "sgst_amount": round(itc_sgst, 2),
            "igst_amount": round(itc_igst, 2),
            "cess_amount": round(itc_cess, 2),
        },
        {
            "gstr3b_section": "4(B)(2) ITC Reversed / Reclaimed",
            "taxable_value": 0.0,
            "cgst_amount": round(reversal_cgst, 2),
            "sgst_amount": round(reversal_sgst, 2),
            "igst_amount": round(reversal_igst, 2),
            "cess_amount": round(reversal_cess, 2),
        },
        {
            "gstr3b_section": "4(C) Net ITC Eligible",
            "taxable_value": 0.0,
            "cgst_amount": round(net_itc_cgst, 2),
            "sgst_amount": round(net_itc_sgst, 2),
            "igst_amount": round(net_itc_igst, 2),
            "cess_amount": round(net_itc_cess, 2),
        }
    ]
    return gstr3b_data


@router.get("/reports/day-book")
def report_day_book(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Daily Transaction Register (Day Book) chronologically."""
    bid = current_user["id"]
    
    today = biz_today_str()   # IST business date, not server-local
    f_date = from_date if from_date else today
    t_date = to_date if to_date else today
    
    transactions = []
    
    # 1. Sales Invoices
    invoices = db.query(
        Invoice.id,
        Invoice.invoice_date,
        Invoice.invoice_type,
        Invoice.invoice_id,
        Invoice.customer,
        Invoice.total_amount,
        Invoice.payment_mode,
        Invoice.status
    ).filter(
        Invoice.business_id == bid,
        Invoice.invoice_date >= f_date,
        Invoice.invoice_date <= t_date
    ).all()
    
    for inv in invoices:
        t_type = "Credit Note" if inv.invoice_type == "credit_note" else "Sale"
        cust_name = inv.customer or "Walk-in Customer"
        transactions.append({
            "date": inv.invoice_date,
            "type": t_type,
            "ref_no": inv.invoice_id or f"INV-ID-{inv.id}",
            "entity_name": cust_name,
            "amount": inv.total_amount or 0.0,
            "payment_mode": inv.payment_mode or "Credit",
            "status": inv.status or "Unpaid"
        })
        
    # 2. Purchase Invoices
    purchases = db.query(
        PurchaseInvoice.id,
        PurchaseInvoice.invoice_date,
        PurchaseInvoice.invoice_type,
        PurchaseInvoice.invoice_number,
        PurchaseInvoice.supplier_name,
        PurchaseInvoice.total_amount,
        PurchaseInvoice.status
    ).filter(
        PurchaseInvoice.business_id == bid,
        PurchaseInvoice.invoice_date >= f_date,
        PurchaseInvoice.invoice_date <= t_date
    ).all()
    
    for pur in purchases:
        t_type = "Debit Note" if pur.invoice_type == "debit_note" else "Purchase"
        transactions.append({
            "date": pur.invoice_date,
            "type": t_type,
            "ref_no": pur.invoice_number or f"PUR-ID-{pur.id}",
            "entity_name": pur.supplier_name or "Unknown Supplier",
            "amount": pur.total_amount or 0.0,
            "payment_mode": "Credit" if pur.status != "Paid" else "Cash/Bank",
            "status": pur.status or "Pending"
        })
        
    # 3. Expenses
    expenses = db.query(
        Expense.id,
        Expense.expense_date,
        Expense.category,
        Expense.amount,
        Expense.payment_mode
    ).filter(
        Expense.business_id == bid,
        Expense.expense_date >= f_date,
        Expense.expense_date <= t_date
    ).all()
    
    for exp in expenses:
        transactions.append({
            "date": exp.expense_date,
            "type": "Expense",
            "ref_no": f"EXP-{exp.id}",
            "entity_name": exp.category,
            "amount": exp.amount or 0.0,
            "payment_mode": exp.payment_mode or "Cash",
            "status": "Paid"
        })
        
    # 4. Invoice Payments
    payments = db.query(
        InvoicePayment.id,
        InvoicePayment.payment_date,
        InvoicePayment.customer_id,
        InvoicePayment.amount_paid,
        InvoicePayment.payment_mode
    ).filter(
        InvoicePayment.business_id == bid,
        InvoicePayment.payment_date >= f_date,
        InvoicePayment.payment_date <= t_date
    ).all()
    
    cust_ids = {pay.customer_id for pay in payments if pay.customer_id}
    cust_names = {}
    if cust_ids:
        cust_rows = db.query(Customer.id, Customer.name).filter(Customer.id.in_(cust_ids)).all()
        cust_names = {c.id: c.name for c in cust_rows}
        
    for pay in payments:
        cust_name = cust_names.get(pay.customer_id, "Walk-in Customer")
        transactions.append({
            "date": pay.payment_date,
            "type": "Receipt",
            "ref_no": f"REC-{pay.id}",
            "entity_name": cust_name,
            "amount": pay.amount_paid or 0.0,
            "payment_mode": pay.payment_mode or "Cash",
            "status": "Received"
        })
        
    transactions.sort(key=lambda x: x["date"])

    # Summary is computed over the FULL date window (it must total the whole day
    # book, not one page); only the transactions list is paginated.
    total_sales = sum(t["amount"] for t in transactions if t["type"] == "Sale")
    total_purchases = sum(t["amount"] for t in transactions if t["type"] == "Purchase")
    total_expenses = sum(t["amount"] for t in transactions if t["type"] == "Expense")
    total_receipts = sum(t["amount"] for t in transactions if t["type"] == "Receipt")

    net_cash_flow = total_receipts - total_expenses

    total_rows = len(transactions)
    limit, offset = _clamp_page(limit, offset)
    page = transactions[offset:offset + limit]
    logger.debug("[REPORT] day_book biz=%s window=%s..%s total=%d offset=%d limit=%d",
                 bid, f_date, t_date, total_rows, offset, limit)

    return {
        "transactions": page,
        "total": total_rows,
        "limit": limit,
        "offset": offset,
        "summary": {
            "total_sales": round(total_sales, 2),
            "total_purchases": round(total_purchases, 2),
            "total_expenses": round(total_expenses, 2),
            "total_receipts": round(total_receipts, 2),
            "net_cash_flow": round(net_cash_flow, 2)
        }
    }


@router.get("/reports/balance-sheet")
def report_balance_sheet(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Assets, Liabilities, and Net Worth Statement."""
    bid = current_user["id"]
    
    # 1. Assets — Cash & Bank Balance (Aggregated in DB)
    sales_receipts = db.query(func.coalesce(func.sum(Invoice.paid_amount), 0.0)).filter(Invoice.business_id == bid).scalar()
    
    purchase_payments = db.query(func.coalesce(func.sum(PurchaseInvoice.total_amount), 0.0)).filter(
        PurchaseInvoice.business_id == bid, PurchaseInvoice.status == "Paid"
    ).scalar()
    
    expense_payments = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(Expense.business_id == bid).scalar()
    
    cash_bank = sales_receipts - purchase_payments - expense_payments
    
    # 2. Assets — Accounts Receivable (Aggregated in DB)
    receivables_sum = db.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(func.coalesce(Invoice.invoice_type, "") != "credit_note", Invoice.total_amount > Invoice.paid_amount),
                        Invoice.total_amount - Invoice.paid_amount
                    ),
                    else_=0.0
                )
            ), 0.0
        ).label("receivables"),
        func.coalesce(
            func.sum(
                case(
                    (Invoice.invoice_type == "credit_note", Invoice.total_amount),
                    else_=0.0
                )
            ), 0.0
        ).label("sales_returns")
    ).filter(Invoice.business_id == bid).first()
    
    raw_receivables, sales_returns = receivables_sum or (0.0, 0.0)
    receivables = max((raw_receivables or 0.0) - (sales_returns or 0.0), 0.0)
    
    # 3. Assets — Inventory Valuation (Aggregated in DB)
    inventory_val = db.query(func.coalesce(func.sum(Inventory.stock * Inventory.cost_price), 0.0)).filter(
        Inventory.business_id == bid
    ).scalar()
    
    total_assets = cash_bank + receivables + inventory_val
    
    # 4. Liabilities — Accounts Payable (Aggregated in DB)
    payables_sum = db.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(PurchaseInvoice.status != "Paid", func.coalesce(PurchaseInvoice.invoice_type, "") != "debit_note"),
                        PurchaseInvoice.total_amount
                    ),
                    else_=0.0
                )
            ), 0.0
        ).label("payables"),
        func.coalesce(
            func.sum(
                case(
                    (PurchaseInvoice.invoice_type == "debit_note", PurchaseInvoice.total_amount),
                    else_=0.0
                )
            ), 0.0
        ).label("debit_notes")
    ).filter(PurchaseInvoice.business_id == bid).first()
    
    raw_payables, debit_notes = payables_sum or (0.0, 0.0)
    payables = max((raw_payables or 0.0) - (debit_notes or 0.0), 0.0)
    
    total_liabilities = payables
    
    # 5. Equity / Net Worth
    net_worth = total_assets - total_liabilities
    
    return {
        "assets": {
            "cash_bank": round(cash_bank, 2),
            "receivables": round(receivables, 2),
            "inventory_valuation": round(inventory_val, 2),
            "total_assets": round(total_assets, 2)
        },
        "liabilities": {
            "payables": round(payables, 2),
            "total_liabilities": round(total_liabilities, 2)
        },
        "net_worth": round(net_worth, 2)
    }


@router.get("/reports/ops-health")
def report_ops_health(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """One per-tenant operational-health snapshot (owner-only) for observability:
    sync backlog, unreviewed conflicts, books integrity, and today's AI usage.
    Shared with the admin fleet view via services.ops_health.compute_ops_health.
    """
    from services.ops_health import compute_ops_health
    return compute_ops_health(db, current_user["id"])


@router.get("/reports/integrity")
def report_books_integrity(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Books integrity check (owner-only): tamper-evident hash chain intact AND
    the posted journal foots globally (SUM debits == SUM credits). Read-only;
    returns the same report a scheduled job would evaluate. `ok: false` means
    the audit trail was altered or an unbalanced entry slipped in — investigate.
    """
    from core.accounting.integrity import run_integrity_check
    report = run_integrity_check(db, current_user["id"])
    logger.info("[REPORT] integrity bid=%s ok=%s drift=%s",
                current_user["id"], report["ok"], report["journal_balance"]["drift"])
    return report


@router.get("/reports/trial-balance")
def report_trial_balance(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Trial Balance — every ledger account's net balance on its normal side,
    with Dr and Cr columns that MUST be equal.

    This is a single-entry / incomplete-records system (no posted journal), so
    the trial balance is *derived* from the same source figures as the P&L and
    Balance Sheet and balanced with a Capital (owner's equity) plug:

        Dr: Cash & Bank, Accounts Receivable, Inventory, Purchases, Expenses
        Cr: Accounts Payable, Sales, Capital (the balancing figure)

    Capital absorbs the residual, so total Dr always equals total Cr (the plug
    equals opening owner's equity = Net Worth − period result). The real
    accounts (Cash/AR/Inventory/AP) are cumulative point-in-time and tie to the
    Balance Sheet; the nominal accounts (Sales/Purchases/Expenses) honour the
    from/to window and tie to the P&L. A negative balance is shown on the
    opposite column so the statement still foots.
    """
    bid = current_user["id"]

    # ── Nominal accounts (date-bounded, tie to P&L) ──────────────────────────
    sales_q = db.query(
        func.coalesce(func.sum(case((func.coalesce(Invoice.invoice_type, "") != "credit_note", Invoice.total_amount), else_=0.0)), 0.0).label("sales_normal"),
        func.coalesce(func.sum(case((Invoice.invoice_type == "credit_note", Invoice.total_amount), else_=0.0)), 0.0).label("returns_sales")
    ).filter(Invoice.business_id == bid)
    if from_date:
        sales_q = sales_q.filter(Invoice.invoice_date >= from_date)
    if to_date:
        sales_q = sales_q.filter(Invoice.invoice_date <= to_date)
    sales_normal, returns_sales = sales_q.first() or (0.0, 0.0)
    sales_net = sales_normal - returns_sales

    pur_q = db.query(
        func.coalesce(func.sum(case((func.coalesce(PurchaseInvoice.invoice_type, "") != "debit_note", PurchaseInvoice.total_amount), else_=0.0)), 0.0).label("purchases_normal"),
        func.coalesce(func.sum(case((PurchaseInvoice.invoice_type == "debit_note", PurchaseInvoice.total_amount), else_=0.0)), 0.0).label("returns_purchases")
    ).filter(PurchaseInvoice.business_id == bid)
    if from_date:
        pur_q = pur_q.filter(PurchaseInvoice.invoice_date >= from_date)
    if to_date:
        pur_q = pur_q.filter(PurchaseInvoice.invoice_date <= to_date)
    purchases_normal, returns_purchases = pur_q.first() or (0.0, 0.0)
    purchases_net = purchases_normal - returns_purchases

    exp_q = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(Expense.business_id == bid)
    if from_date:
        exp_q = exp_q.filter(Expense.expense_date >= from_date)
    if to_date:
        exp_q = exp_q.filter(Expense.expense_date <= to_date)
    expenses_total = exp_q.scalar() or 0.0

    # ── Real accounts (cumulative, tie to Balance Sheet) ─────────────────────
    sales_receipts = db.query(func.coalesce(func.sum(Invoice.paid_amount), 0.0)).filter(Invoice.business_id == bid).scalar()
    
    purchase_payments = db.query(func.coalesce(func.sum(PurchaseInvoice.total_amount), 0.0)).filter(
        PurchaseInvoice.business_id == bid, PurchaseInvoice.status == "Paid"
    ).scalar()
    
    expense_payments = db.query(func.coalesce(func.sum(Expense.amount), 0.0)).filter(Expense.business_id == bid).scalar()
    
    cash_bank = sales_receipts - purchase_payments - expense_payments

    receivables_sum = db.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(func.coalesce(Invoice.invoice_type, "") != "credit_note", Invoice.total_amount > Invoice.paid_amount),
                        Invoice.total_amount - Invoice.paid_amount
                    ),
                    else_=0.0
                )
            ), 0.0
        ).label("receivables"),
        func.coalesce(
            func.sum(
                case(
                    (Invoice.invoice_type == "credit_note", Invoice.total_amount),
                    else_=0.0
                )
            ), 0.0
        ).label("sales_returns")
    ).filter(Invoice.business_id == bid).first()
    
    raw_receivables, sales_returns = receivables_sum or (0.0, 0.0)
    receivables = max((raw_receivables or 0.0) - (sales_returns or 0.0), 0.0)

    inventory_val = db.query(func.coalesce(func.sum(Inventory.stock * Inventory.cost_price), 0.0)).filter(
        Inventory.business_id == bid
    ).scalar()

    payables_sum = db.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(PurchaseInvoice.status != "Paid", func.coalesce(PurchaseInvoice.invoice_type, "") != "debit_note"),
                        PurchaseInvoice.total_amount
                    ),
                    else_=0.0
                )
            ), 0.0
        ).label("payables"),
        func.coalesce(
            func.sum(
                case(
                    (PurchaseInvoice.invoice_type == "debit_note", PurchaseInvoice.total_amount),
                    else_=0.0
                )
            ), 0.0
        ).label("debit_notes")
    ).filter(PurchaseInvoice.business_id == bid).first()
    
    raw_payables, debit_notes = payables_sum or (0.0, 0.0)
    payables = max((raw_payables or 0.0) - (debit_notes or 0.0), 0.0)

    # ── Assemble accounts; place each balance on its normal side (sign-aware) ─
    accounts = []

    def add(account, group, balance, normal):
        debit = credit = 0.0
        if normal == "Dr":
            debit, credit = (balance, 0.0) if balance >= 0 else (0.0, -balance)
        else:
            credit, debit = (balance, 0.0) if balance >= 0 else (0.0, -balance)
        accounts.append({
            "account": account, "group": group,
            "debit": round(debit, 2), "credit": round(credit, 2),
        })

    add("Cash & Bank", "Assets", cash_bank, "Dr")
    add("Accounts Receivable", "Assets", receivables, "Dr")
    add("Inventory", "Assets", inventory_val, "Dr")
    add("Accounts Payable", "Liabilities", payables, "Cr")
    add("Sales", "Income", sales_net, "Cr")
    add("Purchases", "Expenses", purchases_net, "Dr")
    add("Operating Expenses", "Expenses", expenses_total, "Dr")

    subtotal_debit = sum(r["debit"] for r in accounts)
    subtotal_credit = sum(r["credit"] for r in accounts)
    # Capital / Owner's Equity is the plug that makes the two columns foot.
    capital = subtotal_debit - subtotal_credit
    add("Capital / Owner's Equity", "Equity", capital, "Cr")

    total_debit = round(sum(r["debit"] for r in accounts), 2)
    total_credit = round(sum(r["credit"] for r in accounts), 2)
    balanced = abs(total_debit - total_credit) < 0.01

    logger.info(
        "[REPORT] trial-balance bid=%s rows=%d dr=%.2f cr=%.2f balanced=%s",
        bid, len(accounts), total_debit, total_credit, balanced,
    )

    return {
        "accounts": accounts,
        "totals": {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "balanced": balanced,
        },
        "memo": {
            "capital_owner_equity": round(capital, 2),
            "sales_net": round(sales_net, 2),
            "purchases_net": round(purchases_net, 2),
            "expenses_total": round(expenses_total, 2),
        },
    }


def _build_journal_entries(db: Session, bid: int, from_date, to_date):
    """Reconstruct a balanced double-entry General Journal from source documents.

    Single-entry/incomplete-records system → there is no posted journal, so each
    sale / credit note / purchase / debit note / expense is turned into a set of
    Dr/Cr lines that *foot by construction* (net = total − GST, so debits always
    equal credits). Cash receipts come from the invoice's own `paid_amount`
    (never the payments table) to stay consistent with the Balance Sheet /
    Party Ledger and avoid double-counting. Returns entries sorted by date.
    """
    def within(d):
        if from_date and (d or "") < from_date:
            return False
        if to_date and (d or "") > to_date:
            return False
        return True

    def entry(date, etype, ref, narration, lines):
        clean = [{"account": a, "debit": round(dr, 2), "credit": round(cr, 2)}
                 for (a, dr, cr) in lines if round(dr, 2) or round(cr, 2)]
        dt = round(sum(l["debit"] for l in clean), 2)
        ct = round(sum(l["credit"] for l in clean), 2)
        return {
            "date": date, "type": etype, "ref_no": ref, "narration": narration,
            "lines": clean, "debit_total": dt, "credit_total": ct,
            "balanced": abs(dt - ct) < 0.01,
        }

    # Push the date window into SQL so we scan only the requested period (uses
    # ix_invoice_business_date / equivalent) instead of loading the whole ledger
    # and filtering in Python. invoice_date is an ISO 'YYYY-MM-DD' string, so a
    # lexical >=/<= compare is identical to the `within()` guard kept below.
    # coalesce(col, '') mirrors the `(d or "")` semantics of within() EXACTLY,
    # incl. NULL-dated rows (verified equivalent), so this is purely a perf change.
    def _bound(q, col):
        if from_date:
            q = q.filter(func.coalesce(col, "") >= from_date)
        if to_date:
            q = q.filter(func.coalesce(col, "") <= to_date)
        return q

    entries = []

    # ── Sales + credit notes ────────────────────────────────────────────────
    inv_q = _bound(db.query(Invoice).filter(Invoice.business_id == bid), Invoice.invoice_date)
    for inv in inv_q.all():
        if not within(inv.invoice_date):
            continue
        who = inv.customer or "customer"
        if inv.invoice_type == "credit_note":
            entries.append(entry(
                inv.invoice_date, "Credit Note", inv.invoice_id or f"CN-{inv.id}",
                f"Sales return — {who}",
                build_credit_note_lines(inv),
            ))
        else:
            entries.append(entry(
                inv.invoice_date, "Sale", inv.invoice_id or f"INV-{inv.id}",
                f"Sale — {who}",
                build_sale_lines(inv),
            ))

    # ── Purchases + debit notes ─────────────────────────────────────────────
    pur_q = _bound(db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == bid), PurchaseInvoice.invoice_date)
    for pur in pur_q.all():
        if not within(pur.invoice_date):
            continue
        ref = pur.invoice_number or f"PUR-{pur.id}"
        who = pur.supplier_name or "supplier"
        if pur.invoice_type == "debit_note":
            entries.append(entry(
                pur.invoice_date, "Debit Note", ref, f"Purchase return — {who}",
                build_debit_note_lines(pur),
            ))
        else:
            entries.append(entry(
                pur.invoice_date, "Purchase", ref, f"Purchase — {who}",
                build_purchase_lines(pur),
            ))

    # ── Expenses ────────────────────────────────────────────────────────────
    exp_q = _bound(db.query(Expense).filter(Expense.business_id == bid), Expense.expense_date)
    for exp in exp_q.all():
        if not within(exp.expense_date):
            continue
        entries.append(entry(
            exp.expense_date, "Expense", f"EXP-{exp.id}", exp.category or "Expense",
            build_expense_lines(exp),
        ))

    entries.sort(key=lambda e: e["date"] or "")
    logger.debug("[REPORT] journal rebuilt biz=%s window=%s..%s entries=%d",
                 bid, from_date or "*", to_date or "*", len(entries))
    return entries


def _opening_balances(db: Session, bid: int, from_date) -> dict:
    """Per-account opening balance (Dr − Cr) of ALL activity STRICTLY BEFORE
    `from_date` — i.e. the prior period's closing balances carried forward (R2b).

    Returns {} when no `from_date` is given (an unwindowed report already covers
    full history, so its running balance starts correctly at zero). Dates are ISO
    'YYYY-MM-DD' strings; NULL/blank dates sort before any real date and so fold
    into the opening, exactly mirroring `_build_journal_entries`' `within()` rule.
    The boundary day itself (date == from_date) belongs to the window, never the
    opening, so a transaction is counted once and only once.
    """
    if not from_date:
        return {}
    prior = _build_journal_entries(db, bid, None, from_date)
    bal: dict = {}
    for e in prior:
        if (e["date"] or "") >= from_date:      # keep STRICTLY-before the window
            continue
        for ln in e["lines"]:
            bal[ln["account"]] = bal.get(ln["account"], 0.0) + ln["debit"] - ln["credit"]
    return {a: round(v, 2) for a, v in bal.items()}


@router.get("/reports/journal")
def report_journal(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """General Journal — every transaction as balanced Dr/Cr postings."""
    bid = current_user["id"]
    limit, offset = _clamp_page(limit, offset)
    entries = _build_journal_entries(db, bid, from_date, to_date)
    td = round(sum(e["debit_total"] for e in entries), 2)
    tc = round(sum(e["credit_total"] for e in entries), 2)
    
    total_entries = len(entries)
    page = entries[offset:offset + limit]
    
    logger.info("[REPORT] journal bid=%s total=%d offset=%d limit=%d dr=%.2f cr=%.2f balanced=%s",
                bid, total_entries, offset, limit, td, tc, abs(td - tc) < 0.01)
    return {
        "entries": page,
        "total": total_entries,
        "limit": limit,
        "offset": offset,
        "totals": {"total_debit": td, "total_credit": tc, "balanced": abs(td - tc) < 0.01},
    }


@router.get("/reports/general-ledger")
def report_general_ledger(
    account: Optional[str] = Query(None, description="filter to one account (case-insensitive)"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """General Ledger — journal postings regrouped per account with a running
    balance (Dr − Cr). Optionally filter to a single account."""
    bid = current_user["id"]
    entries = _build_journal_entries(db, bid, from_date, to_date)
    # Carry the prior period's closing balances forward as this window's opening
    # balances (R2b), so each account's running balance is a TRUE balance, not just
    # in-window movement. Empty {} when no `from_date` (full history → opens at 0).
    opening = _opening_balances(db, bid, from_date)

    buckets = {}
    for e in entries:
        for ln in e["lines"]:
            buckets.setdefault(ln["account"], []).append({
                "date": e["date"], "type": e["type"], "ref_no": e["ref_no"],
                "debit": ln["debit"], "credit": ln["credit"],
            })

    if account:
        buckets = {a: p for a, p in buckets.items() if a.lower() == account.lower()}
        opening = {a: b for a, b in opening.items() if a.lower() == account.lower()}

    ledgers = []
    # Include accounts that have only an opening balance (no in-window postings) so
    # the ledger is complete — a carried-forward balance must still be visible.
    for acct in sorted(set(buckets) | set(opening)):
        ob = round(opening.get(acct, 0.0), 2)
        running = ob
        rows = []
        for p in buckets.get(acct, []):   # already chronological (entries sorted)
            running += p["debit"] - p["credit"]
            rows.append({**p, "balance": round(running, 2)})
        ledgers.append({
            "account": acct,
            "opening_balance": ob,
            "postings": rows,
            "total_debit": round(sum(r["debit"] for r in rows), 2),
            "total_credit": round(sum(r["credit"] for r in rows), 2),
            "closing_balance": round(running, 2),
        })

    logger.info("[REPORT] general-ledger bid=%s accounts=%d filter=%s opening_accts=%d",
                bid, len(ledgers), account or "all", len(opening))
    return {"ledgers": ledgers}


@router.get("/reports/audit-journal")
def report_audit_journal(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=0, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Audit Journal — the POSTED double-entry journal (written at transaction
    time, read straight from `journal_entries`/`journal_lines`). Unlike
    `/reports/journal` (reconstructed on read), this is the permanent, append-
    only audit trail of every money movement."""
    bid = current_user["id"]
    limit, offset = _clamp_page(limit, offset)

    # 1. Compute totals over the entire date window using fast DB aggregation
    totals_q = db.query(
        func.coalesce(func.sum(JournalLine.debit), 0.0).label("td"),
        func.coalesce(func.sum(JournalLine.credit), 0.0).label("tc")
    ).join(JournalEntry).filter(JournalEntry.business_id == bid)
    
    if from_date:
        totals_q = totals_q.filter(JournalEntry.entry_date >= from_date)
    if to_date:
        totals_q = totals_q.filter(JournalEntry.entry_date <= to_date)
        
    td, tc = totals_q.first() or (0.0, 0.0)
    td = round(td, 2)
    tc = round(tc, 2)

    # 2. Query only the paginated entries
    q = db.query(JournalEntry).filter(JournalEntry.business_id == bid)
    if from_date:
        q = q.filter(JournalEntry.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntry.entry_date <= to_date)
        
    total_entries = q.count()
    
    from sqlalchemy.orm import selectinload
    rows = (
        q.options(selectinload(JournalEntry.lines))
        .order_by(JournalEntry.entry_date.asc(), JournalEntry.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    entries = []
    for e in rows:
        lines = [{"account": ln.account, "debit": round(ln.debit or 0.0, 2),
                  "credit": round(ln.credit or 0.0, 2)} for ln in e.lines]
        dt = round(sum(l["debit"] for l in lines), 2)
        ct = round(sum(l["credit"] for l in lines), 2)
        entries.append({
            "id": e.id, "date": e.entry_date, "type": e.source_type,
            "source_id": e.source_id, "ref_no": e.ref_no, "narration": e.narration,
            "lines": lines, "debit_total": dt, "credit_total": ct,
            "balanced": abs(dt - ct) < 0.01,
        })

    logger.info("[REPORT] audit-journal bid=%s total=%d offset=%d limit=%d dr=%.2f cr=%.2f balanced=%s",
                bid, total_entries, offset, limit, td, tc, abs(td - tc) < 0.01)
    return {
        "entries": entries,
        "total": total_entries,
        "limit": limit,
        "offset": offset,
        "totals": {"total_debit": td, "total_credit": tc, "balanced": abs(td - tc) < 0.01,
                   "posted": True},
    }


@router.get("/reports/verify-chain")
def report_verify_chain(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Verify the tamper-evident hash chain of the POSTED journal (R3).

    Walks every posted entry in order and recomputes the SHA-256 chain. Returns
    `{ok: True, checked, head}` when the books are intact, or `{ok: False,
    broken_at, ...}` pointing at the first entry that was edited/deleted/reordered.
    Owner-only; business-scoped.
    """
    from core.accounting.posting import verify_chain
    bid = current_user["id"]
    result = verify_chain(db, bid)
    logger.info("[REPORT] verify-chain bid=%s ok=%s checked=%s",
                bid, result.get("ok"), result.get("checked"))
    return result
