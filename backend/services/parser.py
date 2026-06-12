import logging
import pandas as pd
from database.models import (
    Invoice,
    Inventory,
    Payment
)
from services.normalize import to_iso, normalize_status

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
            
            # Normalize at ingest (H3): dates → ISO, status → canonical case.
            status_val = normalize_status(row.get("status", existing.status if existing else None))
            inv_date_val = to_iso(row.get("invoice_date", existing.invoice_date if existing else None))
            due_date_val = to_iso(row.get("due_date", existing.due_date if existing else None))

            if existing:
                # UPDATE existing record
                existing.customer = row.get("customer", existing.customer)
                existing.product = row.get("product", existing.product)
                existing.amount = amount_val if amount_val is not None else existing.amount
                existing.status = status_val
                existing.invoice_date = inv_date_val
                existing.due_date = due_date_val
                existing.file_id = file_id
            else:
                # INSERT new record
                invoice = Invoice(
                    invoice_id=invoice_id,
                    customer=row.get("customer"),
                    product=row.get("product"),
                    amount=amount_val,
                    status=status_val,
                    invoice_date=inv_date_val,
                    due_date=due_date_val,
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
                    stock_val = int(float(stock_val))
                except ValueError:
                    raise ValueError(f"Invalid stock value: '{stock_val}'. Must be a valid integer.")
            else:
                stock_val = None

            def _num(key, cast):
                v = row.get(key)
                if v is None or str(v).strip() == "" or pd.isna(v):
                    return None
                try:
                    return cast(float(v))
                except (ValueError, TypeError):
                    return None

            cost_val    = _num("cost_price", float)
            sell_val    = _num("selling_price", float)
            reorder_val = _num("reorder_point", int)

            # Check if product already exists for this business
            existing = db.query(Inventory).filter(
                Inventory.product_name == product_name,
                Inventory.business_id == business_id
            ).first()

            # Normalize at ingest (H3): expiry date → ISO.
            expiry_val = to_iso(row.get("expiry_date", existing.expiry_date if existing else None))

            if existing:
                # UPDATE existing record
                existing.stock = stock_val if stock_val is not None else existing.stock
                existing.expiry_date = expiry_val
                existing.supplier = row.get("supplier", existing.supplier)
                if cost_val    is not None: existing.cost_price    = cost_val
                if sell_val    is not None: existing.selling_price = sell_val
                if reorder_val is not None: existing.reorder_point = reorder_val
                existing.file_id = file_id
            else:
                # INSERT new record
                inventory = Inventory(
                    product_name=product_name,
                    stock=stock_val,
                    expiry_date=expiry_val,
                    supplier=row.get("supplier"),
                    cost_price=cost_val,
                    selling_price=sell_val,
                    reorder_point=reorder_val if reorder_val is not None else 10,
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
            due_date = to_iso(row.get("due_date"))   # normalize at ingest (H3)

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