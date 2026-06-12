"""
generate_sample_data.py
========================
Generates three import-ready CSVs that match BizAssist's uploader columns exactly
(so column-mapping is a clean exact match), with realistic, story-rich data:

  sample_invoices.csv   invoice_id, customer, product, amount, status, invoice_date, due_date
  sample_inventory.csv  product_name, stock, expiry_date, supplier
  sample_payments.csv   customer, amount, due_date, paid

Designed to exercise the standard tools:
  - ~18 months of invoices  -> revenue TREND over time
  - a few customers dominate -> top customers / top debtors / concentration
  - fast-moving vs never-sold products -> product performance / dead stock
  - some stock low / expiring soon       -> reorder + expiry
  - realistic ~55% collection rate         -> cash-flow insight

Run:  python generate_sample_data.py
Then upload the three CSVs via the app (delete old data first).

Note: cost_price/selling_price are NOT included — the current inventory uploader
ignores them, so margins/profit need a small uploader change first.
"""
import csv
import os
import random
from datetime import datetime, timedelta

random.seed(42)                      # reproducible
TODAY = datetime.now()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
os.makedirs(OUT, exist_ok=True)

# ── Reference lists ─────────────────────────────────────────────────────────
CUSTOMERS = [
    "Nilgiris Fresh", "Star Bazaar", "Daily Needs Store", "Big Basket Retail",
    "Reliance Smart Point", "More Supermarket", "Spencer's Retail", "Nature's Basket",
    "Metro Cash & Carry", "Heritage Fresh", "Annapurna Provisions", "Lakshmi General Store",
    "Kumar Stores", "Rahul Traders", "Vijaya Retail Hub", "Royal Mart",
    "Srinivas Kirana", "Namdhari Fresh", "ABC Supermarket", "Sri Venkateswara Stores",
]
# A handful of "big accounts" that get more / larger invoices (concentration).
BIG_ACCOUNTS = CUSTOMERS[:4]

# Products that actually sell (appear on invoices).
SELLING_PRODUCTS = [
    "Basmati Rice 25kg", "Sunflower Oil 15L", "Sugar 50kg", "Wheat Flour 10kg",
    "Toor Dal 5kg", "Tea Leaves 1kg", "Coffee Powder 500g", "Detergent Powder 3kg",
    "Colgate Toothpaste", "Soap Bar 100g", "Shampoo 1L", "Milk Powder 500g",
    "Salt 1kg", "Chilli Powder 500g", "Biscuits Pack", "Cooking Oil 5L",
]
# Perishables (also in inventory, with near expiry).
PERISHABLES = ["Bread Loaf", "Cheese Slices 200g", "Curd 400g", "Eggs 30pc", "Paneer 200g"]
# Dead stock: in inventory but NEVER invoiced.
DEAD_STOCK = ["Sona Masoori Rice 25kg", "Chana Dal 10kg", "Jaggery 5kg", "Vermicelli 1kg"]

SUPPLIERS = ["AgroFoods Wholesale", "Hindustan Distributors", "Sri Balaji Traders",
             "Metro Supply Co", "Nandi Agro"]

PRICE_BAND = {  # rough per-invoice amount band by product
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


# ── Invoices ────────────────────────────────────────────────────────────────
def gen_invoices(n=420):
    rows = []
    start = TODAY - timedelta(days=540)          # ~18 months back
    for i in range(1, n + 1):
        # Bias toward big accounts for concentration + a mild upward trend over time.
        cust = random.choice(BIG_ACCOUNTS) if random.random() < 0.35 else random.choice(CUSTOMERS)
        prod = random.choice(SELLING_PRODUCTS)
        lo, hi = PRICE_BAND[prod]
        # gentle growth: later invoices skew a bit larger
        progress = i / n
        amount = round(random.uniform(lo, hi) * (0.8 + 0.5 * progress), 2)
        inv_date = start + timedelta(days=random.randint(0, 540))
        terms = random.choice([15, 30, 30, 45])
        due = inv_date + timedelta(days=terms)

        # Status: ~55% paid; unpaid + past due => Overdue; unpaid + future => Pending.
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


# ── Inventory ───────────────────────────────────────────────────────────────
def gen_inventory():
    rows = []
    # Selling products: healthy-ish stock, a few low.
    for p in SELLING_PRODUCTS:
        stock = random.choice([random.randint(40, 400), random.randint(40, 400), random.randint(2, 9)])
        rows.append({"product_name": p, "stock": stock,
                     "expiry_date": _d(TODAY + timedelta(days=random.randint(120, 720))),
                     "supplier": random.choice(SUPPLIERS)})
    # Perishables: near expiry (some within 30 days), low-ish stock.
    for p in PERISHABLES:
        rows.append({"product_name": p, "stock": random.randint(15, 200),
                     "expiry_date": _d(TODAY + timedelta(days=random.randint(2, 28))),
                     "supplier": random.choice(SUPPLIERS)})
    # Dead stock: in stock, never sold.
    for p in DEAD_STOCK:
        rows.append({"product_name": p, "stock": random.randint(60, 600),
                     "expiry_date": _d(TODAY + timedelta(days=random.randint(200, 800))),
                     "supplier": random.choice(SUPPLIERS)})
    # Pricing: cost + selling (12–35% margin) + reorder point → unlocks margin/profit.
    for r in rows:
        cost = round(random.uniform(20, 600), 2)
        r["cost_price"] = cost
        r["selling_price"] = round(cost * random.uniform(1.12, 1.35), 2)
        r["reorder_point"] = random.choice([10, 15, 20, 25])
    return rows


# ── Payments (fills the currently-empty payments table) ──────────────────────
def gen_payments(n=90):
    rows = []
    start = TODAY - timedelta(days=400)
    for _ in range(n):
        cust = random.choice(CUSTOMERS)
        due = start + timedelta(days=random.randint(0, 400))
        rows.append({
            "customer": cust,
            "amount": round(random.uniform(2000, 60000), 2),
            "due_date": _d(due),
            "paid": "Yes" if (due < TODAY and random.random() < 0.6) else "No",
        })
    return rows


def write_csv(name, rows, fields):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path, len(rows)


if __name__ == "__main__":
    inv = gen_invoices()
    stock = gen_inventory()
    pay = gen_payments()

    p1, n1 = write_csv("sample_invoices.csv", inv,
                       ["invoice_id", "customer", "product", "amount", "status", "invoice_date", "due_date"])
    p2, n2 = write_csv("sample_inventory.csv", stock,
                       ["product_name", "stock", "expiry_date", "supplier",
                        "cost_price", "selling_price", "reorder_point"])
    p3, n3 = write_csv("sample_payments.csv", pay,
                       ["customer", "amount", "due_date", "paid"])

    # Quick sanity summary
    from collections import Counter
    st = Counter(r["status"] for r in inv)
    print("Generated in:", OUT)
    print(f"  sample_invoices.csv   {n1} rows   statuses={dict(st)}")
    print(f"  sample_inventory.csv  {n2} rows   (incl. {len(DEAD_STOCK)} never-sold, {len(PERISHABLES)} near-expiry)")
    print(f"  sample_payments.csv   {n3} rows")
    print("\nUpload order in the app: invoices, then inventory, then payments.")
