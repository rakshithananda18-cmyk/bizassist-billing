"""
routers/shops.py — delivery points (retail / medical shops) and route templates.
Shops can be imported from the owner's BizAssist Billing customers and stay
linked by `customer_id`.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.billing_models import BillingCustomer
from app.db import get_db
from app.models import FieldRoute, FieldRouteStop, FieldShop, FieldStaff
from app.security import Principal, current_principal, require_owner
from app.services import get_scoped, log_activity, route_out, shop_out
from app.timeutil import parse_hhmm

router = APIRouter(prefix="/api", tags=["shops", "routes"])


# ── Shops ─────────────────────────────────────────────────────────────────────

class ShopIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    contact_name: Optional[str] = Field(None, max_length=80)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)
    area: Optional[str] = Field(None, max_length=80)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    notes: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None


class ShopPatch(ShopIn):
    name: Optional[str] = Field(None, min_length=1, max_length=120)


def _apply_shop(shop: FieldShop, req: ShopIn, *, partial: bool) -> None:
    data = req.model_dump(exclude_unset=partial)
    for k, v in data.items():
        if k in ("is_active", "name") and v is None:
            continue
        setattr(shop, k, v.strip() if isinstance(v, str) else v)
    if (shop.lat is None) != (shop.lng is None):
        raise HTTPException(status_code=422, detail="Give both latitude and longitude, or neither.")
    if "lat" in data and shop.lat is not None:
        shop.location_source = "owner"


@router.get("/shops")
def list_shops(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = db.query(FieldShop).filter(FieldShop.business_id == p.business_id)
    if p.kind == "staff":
        q = q.filter(FieldShop.is_active.is_(True))
    return [shop_out(s) for s in q.order_by(FieldShop.name.asc()).all()]


@router.post("/shops", status_code=201)
def create_shop(req: ShopIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    shop = FieldShop(business_id=p.business_id, name=req.name.strip())
    _apply_shop(shop, req, partial=False)
    if shop.is_active is None:
        shop.is_active = True
    db.add(shop)
    db.flush()
    log_activity(db, p, "shop.create", entity="shop", entity_id=shop.id, summary=shop.name)
    db.commit()
    return shop_out(shop)


@router.patch("/shops/{shop_id}")
def update_shop(shop_id: int, req: ShopPatch, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    shop = get_scoped(db, FieldShop, p.business_id, shop_id, "Shop")
    _apply_shop(shop, req, partial=True)
    log_activity(db, p, "shop.update", entity="shop", entity_id=shop.id, summary=shop.name)
    db.commit()
    return shop_out(shop)


@router.get("/billing/customers")
def billing_customers(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """The owner's BizAssist Billing customers, flagged if already a shop here."""
    linked = {cid for (cid,) in db.query(FieldShop.customer_id).filter(
        FieldShop.business_id == p.business_id, FieldShop.customer_id.isnot(None)).all()}
    rows = (db.query(BillingCustomer)
            .filter(BillingCustomer.business_id == p.business_id)
            .order_by(BillingCustomer.name.asc()).all())
    return [{
        "id": c.id, "name": c.name, "phone": c.phone, "address": c.address,
        "gstin": c.gstin, "is_active": c.is_active is not False, "linked": c.id in linked,
    } for c in rows]


class ImportCustomers(BaseModel):
    customer_ids: List[int] = Field(..., min_length=1, max_length=500)


@router.post("/shops/import-billing")
def import_from_billing(req: ImportCustomers, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Create shops from billing customers (name, phone, address). Already-linked
    customers are skipped, so the call is safe to repeat."""
    customers = (db.query(BillingCustomer)
                 .filter(BillingCustomer.business_id == p.business_id,
                         BillingCustomer.id.in_(req.customer_ids)).all())
    found = {c.id for c in customers}
    missing = sorted(set(req.customer_ids) - found)
    if missing:
        # Includes ids that belong to another business — never reveal which.
        raise HTTPException(status_code=404, detail=f"Customer(s) not found: {missing}")
    linked = {cid for (cid,) in db.query(FieldShop.customer_id).filter(
        FieldShop.business_id == p.business_id, FieldShop.customer_id.in_(found)).all()}
    created = []
    for c in customers:
        if c.id in linked:
            continue
        shop = FieldShop(
            business_id=p.business_id, name=c.name or f"Customer {c.id}",
            phone=c.phone, address=c.address, customer_id=c.id,
        )
        db.add(shop)
        created.append(shop)
    db.flush()
    if created:
        log_activity(db, p, "shop.import_billing", entity="shop", summary=f"{len(created)} from billing customers")
    db.commit()
    return {"created": [shop_out(s) for s in created], "skipped_already_linked": len(linked)}


# ── Route templates ───────────────────────────────────────────────────────────

class RouteIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    weekdays: List[int] = Field(default_factory=list, description="ISO weekdays Mon=1..Sun=7; empty = any day")
    default_staff_id: Optional[int] = None
    due_time: str = "18:00"
    shop_ids: List[int] = Field(default_factory=list, description="Ordered stops")
    is_active: bool = True


def _validate_route(db: Session, p: Principal, req: RouteIn) -> None:
    if any(d < 1 or d > 7 for d in req.weekdays):
        raise HTTPException(status_code=422, detail="weekdays must be 1 (Mon) … 7 (Sun)")
    try:
        parse_hhmm(req.due_time)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="due_time must be HH:MM")
    if req.default_staff_id is not None:
        get_scoped(db, FieldStaff, p.business_id, req.default_staff_id, "Staff member")
    if len(set(req.shop_ids)) != len(req.shop_ids):
        raise HTTPException(status_code=422, detail="A shop appears twice in the route")
    if req.shop_ids:
        n = db.query(FieldShop.id).filter(
            FieldShop.business_id == p.business_id, FieldShop.id.in_(req.shop_ids)).count()
        if n != len(req.shop_ids):
            raise HTTPException(status_code=404, detail="One or more shops not found")


def _write_route(route: FieldRoute, req: RouteIn, business_id: int) -> None:
    route.name = req.name.strip()
    route.description = req.description
    route.weekdays = ",".join(str(d) for d in sorted(set(req.weekdays)))
    route.default_staff_id = req.default_staff_id
    route.due_time = req.due_time
    route.is_active = req.is_active
    route.stops.clear()
    for i, shop_id in enumerate(req.shop_ids):
        route.stops.append(FieldRouteStop(business_id=business_id, shop_id=shop_id, seq=i + 1))


@router.get("/routes")
def list_routes(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.query(FieldRoute).filter(FieldRoute.business_id == p.business_id).order_by(FieldRoute.name).all()
    return [route_out(r) for r in rows]


@router.post("/routes", status_code=201)
def create_route(req: RouteIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    _validate_route(db, p, req)
    route = FieldRoute(business_id=p.business_id, name=req.name.strip())
    db.add(route)
    _write_route(route, req, p.business_id)
    db.flush()
    log_activity(db, p, "route.create", entity="route", entity_id=route.id,
                 summary=f"{route.name} · {len(req.shop_ids)} shops")
    db.commit()
    db.refresh(route)
    return route_out(route)


@router.put("/routes/{route_id}")
def update_route(route_id: int, req: RouteIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    route = get_scoped(db, FieldRoute, p.business_id, route_id, "Route")
    _validate_route(db, p, req)
    _write_route(route, req, p.business_id)
    log_activity(db, p, "route.update", entity="route", entity_id=route.id, summary=route.name)
    db.commit()
    db.refresh(route)
    return route_out(route)
