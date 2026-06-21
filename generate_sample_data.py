"""
generate_sample_data.py
========================
Clears the sample_data/ directory and generates import-ready sample files for all uploader routes:
  1. sample_invoices.csv
  2. sample_inventory.csv
  3. sample_payments.csv
  4. sample_customers_import.csv
  5. sample_products_import.csv
  6. sample_bill.png (invoice image for OCR testing)
"""
import csv
import os
import shutil
import random
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

random.seed(42)  # reproducible random data
TODAY = datetime.now()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")

# ── Clean directory ─────────────────────────────────────────────────────────
if os.path.exists(OUT):
    print(f"Clearing existing sample_data directory: {OUT}")
    shutil.rmtree(OUT)
os.makedirs(OUT, exist_ok=True)

# ── Reference lists ─────────────────────────────────────────────────────────
CUSTOMERS = [
    "Nilgiris Fresh", "Star Bazaar", "Daily Needs Store", "Big Basket Retail",
    "Reliance Smart Point", "More Supermarket", "Spencer's Retail", "Nature's Basket",
    "Metro Cash & Carry", "Heritage Fresh", "Annapurna Provisions", "Lakshmi General Store",
    "Kumar Stores", "Rahul Traders", "Vijaya Retail Hub", "Royal Mart",
    "Srinivas Kirana", "Namdhari Fresh", "ABC Supermarket", "Sri Venkateswara Stores",
]
BIG_ACCOUNTS = CUSTOMERS[:4]

SELLING_PRODUCTS = [
    "Basmati Rice 25kg", "Sunflower Oil 15L", "Sugar 50kg", "Wheat Flour 10kg",
    "Toor Dal 5kg", "Tea Leaves 1kg", "Coffee Powder 500g", "Detergent Powder 3kg",
    "Colgate Toothpaste", "Soap Bar 100g", "Shampoo 1L", "Milk Powder 500g",
    "Salt 1kg", "Chilli Powder 500g", "Biscuits Pack", "Cooking Oil 5L",
]
PERISHABLES = ["Bread Loaf", "Cheese Slices 200g", "Curd 400g", "Eggs 30pc", "Paneer 200g"]
DEAD_STOCK = ["Sona Masoori Rice 25kg", "Chana Dal 10kg", "Jaggery 5kg", "Vermicelli 1kg"]

SUPPLIERS = ["AgroFoods Wholesale", "Hindustan Distributors", "Sri Balaji Traders",
             "Metro Supply Co", "Nandi Agro"]

PRICE_BAND = {
    "Basmati Rice 25kg": (8000, 45000), "Sunflower Oil 15L": (6000, 38000),
    "Sugar 50kg": (5000, 30000), "Wheat Flour 10kg": (2000, 18000),
    "Toor Dal 5kg": (3000, 22000), "Tea Leaves 1kg": (1500, 12000),
    "Coffee Powder 500g": (2000, 15000), "Detergent Powder 3kg": (1000, 9000),
    "Colgate Toothpaste": (500, 6000), "Soap Bar 100g": (400, 5000),
    "Shampoo 1L": (1200, 9000), "Milk Powder 500g": (1500, 11000),
    "Salt 1kg": (300, 3000), "Chilli Powder 500g": (800, 7000),
    "Biscuits Pack": (600, 6500), "Cooking Oil 5L": (3000, 20000),
}

def _d(dt):
    return dt.strftime("%Y-%m-%d")

# ── 1. Invoices ─────────────────────────────────────────────────────────────
def gen_invoices(n=300):
    rows = []
    start = TODAY - timedelta(days=365)
    for i in range(1, n + 1):
        cust = random.choice(BIG_ACCOUNTS) if random.random() < 0.35 else random.choice(CUSTOMERS)
        prod = random.choice(SELLING_PRODUCTS)
        lo, hi = PRICE_BAND[prod]
        progress = i / n
        amount = round(random.uniform(lo, hi) * (0.8 + 0.5 * progress), 2)
        inv_date = start + timedelta(days=random.randint(0, 365))
        due = inv_date + timedelta(days=random.choice([15, 30, 45]))
        
        if random.random() < 0.55:
            status = "Paid"
        else:
            status = "Overdue" if due < TODAY else "Pending"

        rows.append({
            "invoice_id": f"INV-{i:04d}",
            "customer": cust,
            "product": prod,
            "amount": amount,
            "status": status,
            "invoice_date": _d(inv_date),
            "due_date": _d(due),
        })
    return rows

# ── 2. Inventory ────────────────────────────────────────────────────────────
def gen_inventory():
    rows = []
    for p in SELLING_PRODUCTS:
        stock = random.choice([random.randint(40, 400), random.randint(2, 9)])
        rows.append({
            "product_name": p, "stock": stock,
            "expiry_date": _d(TODAY + timedelta(days=random.randint(120, 720))),
            "supplier": random.choice(SUPPLIERS)
        })
    for p in PERISHABLES:
        rows.append({
            "product_name": p, "stock": random.randint(15, 200),
            "expiry_date": _d(TODAY + timedelta(days=random.randint(2, 28))),
            "supplier": random.choice(SUPPLIERS)
        })
    for p in DEAD_STOCK:
        rows.append({
            "product_name": p, "stock": random.randint(60, 600),
            "expiry_date": _d(TODAY + timedelta(days=random.randint(200, 800))),
            "supplier": random.choice(SUPPLIERS)
        })
    
    # Cost, selling, mrp, reorder band
    for r in rows:
        cost = round(random.uniform(50, 400), 2)
        r["cost_price"] = cost
        r["selling_price"] = round(cost * random.uniform(1.12, 1.35), 2)
        r["reorder_point"] = random.choice([10, 20, 30])
    return rows

# ── 3. Payments ─────────────────────────────────────────────────────────────
def gen_payments(n=80):
    rows = []
    start = TODAY - timedelta(days=365)
    for _ in range(n):
        cust = random.choice(CUSTOMERS)
        due = start + timedelta(days=random.randint(0, 365))
        rows.append({
            "customer": cust,
            "amount": round(random.uniform(3000, 45000), 2),
            "due_date": _d(due),
            "paid": "Yes" if (due < TODAY and random.random() < 0.6) else "No",
        })
    return rows

# ── 4. Customers Import ──────────────────────────────────────────────────────
def gen_customers_import():
    rows = []
    for i, name in enumerate(CUSTOMERS[:10]):
        rows.append({
            "name": name,
            "phone": f"+9198765432{i:02d}",
            "email": f"{name.lower().replace(' ', '')}@test.com",
            "address": f"{10 + i} Main St, Business Hub, Bangalore",
            "gstin": f"29TESTC{1234 + i}A1Z{i}",
            "state_code": "29",
            "pan": f"TESTC{1234 + i}A",
            "credit_limit": round(random.choice([50000.0, 100000.0, 250000.0]), 2),
            "credit_days": random.choice([30, 45, 60]),
            "opening_dues": round(random.choice([0.0, 2000.0, 15000.0]), 2),
        })
    return rows

# ── 5. Products Import ───────────────────────────────────────────────────────
def gen_products_import():
    rows = []
    brands = ["Organic India", "Tata", "Fortune", "Surf Excel", "Colgate", "Himalaya", "Nestle"]
    manufacturers = ["Organic India Pvt Ltd", "Tata Consumer Products", "Adani Wilmar", "Unilever", "Colgate-Palmolive", "Himalaya Wellness", "Nestle India"]
    categories = ["Grocery", "Grocery", "Grocery", "Household", "Personal Care", "Personal Care", "Grocery"]
    
    for i, name in enumerate(SELLING_PRODUCTS[:8]):
        cost = round(random.uniform(40.0, 350.0), 2)
        sp = round(cost * random.uniform(1.15, 1.30), 2)
        mrp = round(sp * 1.10, 2)
        rows.append({
            "name": name,
            "sku": f"PROD-SKU-{i:03d}",
            "barcode": f"8901234567{i:03d}",
            "unit": "Nos",
            "description": f"High quality organic {name} for retail distribution.",
            "brand": random.choice(brands),
            "manufacturer": random.choice(manufacturers),
            "category": random.choice(categories),
            "selling_price": sp,
            "cost_price": cost,
            "mrp": mrp,
            "cgst_rate": 6.0,
            "sgst_rate": 6.0,
            "igst_rate": 0.0,
            "opening_stock": random.randint(50, 500)
        })
    return rows

# ── 6. Invoice Image Generator ──────────────────────────────────────────────
def gen_bill_image():
    width, height = 800, 1000
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 28)
        font_header = ImageFont.truetype("arialbd.ttf", 16)
        font_regular = ImageFont.truetype("arial.ttf", 13)
        font_bold = ImageFont.truetype("arialbd.ttf", 13)
    except IOError:
        font_title = ImageFont.load_default()
        font_header = font_title
        font_regular = font_title
        font_bold = font_title

    draw.text((40, 40), "TAX INVOICE", fill="black", font=font_title)
    draw.text((40, 90), "Apex Pharma Distributors", fill="black", font=font_header)
    draw.text((40, 110), "12, Industrial Area, Bangalore - 560001", fill="gray", font=font_regular)
    draw.text((40, 125), "GSTIN: 29APEXPD1234F1Z5 | Phone: +91 98765 43210", fill="gray", font=font_regular)

    draw.text((500, 90), "Invoice No: APEX-2026-908", fill="black", font=font_bold)
    draw.text((500, 110), "Date: 2026-06-15", fill="black", font=font_regular)
    draw.text((500, 125), "Due Date: 2026-07-15", fill="black", font=font_regular)

    draw.line((40, 160, 760, 160), fill="lightgray", width=1)

    draw.text((40, 180), "BILLED TO:", fill="gray", font=font_header)
    draw.text((40, 200), "MediCare Pharmacy", fill="black", font=font_bold)
    draw.text((40, 215), "5th Block, Koramangala, Bangalore - 560034", fill="black", font=font_regular)
    draw.text((40, 230), "GSTIN: 29MEDICARE1234A1Z0", fill="black", font=font_regular)

    draw.line((40, 260, 760, 260), fill="black", width=2)

    headers = [
        ("Item Description", 40),
        ("HSN", 250),
        ("Qty", 320),
        ("Unit", 380),
        ("Rate", 440),
        ("Taxable Val", 510),
        ("GST %", 610),
        ("Total (INR)", 680)
    ]
    for h, x in headers:
        draw.text((x, 275), h, fill="black", font=font_bold)

    draw.line((40, 300, 760, 300), fill="black", width=2)

    rows = [
        ("Paracetamol 650mg", "3004", "10", "Box", "100.00", "1000.00", "12%", "1120.00"),
        ("Amoxicillin 500mg", "3004", "5", "Box", "200.00", "1000.00", "12%", "1120.00"),
        ("Dolo 650", "3004", "20", "Nos", "15.00", "300.00", "12%", "336.00")
    ]

    y_pos = 320
    for row in rows:
        draw.text((40, y_pos), row[0], fill="black", font=font_regular)
        draw.text((250, y_pos), row[1], fill="black", font=font_regular)
        draw.text((320, y_pos), row[2], fill="black", font=font_regular)
        draw.text((380, y_pos), row[3], fill="black", font=font_regular)
        draw.text((440, y_pos), row[4], fill="black", font=font_regular)
        draw.text((510, y_pos), row[5], fill="black", font=font_regular)
        draw.text((610, y_pos), row[6], fill="black", font=font_regular)
        draw.text((680, y_pos), row[7], fill="black", font=font_bold)
        y_pos += 30
        draw.line((40, y_pos - 10, 760, y_pos - 10), fill="lightgray", width=1)

    draw.line((40, y_pos + 10, 760, y_pos + 10), fill="black", width=2)
    totals = [
        ("Subtotal:", "2,300.00", y_pos + 30),
        ("CGST (6%):", "138.00", y_pos + 50),
        ("SGST (6%):", "138.00", y_pos + 70),
        ("Grand Total:", "2,576.00", y_pos + 100)
    ]
    for label, val, y in totals:
        is_grand = "Grand" in label
        draw.text((500, y), label, fill="black", font=font_bold if is_grand else font_regular)
        draw.text((680, y), val, fill="black", font=font_header if is_grand else font_regular)

    out_path = os.path.join(OUT, "sample_bill.png")
    img.save(out_path)
    print(f"Generated sample_bill.png: {out_path}")

# ── CSV Writer Helper ────────────────────────────────────────────────────────
def write_csv(name, rows, fields):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"Generated {name}: {path} ({len(rows)} rows)")

if __name__ == "__main__":
    print("Generating comprehensive sample data...")
    write_csv("sample_invoices.csv", gen_invoices(), 
              ["invoice_id", "customer", "product", "amount", "status", "invoice_date", "due_date"])
    write_csv("sample_inventory.csv", gen_inventory(),
              ["product_name", "stock", "expiry_date", "supplier", "cost_price", "selling_price", "reorder_point"])
    write_csv("sample_payments.csv", gen_payments(),
              ["customer", "amount", "due_date", "paid"])
    write_csv("sample_customers_import.csv", gen_customers_import(),
              ["name", "phone", "email", "address", "gstin", "state_code", "pan", "credit_limit", "credit_days", "opening_dues"])
    write_csv("sample_products_import.csv", gen_products_import(),
              ["name", "sku", "barcode", "unit", "description", "brand", "manufacturer", "category", "selling_price", "cost_price", "mrp", "cgst_rate", "sgst_rate", "igst_rate", "opening_stock"])
    gen_bill_image()
    print("Sample data generation completed successfully!")
