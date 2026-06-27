"""
core/api/products.py — Product Management HTTP layer (Phase 1B).
================================================================
Per FOUNDATION.md: routes stay thin. Auth → scope → validate → call service.

  GET  /products?q=&page=&per_page=          paginated product list
  POST /products                             create product
  GET  /products/{id}                        single product + barcodes
  PATCH /products/{id}                       update product (name/price/description/attrs)
  POST /products/{id}/barcodes               add barcode
  GET  /products/{id}/stock                  current stock + last 50 movements
  POST /products/{id}/stock/adjustment       manual stock correction (append-only)
  POST /products/opening-stock               bulk opening-stock for multiple products
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Product
from core.models import StockLedger, ProductBarcode, Godown
from services.auth import get_active_user, restrict_cashier, restrict_cashier_only
from core.catalog import barcode as PB
from core.stock import ledger as SL
from database.models import Inventory
from services.realtime import realtime_manager

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.products")


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateProduct(BaseModel):
    name: str
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    unit: Optional[str] = "Nos"
    sku: Optional[str] = None
    barcode: Optional[str] = None
    brand: Optional[str] = None
    manufacturer: Optional[str] = None
    category: Optional[str] = None
    selling_price: float = 0.0
    wholesale_price: float = 0.0
    distributor_price: float = 0.0
    cost_price: float = 0.0
    mrp: Optional[float] = None
    cgst_rate: float = 0.0
    sgst_rate: float = 0.0
    igst_rate: float = 0.0
    is_service: bool = False
    track_inventory: bool = True
    price_includes_tax: bool = False
    attributes: Optional[Dict[str, Any]] = None  # vertical-specific JSON escape hatch
    min_stock: float = 0.0
    opening_stock: float = 0.0


class UpdateProduct(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    selling_price: Optional[float] = None
    wholesale_price: Optional[float] = None
    distributor_price: Optional[float] = None
    cost_price: Optional[float] = None
    mrp: Optional[float] = None
    hsn_sac: Optional[str] = None
    unit: Optional[str] = None
    sku: Optional[str] = None
    brand: Optional[str] = None
    manufacturer: Optional[str] = None
    category: Optional[str] = None
    cgst_rate: Optional[float] = None
    sgst_rate: Optional[float] = None
    igst_rate: Optional[float] = None
    is_active: Optional[bool] = None
    track_inventory: Optional[bool] = None
    price_includes_tax: Optional[bool] = None
    attributes: Optional[Dict[str, Any]] = None
    min_stock: Optional[float] = None


class AddBarcodeRequest(BaseModel):
    barcode: str
    make_primary: bool = False
    label: Optional[str] = None


class StockAdjustmentRequest(BaseModel):
    qty_delta: float          # signed: + adds stock, - removes stock
    note: Optional[str] = None


class OpeningStockItem(BaseModel):
    product_id: int
    qty: float
    note: Optional[str] = None


class OpeningStockRequest(BaseModel):
    items: List[OpeningStockItem]


# ── Serializers ───────────────────────────────────────────────────────────────

def _product_out(p: Product, include_barcodes: bool = False, barcodes=None, db: Session = None) -> dict:
    attrs = None
    min_stock = 0.0
    if p.attributes:
        try:
            attrs = json.loads(p.attributes)
            if isinstance(attrs, dict):
                min_stock = float(attrs.get("min_stock") or 0.0)
        except Exception:
            attrs = p.attributes
            
    stock_qty = 0.0
    if db:
        stock_qty = SL.current_stock(db, p.business_id, product_id=p.id)
        
    out = {
        "id": p.id, "name": p.name, "description": p.description,
        "sku": p.sku, "barcode": p.barcode, "brand": p.brand,
        "manufacturer": p.manufacturer, "category": p.category,
        "hsn_sac": p.hsn_sac, "unit": p.unit,
        "selling_price": p.selling_price,
        "wholesale_price": getattr(p, "wholesale_price", 0.0),
        "distributor_price": getattr(p, "distributor_price", 0.0),
        "cost_price": p.cost_price, "mrp": p.mrp,
        "cgst_rate": p.cgst_rate, "sgst_rate": p.sgst_rate, "igst_rate": p.igst_rate,
        "is_service": p.is_service, "is_active": p.is_active,
        "track_inventory": p.track_inventory, "price_includes_tax": p.price_includes_tax,
        "variant_of": p.variant_of,
        "attributes": attrs,
        "min_stock": min_stock,
        "stock_qty": stock_qty,
        "quantity": stock_qty,
    }
    if include_barcodes:
        out["barcodes"] = [
            {"barcode": b.barcode, "is_primary": b.is_primary,
             "active": b.active, "label": b.label}
            for b in (barcodes or [])
        ]
    return out


def _movement_out(m: StockLedger) -> dict:
    return {
        "id": m.id, "movement_type": m.movement_type,
        "qty_delta": m.qty_delta, "balance_after": m.balance_after,
        "reference_type": m.reference_type, "reference_id": m.reference_id,
        "note": m.note, "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/products")
def list_products(
    q: str = "",
    page: int = 1,
    per_page: int = 20,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Paginated product list scoped to the authenticated business."""
    bid = current_user["id"]
    query = db.query(Product).filter(Product.business_id == bid)

    if q:
        like = f"%{q}%"
        from sqlalchemy import or_
        query = query.filter(
            or_(Product.name.ilike(like), Product.sku.ilike(like),
                Product.barcode.ilike(like))
        )
    if category:
        query = query.filter(Product.category == category)
    if is_active is not None:
        query = query.filter(Product.is_active == is_active)

    total = query.count()
    items = (
        query.order_by(Product.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_product_out(p, db=db) for p in items],
    }


@router.post("/products", status_code=201)
def create_product(
    req: CreateProduct,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Create a new product in the catalogue."""
    bid = current_user["id"]

    attrs = req.attributes or {}
    if req.min_stock is not None:
        attrs["min_stock"] = req.min_stock
    attrs_json = json.dumps(attrs) if attrs else None

    p = Product(
        business_id=bid,
        name=req.name,
        description=req.description,
        hsn_sac=req.hsn_sac,
        unit=req.unit or "Nos",
        sku=req.sku,
        brand=req.brand,
        manufacturer=req.manufacturer,
        category=req.category,
        selling_price=req.selling_price,
        wholesale_price=req.wholesale_price,
        distributor_price=req.distributor_price,
        cost_price=req.cost_price,
        mrp=req.mrp,
        cgst_rate=req.cgst_rate,
        sgst_rate=req.sgst_rate,
        igst_rate=req.igst_rate,
        is_service=req.is_service,
        track_inventory=req.track_inventory,
        price_includes_tax=req.price_includes_tax,
        attributes=attrs_json,
        is_active=True,
    )
    db.add(p)
    db.flush()

    if req.opening_stock > 0:
        try:
            SL.record_movement(
                db,
                business_id=bid,
                movement_type=SL.OPENING,
                qty_delta=req.opening_stock,
                product_id=p.id,
                product_name=p.name,
                reference_type="manual",
                note="opening stock",
            )
        except Exception as e:
            logger.error("Failed to record opening stock: %s", e)

    # Register barcode if supplied
    if req.barcode:
        try:
            PB.add_barcode(db, bid, p.id, req.barcode, make_primary=True, source="manual")
        except PB.BarcodeConflict as e:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(e))

    db.commit()
    background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "product"})
    db.refresh(p)
    logger.info("[PRODUCTS] created product %s (biz=%s)", p.id, bid)
    barcodes = PB.list_barcodes(db, bid, p.id)
    return _product_out(p, include_barcodes=True, barcodes=barcodes, db=db)


@router.get("/products/{product_id}")
def get_product(
    product_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Single product with all barcodes, scoped to business."""
    bid = current_user["id"]
    p = db.query(Product).filter(
        Product.id == product_id, Product.business_id == bid
    ).first()
    if p is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    barcodes = PB.list_barcodes(db, bid, p.id)
    return _product_out(p, include_barcodes=True, barcodes=barcodes, db=db)


@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    req: UpdateProduct,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Update allowed product fields (name/price/description/attributes). Never touches money history."""
    bid = current_user["id"]
    p = db.query(Product).filter(
        Product.id == product_id, Product.business_id == bid
    ).first()
    if p is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    updatable = [
        "name", "description", "selling_price", "wholesale_price", "distributor_price", "cost_price", "mrp",
        "hsn_sac", "unit", "sku", "brand", "manufacturer", "category",
        "cgst_rate", "sgst_rate", "igst_rate", "is_active",
        "track_inventory", "price_includes_tax",
    ]
    data = req.model_dump(exclude_none=True)
    for field in updatable:
        if field in data:
            setattr(p, field, data[field])

    if "attributes" in data and req.attributes is not None:
        p.attributes = json.dumps(req.attributes)
        
    if req.min_stock is not None:
        attrs = {}
        if p.attributes:
            try:
                attrs = json.loads(p.attributes)
            except Exception:
                pass
        attrs["min_stock"] = req.min_stock
        p.attributes = json.dumps(attrs)

    db.commit()
    background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "product"})
    db.refresh(p)
    barcodes = PB.list_barcodes(db, bid, p.id)
    return _product_out(p, include_barcodes=True, barcodes=barcodes, db=db)


@router.post("/products/{product_id}/barcodes", status_code=201)
def add_product_barcode(
    product_id: int,
    req: AddBarcodeRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Attach a new barcode to a product."""
    bid = current_user["id"]
    p = db.query(Product).filter(
        Product.id == product_id, Product.business_id == bid
    ).first()
    if p is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    try:
        bc = PB.add_barcode(
            db, bid, product_id, req.barcode,
            make_primary=req.make_primary,
            label=req.label,
            source="manual",
        )
        db.commit()
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "product"})
    except PB.BarcodeConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "barcode": bc.barcode, "is_primary": bc.is_primary,
        "active": bc.active, "label": bc.label,
    }


@router.get("/products/{product_id}/stock")
def get_product_stock(
    product_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Current stock quantity + last 50 ledger movements for a product."""
    bid = current_user["id"]
    p = db.query(Product).filter(
        Product.id == product_id, Product.business_id == bid
    ).first()
    if p is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    current = SL.current_stock(db, bid, product_id=product_id)
    movements = (
        db.query(StockLedger)
        .filter(StockLedger.business_id == bid, StockLedger.product_id == product_id)
        .order_by(StockLedger.created_at.desc())
        .limit(50)
        .all()
    )
    batches_raw = (
        db.query(Inventory)
        .filter(Inventory.business_id == bid, Inventory.product_id == product_id)
        .all()
    )
    batches = []
    for b in batches_raw:
        g_name = "Main Warehouse"
        if b.godown_id:
            g_row = db.query(Godown).filter(Godown.id == b.godown_id, Godown.business_id == bid).first()
            if g_row:
                g_name = g_row.name
        batches.append({
            "godown_id": b.godown_id,
            "godown_name": g_name,
            "batch_no": b.batch_no,
            "expiry_date": b.expiry_date,
            "stock": b.stock or 0,
            "selling_price": b.selling_price,
            "mrp": b.mrp,
            "created_at": b.created_at.isoformat() if b.created_at else None
        })

    return {
        "product_id": product_id,
        "product_name": p.name,
        "current_stock": current,
        "unit": p.unit,
        "track_inventory": p.track_inventory,
        "movements": [_movement_out(m) for m in movements],
        "batches": batches,
    }


@router.post("/products/{product_id}/stock/adjustment", status_code=201)
def stock_adjustment(
    product_id: int,
    req: StockAdjustmentRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(restrict_cashier_only),
    db: Session = Depends(get_db),
):
    """Manual stock correction — writes an 'adjustment' movement (append-only)."""
    bid = current_user["id"]
    p = db.query(Product).filter(
        Product.id == product_id, Product.business_id == bid
    ).first()
    if p is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    if req.qty_delta == 0:
        raise HTTPException(status_code=422, detail="qty_delta cannot be zero")

    try:
        movement = SL.record_movement(
            db,
            business_id=bid,
            movement_type=SL.ADJUSTMENT,
            qty_delta=req.qty_delta,
            product_id=product_id,
            product_name=p.name,
            reference_type="manual",
            note=req.note or "manual adjustment",
        )
        db.commit()
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "product"})
    except Exception as e:
        db.rollback()
        logger.error("stock_adjustment failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not record adjustment")

    return _movement_out(movement)


@router.post("/products/opening-stock", status_code=201)
def bulk_opening_stock(
    req: OpeningStockRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(restrict_cashier_only),
    db: Session = Depends(get_db),
):
    """
    Bulk set opening stock for multiple products.
    Writes 'opening' movements for each product (append-only).
    Designed for initial data import at business onboarding.
    """
    bid = current_user["id"]
    if not req.items:
        raise HTTPException(status_code=422, detail="At least one item is required")

    results = []
    try:
        for item in req.items:
            p = db.query(Product).filter(
                Product.id == item.product_id, Product.business_id == bid
            ).first()
            if p is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {item.product_id} not found for this business",
                )
            if item.qty < 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"Opening stock qty must be >= 0 for product {item.product_id}",
                )
            movement = SL.record_movement(
                db,
                business_id=bid,
                movement_type=SL.OPENING,
                qty_delta=item.qty,
                product_id=item.product_id,
                product_name=p.name,
                reference_type="import",
                note=item.note or "opening stock",
            )
            results.append({
                "product_id": item.product_id,
                "product_name": p.name,
                "qty": item.qty,
                "balance_after": movement.balance_after,
            })
        db.commit()
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "product"})
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("bulk_opening_stock failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not record opening stock")

    return {"recorded": len(results), "items": results}


# ── Frontend Specific Stock Adjustment ────────────────────────────────────────

class FrontendStockAdjustmentRequest(BaseModel):
    product_id: int
    movement_type: str  # "stock_in" | "stock_out" | "adjustment"
    quantity: float
    reason: Optional[str] = None
    reference: Optional[str] = None


@router.post("/stock/adjust", status_code=201)
def frontend_stock_adjustment(
    req: FrontendStockAdjustmentRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(restrict_cashier_only),
    db: Session = Depends(get_db),
):
    """Stock adjustment endpoint for the billing frontend."""
    bid = current_user["id"]
    p = db.query(Product).filter(
        Product.id == req.product_id, Product.business_id == bid
    ).first()
    if p is None:
        raise HTTPException(status_code=404, detail=f"Product {req.product_id} not found")
        
    if req.quantity <= 0:
        raise HTTPException(status_code=422, detail="Quantity must be greater than zero")
        
    qty_delta = req.quantity
    m_type = SL.ADJUSTMENT
    if req.movement_type == "stock_in":
        m_type = "stock_in"
        qty_delta = req.quantity
    elif req.movement_type == "stock_out":
        m_type = "stock_out"
        qty_delta = -req.quantity
    else:
        qty_delta = req.quantity # signed delta
        
    note = req.reason or "manual adjustment"
    if req.reference:
        note += f" (Ref: {req.reference})"
        
    try:
        movement = SL.record_movement(
            db,
            business_id=bid,
            movement_type=m_type,
            qty_delta=qty_delta,
            product_id=req.product_id,
            product_name=p.name,
            reference_type="manual",
            note=note,
        )
        db.commit()
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "product"})
    except Exception as e:
        db.rollback()
        logger.error("frontend_stock_adjustment failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not record adjustment")
        
    return _movement_out(movement)

