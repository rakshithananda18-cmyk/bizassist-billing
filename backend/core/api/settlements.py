"""Owner/manager financial settlements with durable body-key idempotency."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import Invoice
from services.auth import restrict_cashier
from services.realtime import realtime_manager
from core.accounting import settlements
from core.accounting.settlement_models import SupplierPayment, CustomerRefund, CustomerCreditAllocation

router = APIRouter()


class MoneyRequest(BaseModel):
    amount: float = Field(gt=0, lt=1e15, allow_inf_nan=False)
    idempotency_key: str = Field(min_length=1, max_length=160)
    note: Optional[str] = None


class SupplierPaymentRequest(MoneyRequest):
    purchase_invoice_id: int
    payment_mode: str = "Cash"
    payment_date: Optional[str] = None


class CustomerRefundRequest(MoneyRequest):
    credit_note_id: int
    payment_mode: str = "Cash"
    payment_date: Optional[str] = None


class CreditAllocationRequest(MoneyRequest):
    credit_note_id: int
    target_invoice_id: int
    allocation_date: Optional[str] = None


def _out(row):
    return {column.name: (getattr(row, column.name).isoformat() if column.name in {"created_at", "updated_at"}
                          and getattr(row, column.name) is not None else getattr(row, column.name))
            for column in row.__table__.columns}


def _list(db, model, bid, page, per_page):
    query = db.query(model).filter(model.business_id == bid)
    total = query.count()
    return {"items": [_out(row) for row in query.order_by(model.id.desc()).offset((page - 1) * per_page).limit(per_page)],
            "total": total, "page": page, "per_page": per_page}


def _execute(db, user, background, command, payload):
    try:
        row = command(db, business_id=user["id"], operator_id=user.get("user_id") or user["id"], **payload.model_dump())
        background.add_task(realtime_manager.broadcast, user["id"], {"type": "sync.trigger", "entity": row.__tablename__})
        return _out(row)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409 if str(error) == "shift_required" else 422, detail=str(error)) from None
    except Exception:
        db.rollback()
        raise


@router.get("/supplier-payments")
def list_supplier_payments(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=500),
                          user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    return _list(db, SupplierPayment, user["id"], page, per_page)


@router.post("/supplier-payments", status_code=201)
def create_supplier_payment(payload: SupplierPaymentRequest, background: BackgroundTasks,
                            user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    return _execute(db, user, background, settlements.supplier_payment, payload)


@router.get("/customer-refunds")
def list_customer_refunds(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=500),
                         user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    return _list(db, CustomerRefund, user["id"], page, per_page)


@router.post("/customer-refunds", status_code=201)
def create_customer_refund(payload: CustomerRefundRequest, background: BackgroundTasks,
                           user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    return _execute(db, user, background, settlements.customer_refund, payload)


@router.get("/customer-credit-allocations")
def list_credit_allocations(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=500),
                            user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    return _list(db, CustomerCreditAllocation, user["id"], page, per_page)


@router.post("/customer-credit-allocations", status_code=201)
def create_credit_allocation(payload: CreditAllocationRequest, background: BackgroundTasks,
                              user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    return _execute(db, user, background, settlements.allocate_credit, payload)


@router.get("/customer-credits")
def credit_notes(customer_id: Optional[int] = None, page: int = Query(1, ge=1),
                 per_page: int = Query(50, ge=1, le=500), user=Depends(restrict_cashier), db: Session = Depends(get_db)):
    query = db.query(Invoice).filter(Invoice.business_id == user["id"], Invoice.invoice_type == "credit_note")
    if customer_id is not None:
        query = query.filter(Invoice.customer_id == customer_id)
    total = query.count()
    return {"items": [{"id": row.id, "uid": row.uid, "invoice_no": row.invoice_id,
        "parent_invoice_id": row.parent_invoice_id, "customer_id": row.customer_id,
        "customer": row.customer, "total_amount": row.total_amount,
        "available_credit": settlements.credit_available(db, row)}
        for row in query.order_by(Invoice.id.desc()).offset((page - 1) * per_page).limit(per_page)],
        "total": total, "page": page, "per_page": per_page}
