"""Disposable, offline reproductions for the 30 October backend domain audit.

Run with scratch/core-workflow-venv/Scripts/python.exe. Only an in-memory SQLite
database is created. This records current defects; it is not a passing regression
suite or a test of deployed PostgreSQL behavior.
"""
from pathlib import Path
import os
import socket
import sys
import json
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT / "backend"))
base_packages = Path(r"C:\Users\raksh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if base_packages.exists():
    sys.path.append(str(base_packages))
os.environ.update({
    "DATABASE_URL": "sqlite:///./test_audit_domain_unused.db",
    "BIZASSIST_TESTING": "1", "GROQ_API_KEY": "mock_groq_api_key",
    "JWT_SECRET": "test-only-secret-please-change-0123456789abcdef",
    "SENTRY_DSN": "", "CHAT_MEMORY_ENABLED": "0",
    "ANONYMIZED_TELEMETRY": "False", "CLOUD_API_URL": "http://127.0.0.1:9",
    "CLOUD_URL": "http://127.0.0.1:9", "LLM_ROUTER": "off",
})

def no_network(*args, **kwargs):
    raise OSError("All network disabled during audit reproduction")

socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.getaddrinfo = no_network

import dotenv
dotenv.load_dotenv = lambda *_a, **_kw: False

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, Product, Inventory, Invoice, InvoicePayment, Customer
from core.models import JournalEntry, JournalLine, B2BConnection
from core.stock import ledger
from core.billing import commands as billing
from core.purchase import commands as purchase
from core.order import service as orders
from core.accounting import posting
from services import actions, self_healing
from services.tools import business as business_tools

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
results = {}

with Session() as db:
    owner = User(id=810001, username="audit_owner", public_id="BA-AUDIT-OWNER",
                 password="unusable", state_code="29", business_name="Audit fixture",
                 settings=json.dumps({"transactions": {"round_off_enabled": False}}))
    buyer = User(id=810002, username="audit_buyer", public_id="BA-AUDIT-BUYER",
                 password="unusable", state_code="29", business_name="Audit buyer")
    db.add_all([owner, buyer])
    db.flush()
    product = Product(business_id=owner.id, name="Audit batched product", unit="Nos",
                      selling_price=100, cost_price=60, track_inventory=True,
                      is_active=True, cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(product)
    db.flush()
    for batch, qty in [("B1", 5), ("B2", 7)]:
        ledger.record_movement(db, business_id=owner.id, movement_type=ledger.OPENING,
                               qty_delta=qty, product_id=product.id,
                               product_name=product.name, batch_no=batch)
    db.commit()
    ledger.record_movement(db, business_id=owner.id, movement_type=ledger.SALE,
                           qty_delta=-1, product_id=product.id, product_name=product.name)
    db.commit()
    results["stock_null_bucket"] = {
        "ledger_total": ledger.current_stock(db, owner.id, product_id=product.id),
        "inventory_sum": db.query(func.sum(Inventory.stock)).filter(
            Inventory.business_id == owner.id, Inventory.product_id == product.id).scalar(),
        "inventory_buckets": [{"batch": inv.batch_no, "stock": inv.stock} for inv in db.query(Inventory).filter(
            Inventory.business_id == owner.id, Inventory.product_id == product.id).all()],
    }
    assert results["stock_null_bucket"]["ledger_total"] == 11
    assert results["stock_null_bucket"]["inventory_sum"] == 23

    customer = Customer(business_id=owner.id, name="Audit customer", credit_balance=0)
    db.add(customer)
    db.commit()
    for _ in range(2):
        billing.settle_customer_dues(db, business_id=owner.id, customer_id=customer.id,
                                     amount=100, idempotency_key="same-advance-key")
    results["standalone_advance_replay"] = {
        "credit_balance_after_same_key_twice": customer.credit_balance,
        "receipts": db.query(InvoicePayment).filter(InvoicePayment.customer_id == customer.id).count(),
        "journals": db.query(JournalEntry).filter(JournalEntry.business_id == owner.id).count(),
    }
    assert customer.credit_balance == 200
    assert results["standalone_advance_replay"]["receipts"] == 0

    inv = billing.create_sale_invoice(db, business_id=owner.id, invoice_no="AUDIT-UNPAID",
        lines=[{"product_name": "Audit freeform", "quantity": 1, "unit_price": 100}])
    before_entries = db.query(JournalEntry).filter(JournalEntry.business_id == owner.id).count()
    # Real action uses its own SessionLocal. Bind it to this same disposable DB.
    with patch.object(actions, "SessionLocal", Session):
        action_result = actions._mark_paid_execute(owner.id, {"invoice_id": inv.invoice_id})
    db.expire_all()
    db.refresh(inv)
    results["ai_mark_paid"] = {
        "action_ok": action_result["ok"], "status": inv.status,
        "paid_amount": inv.paid_amount,
        "receipt_count": db.query(InvoicePayment).filter(InvoicePayment.invoice_id == inv.id).count(),
        "journal_entries_added": db.query(JournalEntry).filter(
            JournalEntry.business_id == owner.id).count() - before_entries,
    }
    assert inv.status == "Paid" and inv.paid_amount == 0
    assert results["ai_mark_paid"]["receipt_count"] == 0

    first = db.query(JournalEntry).filter(JournalEntry.business_id == owner.id).first()
    first.narration = "Changed after posting; original text lost"
    db.commit()
    before_verify = posting.verify_chain(db, owner.id)
    healed = self_healing.heal_hash_chain(db, owner.id)
    db.commit()
    after_verify = posting.verify_chain(db, owner.id)
    results["hash_tamper_reseal"] = {"before": before_verify, "healed": healed, "after": after_verify}
    assert not before_verify["ok"] and after_verify["ok"]

    pur = purchase.accept_supplier_invoice(db, owner.id, {
        "supplier_name": "Audit carton supplier", "invoice_number": "CARTON-1",
        "invoice_date": "2026-10-30", "items": [{"product_name": "Audit carton item",
        "quantity": 1, "conversion_factor": 12, "purchase_unit": "Carton", "unit": "Nos",
        "unit_price": 120}],
    })
    carton_product = db.query(Product).filter(Product.name == "Audit carton item").one()
    carton_stock = db.query(Inventory).filter(Inventory.product_id == carton_product.id).one()
    results["purchase_unit_cost"] = {"purchase_total": pur.total_amount,
        "stock_units": carton_stock.stock, "unit_cost": carton_stock.cost_price,
        "inventory_value": carton_stock.stock * carton_stock.cost_price}
    assert pur.total_amount == 120 and carton_stock.stock * carton_stock.cost_price == 1440

    conn = B2BConnection(seller_business_id=owner.id, buyer_business_id=buyer.id,
                         status="accepted", price_tier="standard", discount_pct=0,
                         stock_visibility="exact")
    db.add(conn)
    db.commit()
    clean_catalog_product = Product(business_id=owner.id, name="Audit clean catalogue stock",
        unit="Nos", selling_price=10, track_inventory=True, is_active=True,
        cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(clean_catalog_product)
    db.flush()
    for batch, qty in [("C1", 5), ("C2", 7)]:
        ledger.record_movement(db, business_id=owner.id, movement_type=ledger.OPENING,
            qty_delta=qty, product_id=clean_catalog_product.id,
            product_name=clean_catalog_product.name, batch_no=batch)
    db.commit()
    catalog = orders.get_supplier_catalog(db, buyer.id, owner.id)
    catalog_stock = next(row["stock"] for row in catalog if row["product_id"] == clean_catalog_product.id)
    results["catalog_multi_bucket_stock"] = {"true_total": 12, "catalog_stock": catalog_stock}
    assert catalog_stock == 7
    order = orders.create_order(db, buyer.id, owner.id, [{"product_id": product.id, "quantity": 1}])
    # Completing directly is permitted, then changing terminal state retains docs.
    orders.transition_order_status(db, owner.id, order.id, "completed")
    orders.transition_order_status(db, owner.id, order.id, "rejected")
    results["completed_order_rejected"] = {"status": order.status, "seller_invoice_id": order.seller_invoice_id}
    assert order.status == "rejected" and order.seller_invoice_id is not None

    taxable_product = Product(business_id=owner.id, name="Audit GST item", unit="Nos",
        selling_price=100, track_inventory=False, is_active=True,
        cgst_rate=9, sgst_rate=9, igst_rate=18)
    db.add(taxable_product)
    db.commit()
    taxable_order = orders.create_order(db, buyer.id, owner.id,
        [{"product_id": taxable_product.id, "quantity": 1}])
    orders.transition_order_status(db, owner.id, taxable_order.id, "completed")
    final_sale = db.query(Invoice).filter(Invoice.id == taxable_order.seller_invoice_id).one()
    results["b2b_order_gst_mismatch"] = {"same_state_order_total": taxable_order.total_amount,
                                        "final_invoice_total": final_sale.total_amount}
    assert taxable_order.total_amount == 136 and final_sale.total_amount == 118

    conn.catalog_category = "Visible category"
    taxable_product.category = "Hidden category"
    db.commit()
    visible_catalog = orders.get_supplier_catalog(db, buyer.id, owner.id)
    assert taxable_product.id not in {row["product_id"] for row in visible_catalog}
    hidden_order = orders.create_order(db, buyer.id, owner.id,
        [{"product_id": taxable_product.id, "quantity": 1}])
    results["b2b_catalog_category_bypass"] = {"catalog_exposes_product": False,
        "order_accepted_product": hidden_order.line_items[0].product_name,
        "order_exposes_unit_price": hidden_order.line_items[0].unit_price}

    with patch.object(business_tools, "SessionLocal", Session):
        before_overview = json.loads(business_tools.get_business_overview(owner.id))
    plain = Product(business_id=owner.id, name="Audit AI return", unit="Nos",
                    track_inventory=False, is_active=True, selling_price=100,
                    cgst_rate=0, sgst_rate=0, igst_rate=0)
    db.add(plain)
    db.commit()
    full_return_sale = billing.create_sale_invoice(db, business_id=owner.id,
        invoice_no="AUDIT-AI-RETURN", lines=[{"product_id": plain.id, "quantity": 1, "unit_price": 100}])
    billing.create_credit_note(db, business_id=owner.id, original_invoice_id=full_return_sale.id,
                               lines=[{"product_id": plain.id, "quantity": 1}])
    with patch.object(business_tools, "SessionLocal", Session):
        after_overview = json.loads(business_tools.get_business_overview(owner.id))
    results["ai_full_return_metrics"] = {
        "actual_net_revenue_added": 0,
        "tool_revenue_added": after_overview["total_revenue"] - before_overview["total_revenue"],
        "actual_cash_added": 0,
        "tool_collected_added": after_overview["collected_revenue"] - before_overview["collected_revenue"],
    }
    assert results["ai_full_return_metrics"]["tool_revenue_added"] == 200
    assert results["ai_full_return_metrics"]["tool_collected_added"] == 100

serialized = json.dumps(results, indent=2, default=str)
Path(__file__).with_name("backend-domain-repro-results.json").write_text(serialized + "\n", encoding="utf-8")
print(serialized)
