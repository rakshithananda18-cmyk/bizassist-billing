#!/usr/bin/env python3
"""
seed_load_test.py
=================
Seeds the database with a large number of invoices (10k-50k) to load-test performance.
Includes stock movement records and journal entry postings (R3 hash chain).
"""
import os
import sys
import random
import argparse
import time
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import SessionLocal
from database.models import User, Product, Customer
from core.stock import ledger as SL
from core.billing.commands import create_sale_invoice

def get_or_create_entities(db: Session, business_id: int):
    # 1. Ensure business user exists
    biz = db.query(User).filter(User.id == business_id).first()
    if not biz:
        print(f"Creating test business user with ID {business_id}...")
        biz = User(
            id=business_id,
            username=f"test_biz_{business_id}",
            password="pbkdf2:sha256:260000$xxxx$testpassword",
            business_name=f"Load Test Shop {business_id}",
            state_code="29",  # Karnataka (INTRA-state GST by default)
            role="enterprise",
        )
        db.add(biz)
        db.commit()
        db.refresh(biz)
    
    # 2. Ensure we have products
    products = db.query(Product).filter(Product.business_id == business_id).all()
    if not products:
        print("No products found. Creating 10 sample products...")
        product_names = [
            "Basmati Rice 25kg", "Sunflower Oil 15L", "Sugar 50kg", "Wheat Flour 10kg",
            "Toor Dal 5kg", "Tea Leaves 1kg", "Coffee Powder 500g", "Detergent Powder 3kg",
            "Colgate Toothpaste", "Soap Bar 100g"
        ]
        products = []
        for i, name in enumerate(product_names):
            p = Product(
                business_id=business_id,
                name=name,
                selling_price=100.0 + (i * 50.0),
                cost_price=70.0 + (i * 35.0),
                mrp=120.0 + (i * 60.0),
                cgst_rate=6.0,
                sgst_rate=6.0,
                igst_rate=0.0,
                track_inventory=True,
                is_active=True
            )
            db.add(p)
        db.commit()
        products = db.query(Product).filter(Product.business_id == business_id).all()
        
        # Add opening stock
        for p in products:
            SL.record_movement(
                db,
                business_id=business_id,
                movement_type=SL.OPENING,
                qty_delta=100000.0,
                product_id=p.id,
                product_name=p.name,
                note="Load test opening stock"
            )
        db.commit()
        print(f"Sample products created with 100k opening stock each.")

    # 3. Ensure we have customers
    customers = db.query(Customer).filter(Customer.business_id == business_id).all()
    if not customers:
        print("No customers found. Creating 5 sample customers...")
        cust_names = ["Nilgiris Fresh", "Star Bazaar", "Daily Needs Store", "More Supermarket", "Rahul Traders"]
        for name in cust_names:
            c = Customer(
                business_id=business_id,
                name=name,
                gstin="29TESTC1234A1Z0",
                state_code="29",
                is_active=True
            )
            db.add(c)
        db.commit()
        customers = db.query(Customer).filter(Customer.business_id == business_id).all()

    return products, customers

def seed_load_test(business_id: int, count: int):
    db = SessionLocal()
    try:
        # Detect SQLite and apply speed-up PRAGMAs
        db_type = db.bind.url.drivername
        is_sqlite = "sqlite" in db_type
        if is_sqlite:
            print("SQLite detected. Optimizing connection for fast seeding...")
            db.execute(text("PRAGMA synchronous = OFF"))
            db.execute(text("PRAGMA journal_mode = OFF"))
            db.execute(text("PRAGMA cache_size = 100000"))
        
        products, customers = get_or_create_entities(db, business_id)
        
        print(f"Starting seeding of {count} invoices for business {business_id}...")
        start_time = time.time()
        
        # Calculate dates spread over 365 days
        today = datetime.today()
        
        # Prepare list of standard invoices
        for i in range(1, count + 1):
            inv_date = today - timedelta(days=random.randint(0, 365))
            inv_date_str = inv_date.strftime("%Y-%m-%d")
            
            customer = random.choice(customers)
            
            # Select 1 to 3 items
            num_items = random.randint(1, 3)
            invoice_products = random.sample(products, num_items)
            
            lines = []
            for p in invoice_products:
                lines.append({
                    "product_id": p.id,
                    "product_name": p.name,
                    "quantity": float(random.randint(1, 5)),
                    "unit_price": p.selling_price,
                    "cgst_rate": p.cgst_rate,
                    "sgst_rate": p.sgst_rate,
                    "igst_rate": p.igst_rate,
                })
            
            # Create the sale invoice
            # Note: create_sale_invoice commits each invoice. With PRAGMA synchronous = OFF,
            # this runs extremely fast in SQLite.
            invoice_no = f"LT-{i:06d}"
            create_sale_invoice(
                db,
                business_id=business_id,
                lines=lines,
                customer=customer.name,
                customer_id=customer.id,
                invoice_no=invoice_no,
                invoice_date=inv_date_str,
                due_date=(inv_date + timedelta(days=30)).strftime("%Y-%m-%d"),
                place_of_supply="29",
                payment_mode=random.choice(["Cash", "Card", "UPI", None]),
                paid_amount=0.0,
                mark_paid=random.choice([True, False])
            )
            
            if i % 1000 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed
                print(f"Seeded {i}/{count} invoices (Rate: {rate:.2f} inv/sec)")
                
        total_time = time.time() - start_time
        print(f"Seeding completed successfully!")
        print(f"Total time: {total_time:.2f} seconds.")
        print(f"Overall Rate: {count / total_time:.2f} invoices/second.")
        
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed database for performance load testing.")
    parser.add_argument("--business-id", type=int, default=2, help="Business ID to seed invoices for (default: 2)")
    parser.add_argument("--count", type=int, default=10000, help="Number of invoices to seed (default: 10000)")
    args = parser.parse_args()
    
    seed_load_test(args.business_id, args.count)
