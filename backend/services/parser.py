import logging
import pandas as pd
from database.models import (
    Invoice,
    Inventory,
    Payment
)

logger = logging.getLogger("bizassist.parser")

def save_invoices(df, db, business_id, file_id=None):
    """
    Smart upsert for invoices.
    If invoice_id exists, update it. Otherwise insert.
    Prevents duplicates.
    Runs inside a transaction block to guarantee atomicity.
    """
    try:
        for _, row in df.iterrows():
            invoice_id = row.get("invoice_id")
            
            if not invoice_id:
                continue  # Skip rows without invoice_id
            
            amount_val = row.get("amount")
            if amount_val is not None and str(amount_val).strip() != "" and not pd.isna(amount_val):
                try:
                    amount_val = float(amount_val)
                except ValueError:
                    raise ValueError(f"Invalid amount value: '{amount_val}'. Must be a valid number.")
            else:
                amount_val = None

            # Check if invoice already exists for this business
            existing = db.query(Invoice).filter(
                Invoice.invoice_id == invoice_id,
                Invoice.business_id == business_id
            ).first()
            
            if existing:
                # UPDATE existing record
                existing.customer = row.get("customer", existing.customer)
                existing.product = row.get("product", existing.product)
                existing.amount = amount_val if amount_val is not None else existing.amount
                existing.status = row.get("status", existing.status)
                existing.invoice_date = row.get("invoice_date", existing.invoice_date)
                existing.due_date = row.get("due_date", existing.due_date)
                existing.file_id = file_id
            else:
                # INSERT new record
                invoice = Invoice(
                    invoice_id=invoice_id,
                    customer=row.get("customer"),
                    product=row.get("product"),
                    amount=amount_val,
                    status=row.get("status"),
                    invoice_date=row.get("invoice_date"),
                    due_date=row.get("due_date"),
                    business_id=business_id,
                    file_id=file_id
                )
                db.add(invoice)
        
        db.commit()
    except Exception as e:
        db.rollback()
        raise e

# ----------------------------

def save_inventory(df, db, business_id, file_id=None):
    """
    Smart upsert for inventory.
    If product_name exists, update it. Otherwise insert.
    Prevents duplicates.
    Runs inside a transaction block to guarantee atomicity.
    """
    try:
        for _, row in df.iterrows():
            product_name = row.get("product_name")
            
            if not product_name:
                continue  # Skip rows without product_name
            
            stock_val = row.get("stock")
            if stock_val is not None and str(stock_val).strip() != "" and not pd.isna(stock_val):
                try:
                    stock_val = int(stock_val)
                except ValueError:
                    raise ValueError(f"Invalid stock value: '{stock_val}'. Must be a valid integer.")
            else:
                stock_val = None

            # Check if product already exists for this business
            existing = db.query(Inventory).filter(
                Inventory.product_name == product_name,
                Inventory.business_id == business_id
            ).first()
            
            if existing:
                # UPDATE existing record
                existing.stock = stock_val if stock_val is not None else existing.stock
                existing.expiry_date = row.get("expiry_date", existing.expiry_date)
                existing.supplier = row.get("supplier", existing.supplier)
                existing.file_id = file_id
            else:
                # INSERT new record
                inventory = Inventory(
                    product_name=product_name,
                    stock=stock_val,
                    expiry_date=row.get("expiry_date"),
                    supplier=row.get("supplier"),
                    business_id=business_id,
                    file_id=file_id
                )
                db.add(inventory)
        
        db.commit()
    except Exception as e:
        db.rollback()
        raise e

# ----------------------------

def save_payments(df, db, business_id, file_id=None):
    """
    Smart upsert for payments.
    If customer + due_date exists, update it. Otherwise insert.
    Prevents duplicates.
    Runs inside a transaction block to guarantee atomicity.
    """
    try:
        for _, row in df.iterrows():
            customer = row.get("customer")
            due_date = row.get("due_date")
            
            if not customer or not due_date:
                continue  # Skip incomplete records
            
            amount_val = row.get("amount")
            if amount_val is not None and str(amount_val).strip() != "" and not pd.isna(amount_val):
                try:
                    amount_val = float(amount_val)
                except ValueError:
                    raise ValueError(f"Invalid amount value: '{amount_val}'. Must be a valid number.")
            else:
                amount_val = None

            # Check if payment record already exists (by customer + due_date) for this business
            existing = db.query(Payment).filter(
                Payment.customer == customer,
                Payment.due_date == due_date,
                Payment.business_id == business_id
            ).first()
            
            if existing:
                # UPDATE existing record
                existing.amount = amount_val if amount_val is not None else existing.amount
                existing.paid = row.get("paid", existing.paid)
                existing.file_id = file_id
            else:
                # INSERT new record
                payment = Payment(
                    customer=customer,
                    amount=amount_val,
                    due_date=due_date,
                    paid=row.get("paid"),
                    business_id=business_id,
                    file_id=file_id
                )
                db.add(payment)
        
        db.commit()
    except Exception as e:
        db.rollback()
        raise e