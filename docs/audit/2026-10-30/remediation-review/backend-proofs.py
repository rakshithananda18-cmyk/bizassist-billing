"""Current-working-tree verification; expects corrected financial behavior.

Only in-memory SQLite is used. No merchant DB, network, payments or messages.
Unlike the original audit reproduction, false `passed` flags identify remaining
or newly introduced problems, not an expectation that the old bug still exists.
"""
from pathlib import Path
from contextlib import contextmanager
import os
import sys
import socket
import json
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT / "backend"))
# base_packages = Path(r"C:\Users\raksh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
# if base_packages.exists():
#     sys.path.append(str(base_packages))
os.environ.update({
    "DATABASE_URL": "sqlite:///./test_remediation_domain_unused.db",
    "BIZASSIST_TEST_DATABASE_URL": "", "BIZASSIST_TESTING": "1",
    "GROQ_API_KEY": "mock_groq_api_key",
    "JWT_SECRET": "test-only-secret-please-change-0123456789abcdef",
    "SENTRY_DSN": "", "CHAT_MEMORY_ENABLED": "0", "ANONYMIZED_TELEMETRY": "False",
    "CLOUD_API_URL": "http://127.0.0.1:9", "CLOUD_URL": "http://127.0.0.1:9",
    "LLM_ROUTER": "off",
})

def no_network(*args, **kwargs):
    raise OSError("All networking disabled for in-memory remediation proofs")

socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.getaddrinfo = no_network

from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, Product, Inventory, Invoice, InvoiceLineItem, InvoicePayment, Customer, PurchaseInvoice
from core.models import B2BConnection, JournalEntry, JournalLine
from core.stock import ledger
from core.billing import commands as billing
from core.billing.balances import business_revenue_summary, invoice_balance
from core.purchase import commands as purchase
from core.order import service as orders
from core.accounting import posting
from core.api.reports import report_pnl
from services import actions, self_healing, recommendations
from services.handlers import invoices as invoice_handlers
from services.tools import business as business_tools
from database.migration import _COLUMN_MIGRATIONS

checks = []

def record(name, expected, observed):
    checks.append({"check": name, "expected": expected, "observed": observed, "passed": expected == observed})

@contextmanager
def fixture(*, rounding=False, cost=40):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        owner = User(id=930001, username="remed_owner", public_id="BA-REMED-OWNER",
            password="unusable", state_code="29", business_name="Remediation fixture",
            settings=json.dumps({"transactions": {"round_off_enabled": rounding}}))
        buyer = User(id=930002, username="remed_buyer", public_id="BA-REMED-BUYER",
            password="unusable", state_code="29", business_name="Remediation buyer",
            settings=json.dumps({"transactions": {"round_off_enabled": rounding}}))
        db.add_all([owner, buyer])
        db.flush()
        product = Product(business_id=owner.id, name="Remediation item", unit="Nos",
            selling_price=100, cost_price=cost, track_inventory=False, is_active=True,
            cgst_rate=0, sgst_rate=0, igst_rate=0, category="Allowed")
        db.add(product)
        db.commit()
        yield db, owner, buyer, product, Session, engine
    engine.dispose()

def sale(db, owner, product, **kwargs):
    return billing.create_sale_invoice(db, business_id=owner.id,
        lines=[{"product_id": product.id, "quantity": 1, "unit_price": 100}], **kwargs)

def connection(db, owner, buyer, **kwargs):
    row = B2BConnection(seller_business_id=owner.id, buyer_business_id=buyer.id,
        status="accepted", price_tier="standard", discount_pct=0, stock_visibility="exact", **kwargs)
    db.add(row)
    db.commit()
    return row

def complete(db, owner, order):
    for status in ("accepted", "packed", "dispatched", "completed"):
        orders.transition_order_status(db, owner.id, order.id, status)
    return db.query(Invoice).filter(Invoice.id == order.seller_invoice_id).one()

with fixture() as (db, owner, buyer, product, Session, engine):
    inv = sale(db, owner, product, invoice_no="CONTAIN-MARK-PAID")
    with patch.object(actions, "SessionLocal", Session):
        result = actions._mark_paid_execute(owner.id, {"invoice_id": inv.invoice_id})
    db.expire_all()
    db.refresh(inv)
    record("BD-01-disabled-mark-paid", {"ok": False, "status": "Pending", "paid": 0},
        {"ok": result["ok"], "status": inv.status, "paid": inv.paid_amount})
    entry = db.query(JournalEntry).filter(JournalEntry.business_id == owner.id).first()
    old_hash = entry.entry_hash
    entry.narration = "Changed narration in disposable fixture"
    db.commit()
    self_healing.heal_hash_chain(db, owner.id)
    db.commit()
    record("BD-05-preserve-integrity-alarm", {"hash_unchanged": True, "verify_ok": False},
        {"hash_unchanged": entry.entry_hash == old_hash, "verify_ok": posting.verify_chain(db, owner.id)["ok"]})

with fixture() as (db, owner, buyer, product, Session, engine):
    product.track_inventory = True
    db.commit()
    for batch, qty in [("B1", 5), ("B2", 7)]:
        ledger.record_movement(db, business_id=owner.id, movement_type=ledger.OPENING,
            qty_delta=qty, product_id=product.id, product_name=product.name, batch_no=batch)
    db.commit()
    ledger.record_movement(db, business_id=owner.id, movement_type=ledger.SALE,
        qty_delta=-1, product_id=product.id, product_name=product.name)
    db.commit()
    ledger.rebuild_inventory_cache(db, owner.id)
    db.commit()
    total = db.query(func.sum(Inventory.stock)).filter(Inventory.business_id == owner.id).scalar()
    record("BD-02-exact-null-bucket-and-rebuild", 11, total)
    connection(db, owner, buyer)
    catalog = orders.get_supplier_catalog(db, buyer.id, owner.id)
    record("BD-12-catalogue-total", 11, next(row["stock"] for row in catalog if row["product_id"] == product.id))

with fixture() as (db, owner, buyer, product, Session, engine):
    pur = purchase.accept_supplier_invoice(db, owner.id, {
        "supplier_name": "Carton supplier", "invoice_number": "REMED-CARTON", "invoice_date": "2026-10-30",
        "items": [{"product_name": "Carton product", "quantity": 1, "conversion_factor": 12,
                   "purchase_unit": "Carton", "unit": "Nos", "unit_price": 120}],
    })
    carton = db.query(Product).filter(Product.name == "Carton product").one()
    inventory = db.query(Inventory).filter(Inventory.product_id == carton.id).one()
    record("BD-03-conversion-valuation", {"cost": 10, "valuation": 120},
        {"cost": carton.cost_price, "valuation": inventory.stock * inventory.cost_price})

with fixture() as (db, owner, buyer, product, Session, engine):
    customer = Customer(business_id=owner.id, name="No invoice dues", credit_balance=0)
    db.add(customer)
    db.commit()
    rejected = False
    try:
        billing.settle_customer_dues(db, business_id=owner.id, customer_id=customer.id,
            amount=100, idempotency_key="SAME-ADVANCE")
    except ValueError:
        rejected = True
    record("BD-09-standalone-advance-contained", {"rejected": True, "credit_balance": 0},
        {"rejected": rejected, "credit_balance": customer.credit_balance})

with fixture() as (db, owner, buyer, product, Session, engine):
    inv = sale(db, owner, product, invoice_no="REMED-FULL-RETURN")
    billing.create_credit_note(db, business_id=owner.id, original_invoice_id=inv.id,
        lines=[{"product_id": product.id, "quantity": 1}])
    overview = business_revenue_summary(db, owner.id)
    record("BD-04-overview-full-return", {"revenue": 0, "collected": 0},
        {"revenue": overview["net_revenue"], "collected": overview["collected_revenue"]})
    with patch.object(invoice_handlers, "SessionLocal", Session):
        breakdown = invoice_handlers._total_revenue(owner.id)
    with patch.object(recommendations, "SessionLocal", Session), patch("services.memory_service.get_business_facts", return_value=[]):
        snapshot = recommendations.get_business_snapshot(owner.id)
    record("BD-04-deterministic-return-parity", True, "Total revenue  : **₹0**" in breakdown)
    record("BD-04-prompt-snapshot-return-parity", True, "Revenue: Rs.0 |" in snapshot)
    checks[-2]["detail"] = breakdown
    checks[-1]["detail"] = snapshot

with fixture() as (db, owner, buyer, product, Session, engine):
    db.add(Invoice(business_id=owner.id, invoice_id="LEGACY-PAID", amount=100, total_amount=100,
                   status="Paid", paid_amount=100))
    db.commit()
    billing.create_sale_invoice(db, business_id=owner.id, invoice_no="NEW-PAID",
        lines=[{"product_id": product.id, "quantity": 1, "unit_price": 10}], paid_amount=10)
    record("BD-04-mixed-legacy-and-new-receipts", 110,
        business_revenue_summary(db, owner.id)["collected_revenue"])

with fixture() as (db, owner, buyer, product, Session, engine):
    inv = sale(db, owner, product, invoice_no="PART-RETURN-OVERDUE", paid_amount=20)
    billing.create_credit_note(db, business_id=owner.id, original_invoice_id=inv.id,
        lines=[{"product_id": product.id, "quantity": 0.5}])
    inv.status = "Overdue"
    db.commit()
    due = invoice_balance(db, inv)["outstanding"]
    record("BD-04-partial-receipt-return-overdue", due,
        business_revenue_summary(db, owner.id)["overdue_revenue"])

with fixture(rounding=True) as (db, owner, buyer, product, Session, engine):
    product.selling_price = 100.5
    product.cgst_rate = product.sgst_rate = 9
    product.igst_rate = 18
    db.commit()
    connection(db, owner, buyer)
    order = orders.create_order(db, buyer.id, owner.id, [{"product_id": product.id, "quantity": 1}])
    final = complete(db, owner, order)
    record("BD-06-default-rounding-parity", final.total_amount, order.total_amount)

with fixture() as (db, owner, buyer, product, Session, engine):
    product.cgst_rate = product.sgst_rate = 9
    product.igst_rate = 18
    db.commit()
    connection(db, owner, buyer)
    order = orders.create_order(db, buyer.id, owner.id, [{"product_id": product.id, "quantity": 1}])
    buyer.state_code = "27"
    db.commit()
    final = complete(db, owner, order)
    record("BD-06-destination-change-preserves-tax-or-requotes", 18, final.igst_total)
    checks[-1]["detail"] = {"quoted_total": order.total_amount, "final_total": final.total_amount,
                            "final_cgst": final.cgst_total, "final_sgst": final.sgst_total}

with fixture() as (db, owner, buyer, product, Session, engine):
    connection(db, owner, buyer, catalog_category="Allowed")
    product.category = "Hidden"
    db.commit()
    denied = False
    try:
        orders.create_order(db, buyer.id, owner.id, [{"product_id": product.id, "quantity": 1}])
    except ValueError:
        denied = True
    record("BD-07-hidden-product-denied", True, denied)
    product.category = "Allowed"
    db.commit()
    order = orders.create_order(db, buyer.id, owner.id, [{"product_id": product.id, "quantity": 1}])
    complete(db, owner, order)
    denied = False
    try:
        orders.transition_order_status(db, owner.id, order.id, "rejected")
    except ValueError:
        denied = True
    record("BD-08-terminal-order-protected", True, denied)

with fixture(cost=80) as (db, owner, buyer, product, Session, engine):
    sale(db, owner, product, invoice_no="NEW-COST-SNAPSHOT")
    product.cost_price = 140
    db.commit()
    cogs = next(row["amount"] for row in report_pnl(from_date=None, to_date=None,
        current_user={"id": owner.id}, db=db) if row["metric"] == "Cost of Goods Sold (COGS)")
    record("BD-10-new-positive-cost-immutable", 80, cogs)

with fixture(cost=0) as (db, owner, buyer, product, Session, engine):
    inv = sale(db, owner, product, invoice_no="ZERO-COST-RETURN")
    product.cost_price = 40
    db.commit()
    note = billing.create_credit_note(db, business_id=owner.id, original_invoice_id=inv.id,
        lines=[{"product_id": product.id, "quantity": 1}])
    cogs = next(row["amount"] for row in report_pnl(from_date=None, to_date=None,
        current_user={"id": owner.id}, db=db) if row["metric"] == "Cost of Goods Sold (COGS)")
    record("BD-10-zero-cost-return-preserves-original", {"return_cost": 0, "net_cogs": 0},
        {"return_cost": note.line_items[0].cost_price, "net_cogs": cogs})

with fixture(cost=80) as (db, owner, buyer, product, Session, engine):
    inv = sale(db, owner, product, invoice_no="PRE-UPGRADE-ROW")
    owner_id = owner.id
    db.close()
    # Recreate the predecessor shape (the snapshot column did not exist).
    migration = next(m for m in _COLUMN_MIGRATIONS
        if m["table"] == "invoice_line_items" and m["column"] == "cost_price")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE invoice_line_items DROP COLUMN cost_price"))
        conn.execute(text(migration["ddl"]))
        stored_cost = conn.execute(text("SELECT cost_price FROM invoice_line_items")).scalar()
    record("BD-10-migration-does-not-invent-zero-history", None, stored_cost)
    with Session() as verify_db:
        cogs = next(row["amount"] for row in report_pnl(from_date=None, to_date=None,
            current_user={"id": owner_id}, db=verify_db) if row["metric"] == "Cost of Goods Sold (COGS)")
        checks[-1]["detail"] = {"pre_upgrade_product_cost": 80, "post_migration_reported_cogs": cogs}

with fixture() as (db, owner, buyer, product, Session, engine):
    # Simulate an existing deployment: the newly declared index is absent.
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_purchase_invoices_biz_dn"))
    Base.metadata.create_all(engine)
    installed = any(index["name"] == "uq_purchase_invoices_biz_dn"
                    for index in inspect(engine).get_indexes("purchase_invoices"))
    record("BD-13-existing-table-gets-uniqueness", True, installed)
    notes = []
    for number in (1, 2):
        pur = purchase.accept_supplier_invoice(db, owner.id, {
            "supplier_name": f"DN supplier {number}", "invoice_number": f"REMED-PUR-{number}",
            "invoice_date": "2026-10-30", "items": [{"product_name": f"DN item {number}",
                                                    "quantity": 1, "unit_price": 50}],
        })
        pid = pur.line_items[0].product_id
        notes.append(purchase.create_debit_note(db, business_id=owner.id, original_purchase_id=pur.id,
            lines=[{"product_id": pid, "quantity": 1}], debit_note_no="DN-SAME"))
    record("BD-13-existing-db-rejects-duplicate-manual-number", 1,
        db.query(PurchaseInvoice).filter(PurchaseInvoice.invoice_type == "debit_note",
            PurchaseInvoice.invoice_number == "DN-SAME").count())

output = {"scope": "HEAD 6c52792 plus current unstaged/new files; in-memory SQLite only",
          "checks": checks, "passed": sum(check["passed"] for check in checks),
          "failed": sum(not check["passed"] for check in checks)}
serialized = json.dumps(output, indent=2, ensure_ascii=False, default=str)
Path(__file__).with_name("backend-proof-results.json").write_text(serialized + "\n", encoding="utf-8")
print(serialized)
