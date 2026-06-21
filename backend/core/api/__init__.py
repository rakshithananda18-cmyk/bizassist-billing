"""
core.api — the billing ecosystem's HTTP layer.
==============================================
All of core's routes (sales counter, business templates, and future
purchase/connection/order endpoints) are aggregated here into ONE `core_router`.

The app entry point mounts the whole ecosystem with a single line —
`app.include_router(core_router)` — and never imports individual billing routes.
That is the "billing is wired from core, not from the entry point" boundary: to
add a core endpoint, include its router HERE; the entry point doesn't change.
"""
from fastapi import APIRouter

from core.api.sales import router as sales_router
from core.api.business import router as business_router
from core.api.products import router as products_router
from core.api.parties import router as parties_router
from core.api.payments import router as payments_router
from core.api.reports import router as reports_router
from core.api.import_route import router as import_router
from core.api.purchases import router as purchases_router
from core.api.connections import router as connections_router
from core.api.orders import router as orders_router
from core.api.godowns import router as godowns_router
from core.api.transfers import router as transfers_router
from core.api.staff import router as staff_router
from core.api.period_lock import router as period_lock_router
from core.api.compliance import router as compliance_router

core_router = APIRouter()
core_router.include_router(sales_router)
core_router.include_router(business_router)
core_router.include_router(products_router)
core_router.include_router(parties_router)
core_router.include_router(payments_router)
core_router.include_router(reports_router)
core_router.include_router(import_router)
core_router.include_router(purchases_router)
core_router.include_router(connections_router)
core_router.include_router(connections_router, prefix="/connections")
core_router.include_router(orders_router)
core_router.include_router(orders_router, prefix="/connections")
core_router.include_router(godowns_router)
core_router.include_router(transfers_router)
core_router.include_router(staff_router)
core_router.include_router(period_lock_router)
core_router.include_router(compliance_router)

__all__ = ["core_router"]
