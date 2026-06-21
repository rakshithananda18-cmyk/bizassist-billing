"""
services/import_data.py — bulk data import service (Phase 1B).
=============================================================
Conforms to append-only and business scoping rules.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from database.models import Product, Customer, Invoice, Vendor
from core.catalog import barcode as PB
from core.stock import ledger as SL

logger = logging.getLogger("bizassist.services.import_data")


def import_products_bulk(db: Session, business_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Bulk import products.
    Creates products and registers barcodes. If opening stock is specified, records it in StockLedger.
    """
    created_count = 0
    errors = []
    
    for idx, item in enumerate(items):
        name = item.get("name", "").strip()
        if not name:
            errors.append(f"Row {idx+1}: Name is required")
            continue
            
        sku = item.get("sku")
        barcode = item.get("barcode")
        unit = item.get("unit") or "Nos"
        description = item.get("description")
        brand = item.get("brand")
        manufacturer = item.get("manufacturer")
        category = item.get("category")
        
        try:
            selling_price = float(item.get("selling_price") or 0.0)
            cost_price = float(item.get("cost_price") or 0.0)
            mrp = float(item.get("mrp")) if item.get("mrp") else None
            cgst_rate = float(item.get("cgst_rate") or 0.0)
            sgst_rate = float(item.get("sgst_rate") or 0.0)
            igst_rate = float(item.get("igst_rate") or 0.0)
            opening_stock = float(item.get("opening_stock") or 0.0)
        except (ValueError, TypeError) as e:
            errors.append(f"Row {idx+1}: Invalid numeric formats: {e}")
            continue

        # Check SKU uniqueness within business
        if sku:
            exists = db.query(Product).filter(Product.business_id == business_id, Product.sku == sku).first()
            if exists:
                errors.append(f"Row {idx+1}: Product with SKU '{sku}' already exists")
                continue

        p = Product(
            business_id=business_id,
            name=name,
            description=description,
            unit=unit,
            sku=sku,
            brand=brand,
            manufacturer=manufacturer,
            category=category,
            selling_price=selling_price,
            cost_price=cost_price,
            mrp=mrp,
            cgst_rate=cgst_rate,
            sgst_rate=sgst_rate,
            igst_rate=igst_rate,
            track_inventory=True,
            is_active=True,
        )
        db.add(p)
        db.flush()  # get p.id

        # Attach barcode
        if barcode:
            try:
                PB.add_barcode(db, business_id, p.id, barcode, make_primary=True, source="import")
            except Exception as e:
                db.rollback()
                errors.append(f"Row {idx+1}: Barcode conflict for '{barcode}': {e}")
                continue

        # Create opening stock movement
        if opening_stock > 0:
            try:
                SL.record_movement(
                    db,
                    business_id=business_id,
                    movement_type=SL.OPENING,
                    qty_delta=opening_stock,
                    product_id=p.id,
                    product_name=p.name,
                    reference_type="import",
                    note="Imported opening stock",
                )
            except Exception as e:
                db.rollback()
                errors.append(f"Row {idx+1}: Failed to record opening stock: {e}")
                continue
                
        created_count += 1
        
    db.commit()
    return {"created": created_count, "errors": errors}


def import_customers_bulk(db: Session, business_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Bulk import customers.
    Creates customer records. If opening_dues is specified, records it as a pending opening invoice.
    """
    created_count = 0
    errors = []
    
    for idx, item in enumerate(items):
        name = item.get("name", "").strip()
        if not name:
            errors.append(f"Row {idx+1}: Name is required")
            continue
            
        phone = item.get("phone")
        email = item.get("email")
        address = item.get("address")
        gstin = item.get("gstin")
        state_code = item.get("state_code")
        pan = item.get("pan")
        
        try:
            credit_limit = float(item.get("credit_limit") or 0.0)
            credit_days = int(item.get("credit_days") or 30)
            opening_dues = float(item.get("opening_dues") or 0.0)
        except (ValueError, TypeError) as e:
            errors.append(f"Row {idx+1}: Invalid formats: {e}")
            continue

        c = Customer(
            business_id=business_id,
            name=name,
            phone=phone,
            email=email,
            address=address,
            gstin=gstin,
            state_code=state_code,
            pan=pan,
            credit_limit=credit_limit,
            credit_days=credit_days,
            is_active=True,
        )
        db.add(c)
        db.flush()  # get c.id

        # Record opening dues as a pending invoice (append-only)
        if opening_dues > 0:
            inv = Invoice(
                business_id=business_id,
                customer_id=c.id,
                customer=c.name,
                invoice_id=f"OPEN-{c.id}",
                amount=opening_dues,
                total_amount=opening_dues,
                paid_amount=0.0,
                status="Pending",
                invoice_type="opening_due",
                invoice_date=datetime.today().strftime("%Y-%m-%d"),
                due_date=datetime.today().strftime("%Y-%m-%d"),
                notes="Imported opening outstanding dues",
            )
            db.add(inv)
            
        created_count += 1
        
    db.commit()
    return {"created": created_count, "errors": errors}


def import_vendors_bulk(db: Session, business_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Bulk import vendors.
    """
    created_count = 0
    errors = []
    
    for idx, item in enumerate(items):
        name = item.get("name", "").strip()
        if not name:
            errors.append(f"Row {idx+1}: Name is required")
            continue
            
        phone = item.get("phone")
        email = item.get("email")
        address = item.get("address")
        gstin = item.get("gstin")
        state_code = item.get("state_code")
        pan = item.get("pan")
        
        try:
            payment_terms_days = int(item.get("payment_terms_days") or 30)
        except (ValueError, TypeError) as e:
            errors.append(f"Row {idx+1}: Invalid payment terms days: {e}")
            continue

        v = Vendor(
            business_id=business_id,
            name=name,
            phone=phone,
            email=email,
            address=address,
            gstin=gstin,
            state_code=state_code,
            pan=pan,
            payment_terms_days=payment_terms_days,
            is_active=True,
        )
        db.add(v)
        created_count += 1
        
    db.commit()
    return {"created": created_count, "errors": errors}
