"""
tests/test_universal_schema.py
==============================
Proves the catalogue + invoice schema fits EVERY business type, and that the
GST-mandatory `reverse_charge` field exists. Each vertical creates a product
using only the fields it needs; vertical-specific extras go in `attributes`
(JSON) with NO schema change.

Pure DB unit test.
"""
import os
import sys
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem

BID = 990003


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(InvoiceLineItem).filter(
            InvoiceLineItem.invoice_id.in_(
                db.query(Invoice.id).filter(Invoice.business_id == BID))).delete(synchronize_session=False)
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()


def test_every_business_type_fits_one_product_table():
    """One products table serves retail, wholesale, pharmacy, garments,
    restaurant, and services — each using only the fields it needs."""
    db = SessionLocal()
    try:
        products = [
            # Retail / supermarket — loose qty, MRP-inclusive pricing
            Product(business_id=BID, name="Loose Rice", unit="Kg",
                    price_includes_tax=True, mrp=60, category="Grocery"),
            # Wholesale / distributor — buy carton, stock pieces (conversion)
            Product(business_id=BID, name="Biscuits Pack", unit="Nos",
                    purchase_unit="Carton", conversion_factor=48, sku="BISC-48"),
            # Pharmacy — vertical fields in attributes (no schema change)
            Product(business_id=BID, name="Paracetamol 500", unit="Strip",
                    hsn_sac="3004",
                    attributes=json.dumps({"drug_schedule": "H", "salt": "Paracetamol"})),
            # Garments — a variant of a parent, attributes hold size/colour
            Product(business_id=BID, name="T-Shirt - M / Blue",
                    attributes=json.dumps({"size": "M", "colour": "Blue"})),
            # Restaurant — prepared food, NOT stock-tracked, a service-ish item
            Product(business_id=BID, name="Masala Dosa", unit="Plate",
                    track_inventory=False, is_service=False, category="Food"),
            # Services — SAC, no stock
            Product(business_id=BID, name="Tailoring Service", unit="Job",
                    is_service=True, track_inventory=False, hsn_sac="9988"),
            # Electronics — serial/IMEI via attributes + brand/manufacturer
            Product(business_id=BID, name="Phone X", brand="Acme",
                    manufacturer="Acme Pvt", attributes=json.dumps({"warranty_months": 12})),
        ]
        db.add_all(products)
        db.commit()

        rows = db.query(Product).filter(Product.business_id == BID).all()
        assert len(rows) == 7
        # vertical fields round-trip
        pharma = next(p for p in rows if p.name.startswith("Paracetamol"))
        assert json.loads(pharma.attributes)["drug_schedule"] == "H"
        whole = next(p for p in rows if p.sku == "BISC-48")
        assert whole.purchase_unit == "Carton" and whole.conversion_factor == 48
        food = next(p for p in rows if p.name == "Masala Dosa")
        assert food.track_inventory is False
    finally:
        db.close()


def test_invoice_has_gst_reverse_charge_and_universal_fields():
    """GST Rule-46 reverse_charge + retail tax-inclusive + round_off exist and persist."""
    db = SessionLocal()
    try:
        inv = Invoice(
            business_id=BID, invoice_id="INV-UNIV-1", customer="Test Buyer",
            amount=118.0, status="Paid",
            reverse_charge=True, is_tax_inclusive=True,
            discount_total=2.0, round_off=0.5,
            place_of_supply="29-Karnataka", invoice_type="B2B",
        )
        db.add(inv)
        db.commit()
        got = db.query(Invoice).filter(Invoice.business_id == BID,
                                       Invoice.invoice_id == "INV-UNIV-1").first()
        assert got.reverse_charge is True
        assert got.is_tax_inclusive is True
        assert got.round_off == 0.5
        assert got.discount_total == 2.0
    finally:
        db.close()


def test_line_item_supports_batch_and_serial():
    db = SessionLocal()
    try:
        inv = Invoice(business_id=BID, invoice_id="INV-UNIV-2", customer="B", amount=10)
        db.add(inv)
        db.commit()
        li = InvoiceLineItem(invoice_id=inv.id, product_name="Paracetamol 500",
                             quantity=2, unit_price=5, batch_no="B12", serial_no=None,
                             description="strip of 10")
        db.add(li)
        db.commit()
        got = db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id == inv.id).first()
        assert got.batch_no == "B12" and got.description == "strip of 10"
    finally:
        db.close()
