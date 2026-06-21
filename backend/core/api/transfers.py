import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from core.models import StockTransfer, StockTransferLineItem, Godown
from services.auth import get_active_user
from core.stock import ledger as SL

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.transfers")

class StockTransferLineItemRequest(BaseModel):
    product_id: int
    product_name: str
    quantity: float
    unit: Optional[str] = "Nos"
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None

class CreateStockTransferRequest(BaseModel):
    transfer_date: str
    from_godown_id: int
    to_godown_id: int
    notes: Optional[str] = None
    items: List[StockTransferLineItemRequest]

def _line_item_out(li: StockTransferLineItem) -> dict:
    return {
        "id": li.id,
        "product_id": li.product_id,
        "product_name": li.product_name,
        "quantity": li.quantity,
        "unit": li.unit,
    }

def _transfer_out(st: StockTransfer, db: Session, bid: int) -> dict:
    from_godown = db.query(Godown).filter(Godown.id == st.from_godown_id, Godown.business_id == bid).first()
    to_godown = db.query(Godown).filter(Godown.id == st.to_godown_id, Godown.business_id == bid).first()
    
    return {
        "id": st.id,
        "transfer_date": st.transfer_date,
        "from_godown_id": st.from_godown_id,
        "from_godown_name": from_godown.name if from_godown else "Unknown",
        "to_godown_id": st.to_godown_id,
        "to_godown_name": to_godown.name if to_godown else "Unknown",
        "notes": st.notes,
        "items": [_line_item_out(item) for item in st.line_items],
    }

@router.get("/stock-transfers")
def list_transfers(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    bid = current_user["id"]
    transfers = (
        db.query(StockTransfer)
        .filter(StockTransfer.business_id == bid)
        .order_by(StockTransfer.id.desc())
        .all()
    )
    return [_transfer_out(t, db, bid) for t in transfers]

@router.post("/stock-transfers", status_code=201)
def create_transfer(
    req: CreateStockTransferRequest,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    bid = current_user["id"]
    if req.from_godown_id == req.to_godown_id:
        raise HTTPException(status_code=400, detail="Source and destination godowns must be different")

    # Validate godowns exist
    from_g = db.query(Godown).filter(Godown.id == req.from_godown_id, Godown.business_id == bid).first()
    to_g = db.query(Godown).filter(Godown.id == req.to_godown_id, Godown.business_id == bid).first()
    if not from_g or not to_g:
        raise HTTPException(status_code=400, detail="Invalid source or destination godown")

    if not req.items:
        raise HTTPException(status_code=400, detail="Transfer must contain at least one item")

    # 1. Create StockTransfer header
    st = StockTransfer(
        business_id=bid,
        transfer_date=req.transfer_date,
        from_godown_id=req.from_godown_id,
        to_godown_id=req.to_godown_id,
        notes=req.notes
    )
    db.add(st)
    db.flush() # Populate st.id

    # 2. Add line items and record stock movements
    for item in req.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Invalid quantity for product {item.product_name}")

        # Check stock in source godown
        source_stock = SL.current_stock(
            db, bid, product_id=item.product_id,
            godown_id=req.from_godown_id, batch_no=item.batch_no
        )
        if source_stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {item.product_name} in {from_g.name}. Available: {source_stock}, Requested: {item.quantity}"
            )

        li = StockTransferLineItem(
            transfer_id=st.id,
            product_id=item.product_id,
            product_name=item.product_name,
            quantity=item.quantity,
            unit=item.unit
        )
        db.add(li)

        # Record TRANSFER_OUT movement for source godown
        SL.record_movement(
            db,
            business_id=bid,
            movement_type=SL.TRANSFER_OUT,
            qty_delta=-item.quantity,
            product_id=item.product_id,
            product_name=item.product_name,
            reference_type="stock_transfer",
            reference_id=st.id,
            note=f"Transfer to {to_g.name}",
            godown_id=req.from_godown_id,
            batch_no=item.batch_no,
            expiry_date=item.expiry_date
        )

        # Record TRANSFER_IN movement for destination godown
        SL.record_movement(
            db,
            business_id=bid,
            movement_type=SL.TRANSFER_IN,
            qty_delta=item.quantity,
            product_id=item.product_id,
            product_name=item.product_name,
            reference_type="stock_transfer",
            reference_id=st.id,
            note=f"Transfer from {from_g.name}",
            godown_id=req.to_godown_id,
            batch_no=item.batch_no,
            expiry_date=item.expiry_date
        )

    db.commit()
    db.refresh(st)
    logger.info("[TRANSFERS] Stock transfer %s created (biz=%s)", st.id, bid)
    return _transfer_out(st, db, bid)
