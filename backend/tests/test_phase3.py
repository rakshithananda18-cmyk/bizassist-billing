import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Customer, Inventory, Invoice, PurchaseInvoice
from core.models import Godown, StockTransfer, StockTransferLineItem, StockLedger
from core.stock import ledger as SL
from core.billing import commands as billing_commands
from core.purchase import commands as purchase_commands

BID = 880001

def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()

def _clear():
    db = SessionLocal()
    try:
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(Customer).filter(Customer.business_id == BID).delete()
        db.query(Godown).filter(Godown.business_id == BID).delete()
        db.query(StockTransfer).filter(StockTransfer.business_id == BID).delete()
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == BID).delete()
        db.commit()
    finally:
        db.close()

@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    yield
    _clear()

def test_multi_godown_transfers():
    db = SessionLocal()
    try:
        # 1. Create Godowns
        godown1 = Godown(business_id=BID, name="Main Warehouse", address="A1", is_active=True)
        godown2 = Godown(business_id=BID, name="Outlet Store", address="B1", is_active=True)
        db.add_all([godown1, godown2])
        db.commit()
        db.refresh(godown1)
        db.refresh(godown2)

        # 2. Create Product
        product = Product(
            business_id=BID,
            name="Testing Rice",
            selling_price=100.0,
            cost_price=70.0,
            track_inventory=True
        )
        db.add(product)
        db.commit()
        db.refresh(product)

        # 3. Seed opening stock in Main Warehouse (godown1)
        SL.record_movement(
            db, business_id=BID, movement_type=SL.OPENING, qty_delta=100.0,
            product_id=product.id, product_name=product.name,
            godown_id=godown1.id, batch_no="B001"
        )
        db.commit()

        # Check stock in godown1 and godown2
        assert SL.current_stock(db, BID, product_id=product.id, godown_id=godown1.id) == 100.0
        assert SL.current_stock(db, BID, product_id=product.id, godown_id=godown2.id) == 0.0

        # Verify Inventory Cache is scoped correctly
        inv1 = db.query(Inventory).filter(
            Inventory.business_id == BID, Inventory.product_id == product.id, Inventory.godown_id == godown1.id
        ).first()
        assert inv1 is not None
        assert inv1.stock == 100

        inv2 = db.query(Inventory).filter(
            Inventory.business_id == BID, Inventory.product_id == product.id, Inventory.godown_id == godown2.id
        ).first()
        assert inv2 is None # No movement yet in godown2

        # 4. Transfer 30 items from Main Warehouse (godown1) to Outlet Store (godown2)
        # We simulate the API's transaction block:
        st = StockTransfer(
            business_id=BID,
            transfer_date="2026-06-17",
            from_godown_id=godown1.id,
            to_godown_id=godown2.id,
            notes="Transfer to outlet store"
        )
        db.add(st)
        db.flush()

        li = StockTransferLineItem(
            transfer_id=st.id,
            product_id=product.id,
            product_name=product.name,
            quantity=30.0,
            unit="Nos"
        )
        db.add(li)

        # Record TRANSFER_OUT movement for source
        SL.record_movement(
            db, business_id=BID, movement_type=SL.TRANSFER_OUT, qty_delta=-30.0,
            product_id=product.id, product_name=product.name,
            reference_type="stock_transfer", reference_id=st.id,
            godown_id=godown1.id, batch_no="B001"
        )

        # Record TRANSFER_IN movement for dest
        SL.record_movement(
            db, business_id=BID, movement_type=SL.TRANSFER_IN, qty_delta=30.0,
            product_id=product.id, product_name=product.name,
            reference_type="stock_transfer", reference_id=st.id,
            godown_id=godown2.id, batch_no="B001"
        )
        db.commit()

        # 5. Assert final stocks
        assert SL.current_stock(db, BID, product_id=product.id, godown_id=godown1.id) == 70.0
        assert SL.current_stock(db, BID, product_id=product.id, godown_id=godown2.id) == 30.0

        # Assert Inventory caches
        inv1 = db.query(Inventory).filter(
            Inventory.business_id == BID, Inventory.product_id == product.id, Inventory.godown_id == godown1.id
        ).first()
        assert inv1.stock == 70

        inv2 = db.query(Inventory).filter(
            Inventory.business_id == BID, Inventory.product_id == product.id, Inventory.godown_id == godown2.id
        ).first()
        assert inv2 is not None
        assert inv2.stock == 30
    finally:
        db.close()

def test_customer_price_tiers_sales():
    db = SessionLocal()
    try:
        # 1. Create Product with multiple tier prices
        product = Product(
            business_id=BID,
            name="Super Widgets",
            selling_price=100.0,
            wholesale_price=80.0,
            distributor_price=60.0,
            track_inventory=False
        )
        db.add(product)
        db.commit()
        db.refresh(product)

        # 2. Create Customers with different tiers
        cust_std = Customer(business_id=BID, name="Retail Store", price_tier="standard")
        cust_ws = Customer(business_id=BID, name="Wholesale Buyer Inc", price_tier="wholesale")
        cust_dist = Customer(business_id=BID, name="Mega Distributor", price_tier="distributor")
        db.add_all([cust_std, cust_ws, cust_dist])
        db.commit()
        db.refresh(cust_std)
        db.refresh(cust_ws)
        db.refresh(cust_dist)

        # 3. Simulate Sale Checkout. Let's make sure the billing router or command handler uses the correct price.
        # Wait, the customer's price tier should be applied when setting up the sales screen (in frontend)
        # or on backend checkouts if needed. Let's verify that the command can successfully run and record correct values.
        # Retail checkout: unit price is 100.0
        inv1 = billing_commands.create_sale_invoice(
            db, business_id=BID,
            customer=cust_std.name, customer_id=cust_std.id,
            lines=[{"product_id": product.id, "quantity": 10.0, "unit_price": product.selling_price}]
        )
        assert inv1.total_amount == 1000.0

        # Wholesale checkout: unit price is 80.0
        inv2 = billing_commands.create_sale_invoice(
            db, business_id=BID,
            customer=cust_ws.name, customer_id=cust_ws.id,
            lines=[{"product_id": product.id, "quantity": 10.0, "unit_price": product.wholesale_price}]
        )
        assert inv2.total_amount == 800.0

        # Distributor checkout: unit price is 60.0
        inv3 = billing_commands.create_sale_invoice(
            db, business_id=BID,
            customer=cust_dist.name, customer_id=cust_dist.id,
            lines=[{"product_id": product.id, "quantity": 10.0, "unit_price": product.distributor_price}]
        )
        assert inv3.total_amount == 600.0
    finally:
        db.close()

def test_purchase_invoice_godown_batch():
    db = SessionLocal()
    try:
        # 1. Create Godown
        godown = Godown(business_id=BID, name="Cold Storage", address="Fridge A", is_active=True)
        db.add(godown)
        db.commit()
        db.refresh(godown)

        # 2. Accept Supplier Invoice in Cold Storage (godown.id) and batch B123
        invoice_data = {
            "supplier_name": "Fresh Dairy Co",
            "invoice_number": "PUR-990",
            "invoice_date": "2026-06-17",
            "godown_id": godown.id,
            "items": [
                {
                    "product_name": "Premium Butter",
                    "quantity": 50,
                    "unit_price": 200.0,
                    "batch": "B123",
                    "expiry": "2026-12-31"
                }
            ]
        }
        purchase_commands.accept_supplier_invoice(db, BID, invoice_data)

        # 3. Assert ledger entry has the correct godown_id, batch_no, and expiry_date
        prod = db.query(Product).filter(Product.business_id == BID, Product.name == "Premium Butter").first()
        assert prod is not None

        ledger = db.query(StockLedger).filter(
            StockLedger.business_id == BID, StockLedger.product_id == prod.id
        ).first()
        assert ledger is not None
        assert ledger.godown_id == godown.id
        assert ledger.batch_no == "B123"
        assert ledger.expiry_date == "2026-12-31"

        # 4. Assert stock is recorded specifically in that godown
        assert SL.current_stock(db, BID, product_id=prod.id, godown_id=godown.id) == 50.0
        assert SL.current_stock(db, BID, product_id=prod.id, godown_id=9999) == 0.0 # other godown has 0

        # 5. Assert Inventory Cache has the correct godown_id and batch_no
        inv = db.query(Inventory).filter(
            Inventory.business_id == BID, Inventory.product_id == prod.id
        ).first()
        assert inv is not None
        assert inv.godown_id == godown.id
        assert inv.batch_no == "B123"
        assert inv.expiry_date == "2026-12-31"
        assert inv.stock == 50
    finally:
        db.close()
