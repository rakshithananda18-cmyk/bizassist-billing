import os
import json
import logging
import pypdf
import io
from typing import Optional, Dict, Any
from groq import Groq
import anthropic
from database.db import SessionLocal
from database.models import UploadedFile, Invoice, Inventory, Payment
from services.embeddings import index_new_file_records
from datetime import datetime

logger = logging.getLogger("bizassist.pdf_parser")

def parse_pdf_text(file_bytes: bytes) -> str:
    """Extracts raw text from PDF file bytes using pypdf."""
    raw_text = ""
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = pypdf.PdfReader(pdf_file)
        logger.info(f"Extracting text from PDF (pages count: {len(reader.pages)})")
        for idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                raw_text += text + "\n"
        logger.info(f"Extracted {len(raw_text)} characters of text from PDF.")
        return raw_text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}", exc_info=True)
        raise ValueError(f"Failed to read PDF file: {str(e)}")

def extract_structured_invoice(raw_text: str) -> dict:
    """
    Sends raw invoice text to LLM (OpenAI, Groq, or Claude fallback chain)
    instructed to output a JSON object adhering strictly to the schema.
    """
    system_prompt = (
        "You are a precise data extraction agent. Extract structured billing, invoice, and inventory information "
        "from the provided raw invoice text. You must output a JSON object only. Do NOT output markdown code blocks (e.g. ```json), "
        "preamble, or explanations. The JSON output must strictly conform to the following schema:\n\n"
        "{\n"
        "  \"invoice_id\": \"string (e.g. INV-1002, 2901-A)\",\n"
        "  \"supplier\": \"string (name of company/vendor selling the items)\",\n"
        "  \"customer\": \"string (name of business buying the items, e.g. MediCare Pharmacy)\",\n"
        "  \"invoice_date\": \"string (format YYYY-MM-DD, e.g. 2026-05-12)\",\n"
        "  \"due_date\": \"string or null (format YYYY-MM-DD, e.g. 2026-06-12, or null)\",\n"
        "  \"total_amount\": \"number (grand total invoice value)\",\n"
        "  \"status\": \"string (must be 'Paid', 'Pending', or 'Overdue')\",\n"
        "  \"items\": [\n"
        "    {\n"
        "      \"product_name\": \"string (name of medicine or product)\",\n"
        "      \"stock\": \"integer (quantity purchased/added)\",\n"
        "      \"expiry_date\": \"string or null (format YYYY-MM-DD, or null)\",\n"
        "      \"price_per_unit\": \"number (unit price of this item)\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    user_content = f"Raw Invoice Text:\n{raw_text}\n\nStrict JSON Output:"

    # 1. Try Groq (primary — free, fast, reliable JSON mode)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            logger.info("Extracting invoice structure using Groq (llama-3.3-70b-versatile)...")
            client = Groq(api_key=groq_key)
            model = "llama-3.3-70b-versatile"
            
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            logger.warning(f"Groq extraction failed: {str(e)}. Attempting fallback to Claude...")

    # 2. Fallback: Anthropic/Claude
    claude_key = os.getenv("CLAUDE_API_KEY")
    if claude_key:
        try:
            logger.info("Extracting invoice structure using Anthropic (claude-3-5-sonnet-20241022)...")
            client = anthropic.Anthropic(api_key=claude_key)
            
            # Construct message
            message = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0
            )
            response_text = message.content[0].text.strip()
            
            # Strip markdown block indicators if Claude returned them despite instructions
            if response_text.startswith("```"):
                lines = response_text.splitlines()
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    lines = lines[1:-1]
                response_text = "\n".join(lines).strip()
                
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Anthropic extraction failed: {str(e)}")
            raise e

    raise ValueError("No configured LLM API keys (GROQ_API_KEY or CLAUDE_API_KEY) found for PDF extraction.")

def save_pdf_invoice_to_db(data: dict, business_id: int, filename: str, file_hash: str = None) -> dict:
    """Saves parsed JSON invoice structured details into the standard BIZASSIST tables."""
    db = SessionLocal()
    try:
        # Validate data format
        items = data.get("items", [])
        if not items:
            raise ValueError("No items found in extracted PDF invoice data.")

        # 1. Save upload history file log
        upload_log = UploadedFile(
            filename=filename,
            file_type="invoice",
            rows_count=len(items),
            upload_time=str(datetime.now()),
            business_id=business_id,
            file_hash=file_hash
        )
        db.add(upload_log)
        db.flush()
        file_id = upload_log.id

        # 2. Add Invoice and Inventory records for each line item
        for item in items:
            product_name = item.get("product_name")
            if not product_name:
                continue

            stock_qty = item.get("stock", 0)
            try:
                stock_qty = int(stock_qty)
            except (ValueError, TypeError):
                stock_qty = 0

            unit_price = item.get("price_per_unit", 0.0)
            try:
                unit_price = float(unit_price)
            except (ValueError, TypeError):
                unit_price = 0.0

            # Line item amount is price_per_unit * quantity
            line_amount = unit_price * stock_qty

            # Upsert invoice line — check invoice_id + product + business_id to prevent duplicates
            invoice_id_val = data.get("invoice_id")
            existing_inv = db.query(Invoice).filter(
                Invoice.invoice_id   == invoice_id_val,
                Invoice.product      == product_name,
                Invoice.business_id  == business_id
            ).first()

            if existing_inv:
                existing_inv.amount       = line_amount
                existing_inv.status       = data.get("status", existing_inv.status)
                existing_inv.invoice_date = data.get("invoice_date", existing_inv.invoice_date)
                existing_inv.due_date     = data.get("due_date", existing_inv.due_date)
                existing_inv.file_id      = file_id
                logger.info(f"[PDF Parser] Updated existing invoice line: {invoice_id_val} / {product_name}")
            else:
                invoice_record = Invoice(
                    business_id=business_id,
                    file_id=file_id,
                    invoice_id=invoice_id_val,
                    customer=data.get("customer"),
                    product=product_name,
                    amount=line_amount,
                    status=data.get("status", "Pending"),
                    invoice_date=data.get("invoice_date"),
                    due_date=data.get("due_date")
                )
                db.add(invoice_record)

            # Smart upsert for Inventory
            existing_inventory = db.query(Inventory).filter(
                Inventory.product_name == product_name,
                Inventory.business_id == business_id
            ).first()

            if existing_inventory:
                # Update existing inventory (override or accumulate)
                existing_inventory.stock = stock_qty
                existing_inventory.expiry_date = item.get("expiry_date", existing_inventory.expiry_date)
                existing_inventory.supplier = data.get("supplier", existing_inventory.supplier)
                existing_inventory.file_id = file_id
            else:
                # Create new inventory record
                new_inventory = Inventory(
                    business_id=business_id,
                    file_id=file_id,
                    product_name=product_name,
                    stock=stock_qty,
                    expiry_date=item.get("expiry_date"),
                    supplier=data.get("supplier")
                )
                db.add(new_inventory)

        # 3. Add to Payments/Dues tracking
        total_invoice_amount = data.get("total_amount", 0.0)
        try:
            total_invoice_amount = float(total_invoice_amount)
        except (ValueError, TypeError):
            total_invoice_amount = 0.0

        payment_status = "Yes" if data.get("status") == "Paid" else "No"

        # Check if a payment for this customer + due_date already exists to avoid duplication
        existing_payment = db.query(Payment).filter(
            Payment.customer == data.get("customer"),
            Payment.due_date == data.get("due_date"),
            Payment.business_id == business_id
        ).first()

        if existing_payment:
            existing_payment.amount = total_invoice_amount
            existing_payment.paid = payment_status
            existing_payment.file_id = file_id
        else:
            new_payment = Payment(
                business_id=business_id,
                file_id=file_id,
                customer=data.get("customer"),
                amount=total_invoice_amount,
                due_date=data.get("due_date"),
                paid=payment_status
            )
            db.add(new_payment)

        db.commit()

        # 4. Generate & Index Embeddings for RAG (semantic vector search) on Invoices, Inventory, and Payments
        try:
            index_new_file_records(db, "invoice", file_id, business_id)
            index_new_file_records(db, "inventory", file_id, business_id)
            index_new_file_records(db, "payment", file_id, business_id)
        except Exception as embed_err:
            logger.error(f"Failed RAG indexing for PDF file ID {file_id}: {embed_err}", exc_info=True)

        logger.info(f"Successfully saved and indexed parsed PDF invoice '{filename}' for business ID {business_id}.")
        return {
            "status": "success",
            "file_id": file_id,
            "invoice_id": data.get("invoice_id"),
            "items_count": len(items),
            "total_amount": total_invoice_amount
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error saving PDF invoice to database: {str(e)}", exc_info=True)
        raise e
    finally:
        db.close()
