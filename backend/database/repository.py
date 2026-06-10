"""
database/repository.py
======================
Repository pattern for BizAssist.

SOLID principles applied:
  - Single Responsibility : each repository owns DB access for one domain.
  - Open/Closed           : add new query methods without touching BaseRepository.
  - Liskov Substitution   : any concrete repo can be swapped for BaseRepository[T].
  - Interface Segregation : repos expose only domain-relevant methods.
  - Dependency Inversion  : services receive a repository; never call SessionLocal directly.

Usage
-----
    from database.repository import InvoiceRepository
    from database.db import SessionLocal

    db = SessionLocal()
    repo = InvoiceRepository(db)
    overdue = repo.get_overdue(business_id=1)
    db.close()

  Or with a context manager:
    with SessionLocal() as db:
        repo = InvoiceRepository(db)
        ...
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Generic, List, Optional, Type, TypeVar

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.dates import parse_date

from database.models import (
    Invoice, InvoiceLineItem,
    Customer, Vendor, Product,
    Inventory, Payment,
    PurchaseOrder,
)

logger = logging.getLogger("bizassist.repository")

# Generic type bound to SQLAlchemy Base models
T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────────────
# BASE REPOSITORY  (Open/Closed — never modify, only extend)
# ─────────────────────────────────────────────────────────────────────────────

class BaseRepository(Generic[T]):
    """
    Generic CRUD repository.  Concrete repositories inherit and add
    domain-specific query methods on top.

    All methods filter by business_id — enforces multi-tenant isolation.
    """

    def __init__(self, db: Session, model: Type[T]):
        self._db    = db
        self._model = model

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self, record_id: int, business_id: int) -> Optional[T]:
        """Fetch a single record by PK, scoped to the business."""
        return (
            self._db.query(self._model)
            .filter(
                self._model.id == record_id,
                self._model.business_id == business_id,
            )
            .first()
        )

    def get_all(self, business_id: int, limit: int = 100, offset: int = 0) -> List[T]:
        """Return all records for a business, paginated."""
        return (
            self._db.query(self._model)
            .filter(self._model.business_id == business_id)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count(self, business_id: int) -> int:
        return (
            self._db.query(func.count(self._model.id))
            .filter(self._model.business_id == business_id)
            .scalar() or 0
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, obj: T) -> T:
        """Persist a new record and return it with its generated id."""
        try:
            self._db.add(obj)
            self._db.flush()   # assigns id without committing — caller controls commit
            return obj
        except Exception as e:
            self._db.rollback()
            logger.error(f"[{self._model.__name__}] create failed: {e}", exc_info=True)
            raise

    def update(self, obj: T) -> T:
        """Flush pending changes for an already-tracked object."""
        try:
            self._db.flush()
            return obj
        except Exception as e:
            self._db.rollback()
            logger.error(f"[{self._model.__name__}] update failed: {e}", exc_info=True)
            raise

    def delete(self, record_id: int, business_id: int) -> bool:
        """Hard-delete a record scoped to the business. Returns True if found."""
        obj = self.get(record_id, business_id)
        if not obj:
            return False
        try:
            self._db.delete(obj)
            self._db.flush()
            return True
        except Exception as e:
            self._db.rollback()
            logger.error(f"[{self._model.__name__}] delete failed: {e}", exc_info=True)
            raise

    def commit(self):
        """Explicit commit — call after one or more create/update/delete ops."""
        self._db.commit()

    def rollback(self):
        self._db.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# INVOICE REPOSITORY
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceRepository(BaseRepository[Invoice]):

    def __init__(self, db: Session):
        super().__init__(db, Invoice)

    def get_by_status(self, business_id: int, status: str) -> List[Invoice]:
        return (
            self._db.query(Invoice)
            .filter(Invoice.business_id == business_id, Invoice.status == status)
            .order_by(Invoice.amount.desc())
            .all()
        )

    def get_overdue(self, business_id: int, limit: int = 50) -> List[Invoice]:
        return (
            self._db.query(Invoice)
            .filter(Invoice.business_id == business_id, Invoice.status == "Overdue")
            .order_by(Invoice.amount.desc())
            .limit(limit)
            .all()
        )

    def get_pending(self, business_id: int, limit: int = 50) -> List[Invoice]:
        return (
            self._db.query(Invoice)
            .filter(Invoice.business_id == business_id, Invoice.status == "Pending")
            .order_by(Invoice.due_date.asc())
            .limit(limit)
            .all()
        )

    def get_by_customer(self, business_id: int, customer_name: str) -> List[Invoice]:
        return (
            self._db.query(Invoice)
            .filter(
                Invoice.business_id == business_id,
                Invoice.customer.ilike(f"%{customer_name}%"),
            )
            .order_by(Invoice.invoice_date.desc())
            .all()
        )

    def revenue_summary(self, business_id: int) -> dict:
        """Aggregate revenue figures — used by handlers and context cache."""
        q = self._db.query(Invoice).filter(Invoice.business_id == business_id)
        total   = q.with_entities(func.sum(Invoice.amount)).scalar() or 0
        paid    = q.filter(Invoice.status == "Paid").with_entities(func.sum(Invoice.amount)).scalar() or 0
        pending = q.filter(Invoice.status == "Pending").with_entities(func.sum(Invoice.amount)).scalar() or 0
        overdue = q.filter(Invoice.status == "Overdue").with_entities(func.sum(Invoice.amount)).scalar() or 0
        return {
            "total":            total,
            "paid":             paid,
            "pending":          pending,
            "overdue":          overdue,
            "collection_rate":  round((paid / total) * 100, 1) if total else 0,
        }

    def top_customers(self, business_id: int, limit: int = 10) -> List[tuple]:
        """Returns (customer_name, total_revenue) sorted desc."""
        return (
            self._db.query(Invoice.customer, func.sum(Invoice.amount).label("total"))
            .filter(Invoice.business_id == business_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(limit)
            .all()
        )

    def top_debtors(self, business_id: int, limit: int = 10) -> List[tuple]:
        """Returns (customer_name, overdue_amount) sorted desc."""
        return (
            self._db.query(Invoice.customer, func.sum(Invoice.amount).label("overdue_total"))
            .filter(Invoice.business_id == business_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(limit)
            .all()
        )

    def mark_paid(self, record_id: int, business_id: int,
                  paid_amount: float = None, payment_mode: str = "Cash") -> Optional[Invoice]:
        """Mark an invoice as Paid. Uses full invoice amount if paid_amount not given."""
        inv = self.get(record_id, business_id)
        if not inv:
            return None
        inv.status       = "Paid"
        inv.paid_amount  = paid_amount if paid_amount is not None else inv.amount
        inv.payment_date = datetime.utcnow().strftime("%Y-%m-%d")
        inv.payment_mode = payment_mode
        self._db.flush()
        return inv


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER REPOSITORY
# ─────────────────────────────────────────────────────────────────────────────

class CustomerRepository(BaseRepository[Customer]):

    def __init__(self, db: Session):
        super().__init__(db, Customer)

    def search(self, business_id: int, query: str) -> List[Customer]:
        return (
            self._db.query(Customer)
            .filter(
                Customer.business_id == business_id,
                Customer.is_active == True,
                Customer.name.ilike(f"%{query}%"),
            )
            .order_by(Customer.name)
            .all()
        )

    def get_by_name(self, business_id: int, name: str) -> Optional[Customer]:
        return (
            self._db.query(Customer)
            .filter(
                Customer.business_id == business_id,
                Customer.name == name,
            )
            .first()
        )

    def get_with_outstanding(self, business_id: int) -> List[dict]:
        """Returns customers who have overdue invoices with totals."""
        rows = (
            self._db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("overdue_total"),
                func.count(Invoice.id).label("invoice_count"),
            )
            .filter(Invoice.business_id == business_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .all()
        )
        return [
            {"customer": r.customer, "overdue_total": r.overdue_total, "invoice_count": r.invoice_count}
            for r in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# VENDOR REPOSITORY
# ─────────────────────────────────────────────────────────────────────────────

class VendorRepository(BaseRepository[Vendor]):

    def __init__(self, db: Session):
        super().__init__(db, Vendor)

    def search(self, business_id: int, query: str) -> List[Vendor]:
        return (
            self._db.query(Vendor)
            .filter(
                Vendor.business_id == business_id,
                Vendor.is_active == True,
                Vendor.name.ilike(f"%{query}%"),
            )
            .all()
        )

    def get_unreliable_filers(self, business_id: int, threshold: float = 0.7) -> List[Vendor]:
        """Returns vendors whose GST filing reliability is below the threshold."""
        return (
            self._db.query(Vendor)
            .filter(
                Vendor.business_id == business_id,
                Vendor.filing_reliability < threshold,
                Vendor.filing_reliability.isnot(None),
            )
            .order_by(Vendor.filing_reliability.asc())
            .all()
        )


# ─────────────────────────────────────────────────────────────────────────────
# INVENTORY REPOSITORY
# ─────────────────────────────────────────────────────────────────────────────

class InventoryRepository(BaseRepository[Inventory]):

    def __init__(self, db: Session):
        super().__init__(db, Inventory)

    def get_low_stock(self, business_id: int, threshold: int = None) -> List[Inventory]:
        """Returns items at or below their reorder_point (or explicit threshold)."""
        q = self._db.query(Inventory).filter(Inventory.business_id == business_id)
        if threshold is not None:
            return q.filter(Inventory.stock <= threshold).order_by(Inventory.stock.asc()).all()
        # Use per-item reorder_point when available, fallback to 10
        items = q.all()
        return [
            i for i in items
            if i.stock is not None and i.stock <= (i.reorder_point or 10)
        ]

    def get_expiring(self, business_id: int, within_days: int = 30) -> List[Inventory]:
        """Returns items expiring within the given window."""
        today = datetime.today()
        cutoff = today + timedelta(days=within_days)
        items = self._db.query(Inventory).filter(Inventory.business_id == business_id).all()
        expiring = []
        for item in items:
            exp = parse_date(item.expiry_date)
            if exp is None:
                continue
            if today <= exp <= cutoff:
                expiring.append(item)
        return sorted(expiring, key=lambda i: str(i.expiry_date))

    def adjust_stock(self, record_id: int, business_id: int,
                     delta: int, reason: str = "") -> Optional[Inventory]:
        """Add or subtract stock. delta can be negative (e.g. damage write-off)."""
        item = self.get(record_id, business_id)
        if not item:
            return None
        item.stock = (item.stock or 0) + delta
        self._db.flush()
        return item


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT REPOSITORY
# ─────────────────────────────────────────────────────────────────────────────

class ProductRepository(BaseRepository[Product]):

    def __init__(self, db: Session):
        super().__init__(db, Product)

    def search(self, business_id: int, query: str) -> List[Product]:
        return (
            self._db.query(Product)
            .filter(
                Product.business_id == business_id,
                Product.is_active == True,
                Product.name.ilike(f"%{query}%"),
            )
            .order_by(Product.name)
            .all()
        )

    def get_by_barcode(self, business_id: int, barcode: str) -> Optional[Product]:
        return (
            self._db.query(Product)
            .filter(Product.business_id == business_id, Product.barcode == barcode)
            .first()
        )

    def get_by_hsn(self, business_id: int, hsn: str) -> List[Product]:
        return (
            self._db.query(Product)
            .filter(Product.business_id == business_id, Product.hsn_sac == hsn)
            .all()
        )


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE ORDER REPOSITORY
# ─────────────────────────────────────────────────────────────────────────────

class PurchaseOrderRepository(BaseRepository[PurchaseOrder]):

    def __init__(self, db: Session):
        super().__init__(db, PurchaseOrder)

    def get_by_status(self, business_id: int, status: str) -> List[PurchaseOrder]:
        return (
            self._db.query(PurchaseOrder)
            .filter(PurchaseOrder.business_id == business_id, PurchaseOrder.status == status)
            .order_by(PurchaseOrder.po_date.desc())
            .all()
        )

    def get_pending_receipts(self, business_id: int) -> List[PurchaseOrder]:
        """POs that have been sent but not yet received."""
        return self.get_by_status(business_id, "Sent")
