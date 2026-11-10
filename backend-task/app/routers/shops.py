"""
routers/shops.py — delivery points (retail / medical shops) and route templates.
Shops can be imported from the owner's BizAssist Billing customers, or linked
to one later, by `customer_id`; a linked shop lists that customer's billing
invoices for planning deliveries and collections (app/invoices.py).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.billing_models import BillingCustomer
from app.db import get_db
from app.invoices import shop_invoices
from app.models import FieldRoute, FieldRouteStop, FieldShop, FieldStaff, FieldTask, FieldTaskInvoice
from app.security import Principal, current_principal, require_owner
from app.services import get_scoped, log_activity, prime_billing_reads, route_out, shop_out
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
    customer_id: Optional[int] = Field(None, description="Billing customer to link; null unlinks")


def _apply_shop(shop: FieldShop, req: ShopIn, *, partial: bool) -> None:
    data = req.model_dump(exclude_unset=partial, exclude={"customer_id"})
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
    rows = q.order_by(FieldShop.name.asc()).all()
    prime_billing_reads(shops=rows)
    return sorted((shop_out(s) for s in rows), key=lambda s: (s["name"] or "").casefold())


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


def _link_customer(db: Session, p: Principal, shop: FieldShop, customer_id: Optional[int]) -> None:
    if customer_id != shop.customer_id:
        pending = (db.query(FieldTask.id).join(FieldTaskInvoice, FieldTaskInvoice.task_id == FieldTask.id)
                   .filter(FieldTask.business_id == p.business_id, FieldTask.shop_id == shop.id,
                           FieldTask.status == "pending").first())
        if pending:
            raise HTTPException(status_code=409,
                                detail="Complete or cancel this shop's pending invoice tasks before changing its billing customer")
        # Collected cash still awaiting Billing approval belongs to the original
        # customer, even though the staff task itself has already finished.
        from app.collections import confirmed_in_billing
        awaiting = (db.query(FieldTask).filter(FieldTask.business_id == p.business_id,
                    FieldTask.shop_id == shop.id, FieldTask.task_type == "payment_collect",
                    FieldTask.status == "done", FieldTask.amount_collected > 0).all())
        confirmed = confirmed_in_billing(db, p.business_id, [task.uid for task in awaiting])
        if any(float(task.amount_collected or 0) - confirmed.get(task.uid, 0) > 0.005 for task in awaiting):
            raise HTTPException(status_code=409, detail="Confirm this shop's collected money in Billing before changing its billing customer")
    if customer_id is None:
        # Keep the current contact identity as a field-owned snapshot on unlink.
        current = (db.query(BillingCustomer).filter(BillingCustomer.business_id == p.business_id,
                                                   BillingCustomer.id == shop.customer_id).first())
        if current:
            shop.name = current.name or f"Customer {current.id}"
            shop.phone, shop.address = current.phone, current.address
        shop.customer_id = None
        return
    customer = (db.query(BillingCustomer)
                .filter(BillingCustomer.business_id == p.business_id, BillingCustomer.id == customer_id).first())
    if customer is None:
        raise HTTPException(status_code=404, detail="Billing customer not found")
    other = (db.query(FieldShop.name)
             .filter(FieldShop.business_id == p.business_id, FieldShop.customer_id == customer_id,
                     FieldShop.id != shop.id).first())
    if other:
        raise HTTPException(status_code=409, detail=f"{customer.name} is already linked to {other.name}")
    shop.customer_id = customer_id
    shop.name = customer.name or f"Customer {customer.id}"
    shop.phone, shop.address = customer.phone, customer.address


@router.patch("/shops/{shop_id}")
def update_shop(shop_id: int, req: ShopPatch, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    shop = get_scoped(db, FieldShop, p.business_id, shop_id, "Shop")
    if "customer_id" in req.model_fields_set:
        _link_customer(db, p, shop, req.customer_id)
    data = req.model_dump(exclude_unset=True)
    if shop.customer_id is not None:
        customer = (db.query(BillingCustomer).filter(BillingCustomer.business_id == p.business_id,
                                                    BillingCustomer.id == shop.customer_id).first())
        for key in ("name", "phone", "address"):
            canonical = (customer.name or f"Customer {customer.id}") if key == "name" and customer else getattr(customer, key, None)
            supplied = data.get(key)
            if key in data and (supplied or "").strip() != (canonical or "").strip():
                raise HTTPException(status_code=422, detail="Linked customer name, phone and address are managed in BizAssist Billing")
        data = {k: v for k, v in data.items() if k not in ("name", "phone", "address")}
    _apply_shop(shop, ShopPatch.model_validate(data), partial=True)
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


@router.get("/shops/{shop_id}/billing-invoices")
def billing_invoices(shop_id: int, days: int = Query(30, ge=1, le=365),
                     p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """The linked billing customer's invoices: the last `days` days plus any
    older one still unpaid. Each lists the live tasks that already carry it."""
    shop = get_scoped(db, FieldShop, p.business_id, shop_id, "Shop")
    return {"shop_id": shop.id, "customer_id": shop.customer_id, "days": days,
            "invoices": shop_invoices(db, p.business_id, shop, days)}


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
    prime_billing_reads(shops=[stop.shop for route in rows for stop in route.stops])
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
