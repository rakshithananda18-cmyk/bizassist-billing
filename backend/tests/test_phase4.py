import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Customer, Invoice, PurchaseInvoice, User
from core.billing import commands as billing_commands
from core.purchase import commands as purchase_commands

BID = 880002

def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.drop_all(bind=db.get_bind())
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()

def _clear():
    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(Customer).filter(Customer.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()

@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()

def test_gstr_reports_and_calculations():
    db = SessionLocal()
    try:
        # 0. Create Business User
        user = User(id=BID, username="taxpayer", email="tax@test.com", password="hash", state_code="29", business_name="Test Corp")
        db.add(user)
        db.commit()

        # 1. Create Products
        p1 = Product(business_id=BID, name="Paracetamol", hsn_sac="3004", unit="Strip", selling_price=100.0, cgst_rate=6.0, sgst_rate=6.0, track_inventory=False)
        p2 = Product(business_id=BID, name="Face Mask", hsn_sac="6307", unit="Pcs", selling_price=10.0, cgst_rate=2.5, sgst_rate=2.5, track_inventory=False)
        p3 = Product(business_id=BID, name="Imported Soap", hsn_sac="3401", unit="Nos", selling_price=500.0, igst_rate=18.0, track_inventory=False)
        db.add_all([p1, p2, p3])
        db.commit()
        db.refresh(p1)
        db.refresh(p2)
        db.refresh(p3)

        # 2. Create Customers (B2B and B2C)
        cust_b2b = Customer(business_id=BID, name="MediLife Pharmacy", gstin="29AAACM1234F1Z1", state_code="29")
        cust_b2c = Customer(business_id=BID, name="Walk-in Patient", state_code="29")
        db.add_all([cust_b2b, cust_b2c])
        db.commit()
        db.refresh(cust_b2b)
        db.refresh(cust_b2c)

        # 3. Create Sales Invoices
        # Invoice 1: B2B, local intra-state sales
        inv1 = billing_commands.create_sale_invoice(
            db, business_id=BID,
            customer=cust_b2b.name, customer_id=cust_b2b.id,
            place_of_supply="29-Karnataka",
            lines=[
                {"product_id": p1.id, "quantity": 10.0, "unit_price": p1.selling_price}, # 1000 + 120 tax
                {"product_id": p2.id, "quantity": 20.0, "unit_price": p2.selling_price}  # 200 + 10 tax
            ]
        )

        # Invoice 2: B2C, local intra-state sales
        inv2 = billing_commands.create_sale_invoice(
            db, business_id=BID,
            customer=cust_b2c.name, customer_id=cust_b2c.id,
            place_of_supply="29-Karnataka",
            lines=[
                {"product_id": p1.id, "quantity": 5.0, "unit_price": p1.selling_price} # 500 + 60 tax
            ]
        )

        # Invoice 3: B2C, inter-state sales
        inv3 = billing_commands.create_sale_invoice(
            db, business_id=BID,
            customer=cust_b2c.name, customer_id=cust_b2c.id,
            place_of_supply="27-Maharashtra",
            lines=[
                {"product_id": p3.id, "quantity": 2.0, "unit_price": p3.selling_price} # 1000 + 180 IGST
            ]
        )

        # 4. Create Purchase Invoices (For ITC / Reverse Charge verification)
        # Purchase 1: Regular purchase with ITC (taxable = 1000, IGST = 180)
        purchase_commands.accept_supplier_invoice(db, BID, {
            "supplier_name": "Mega Wholesale",
            "invoice_number": "PUR-101",
            "invoice_date": "2026-06-17",
            "reverse_charge": False,
            "items": [
                {
                    "product_name": "Imported Soap",
                    "quantity": 10,
                    "unit_price": 100.0,
                    "igst_rate": 18.0,
                    "taxable_value": 1000.0,
                    "igst_amount": 180.0,
                    "line_total": 1180.0
                }
            ]
        })

        # Purchase 2: Purchase under Reverse Charge (taxable = 500, CGST=45, SGST=45)
        purchase_commands.accept_supplier_invoice(db, BID, {
            "supplier_name": "Local Transporter",
            "invoice_number": "PUR-102",
            "invoice_date": "2026-06-17",
            "reverse_charge": True,
            "items": [
                {
                    "product_name": "Freight Services",
                    "quantity": 1,
                    "unit_price": 500.0,
                    "cgst_rate": 9.0,
                    "sgst_rate": 9.0,
                    "taxable_value": 500.0,
                    "cgst_amount": 45.0,
                    "sgst_amount": 45.0,
                    "line_total": 590.0
                }
            ]
        })

        # 5. Verify GSTR-1 B2B calculations
        # We simulate report_gstr1_b2b logic directly with DB session
        from core.api.reports import report_gstr1_b2b, report_gstr1_b2cs, report_gstr1_hsn, report_gstr3b
        
        class MockUser:
            def __getitem__(self, key):
                return BID

        current_user = {"id": BID}
        
        b2b = report_gstr1_b2b(current_user=current_user, db=db)
        # Should have 2 rate categories grouped from Invoice 1 (12% and 5%)
        assert len(b2b) == 2
        # Check rates
        rates = [row["tax_rate"] for row in b2b]
        assert 12.0 in rates
        assert 5.0 in rates
        
        for r in b2b:
            assert r["recipient_gstin"] == "29AAACM1234F1Z1"
            if r["tax_rate"] == 12.0:
                assert r["taxable_value"] == 1000.0
                assert r["cgst_amount"] == 60.0
                assert r["sgst_amount"] == 60.0
            elif r["tax_rate"] == 5.0:
                assert r["taxable_value"] == 200.0
                assert r["cgst_amount"] == 5.0
                assert r["sgst_amount"] == 5.0

        # 6. Verify GSTR-1 B2CS calculations
        b2cs = report_gstr1_b2cs(current_user=current_user, db=db)
        # Should have Invoice 2 (POS 29-Karnataka, rate 12%) and Invoice 3 (POS 27-Maharashtra, rate 18%)
        assert len(b2cs) == 2
        pos_rates = [(r["place_of_supply"], r["tax_rate"]) for r in b2cs]
        assert ("29-Karnataka", 12.0) in pos_rates
        assert ("27-Maharashtra", 18.0) in pos_rates
        
        for r in b2cs:
            if r["place_of_supply"] == "29-Karnataka":
                assert r["taxable_value"] == 500.0
                assert r["cgst_amount"] == 30.0
                assert r["sgst_amount"] == 30.0
            elif r["place_of_supply"] == "27-Maharashtra":
                assert r["taxable_value"] == 1000.0
                assert r["igst_amount"] == 180.0

        # 7. Verify GSTR-1 HSN summary
        hsn = report_gstr1_hsn(current_user=current_user, db=db)
        # Products sold: p1 (10 + 5 strips), p2 (20 pcs), p3 (2 nos)
        assert len(hsn) == 3
        hsn_codes = [r["hsn_sac"] for r in hsn]
        assert "3004" in hsn_codes
        assert "6307" in hsn_codes
        assert "3401" in hsn_codes

        for r in hsn:
            if r["hsn_sac"] == "3004":
                assert r["total_quantity"] == 15.0
                assert r["taxable_value"] == 1500.0
            elif r["hsn_sac"] == "3401":
                assert r["total_quantity"] == 2.0
                assert r["taxable_value"] == 1000.0

        # 8. Verify GSTR-3B calculations
        g3b = report_gstr3b(current_user=current_user, db=db)
        g3b_sections = {r["gstr3b_section"]: r for r in g3b}
        
        # 3.1(a) Outward Taxable: taxable = inv1(1200) + inv2(500) + inv3(1000) = 2700.0
        # cgst = 60(inv1) + 10(inv1) + 30(inv2) = 100
        # sgst = 60(inv1) + 10(inv1) + 30(inv2) = 100
        # igst = 180 (inv3)
        sec31a = g3b_sections["3.1(a) Outward Taxable Supplies"]
        assert sec31a["taxable_value"] == 2700.0
        assert sec31a["cgst_amount"] == 95.0
        assert sec31a["sgst_amount"] == 95.0
        assert sec31a["igst_amount"] == 180.0
        
        # 3.1(d) Inward Supplies (Reverse Charge): taxable = 500 (PUR-102), cgst = 45, sgst = 45
        sec31d = g3b_sections["3.1(d) Inward Supplies (Reverse Charge)"]
        assert sec31d["taxable_value"] == 500.0
        assert sec31d["cgst_amount"] == 45.0
        assert sec31d["sgst_amount"] == 45.0
        
        # 4(A)(5) Eligible ITC: regular purchases = PUR-101(IGST 180) + PUR-102(CGST 45, SGST 45) = igst=180, cgst=45, sgst=45
        # Wait, CGST/SGST/IGST of reverse charge purchase is also eligible for ITC.
        sec4a5 = g3b_sections["4(A)(5) Eligible ITC Available"]
        assert sec4a5["igst_amount"] == 180.0
        assert sec4a5["cgst_amount"] == 45.0
        assert sec4a5["sgst_amount"] == 45.0

    finally:
        db.close()
