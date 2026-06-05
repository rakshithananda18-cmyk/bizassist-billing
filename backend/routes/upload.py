import hashlib
import logging
from services.context_cache import invalidate as invalidate_cache
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    HTTPException,
    Header,
    Depends
)

import pandas as pd
from datetime import datetime
from database.db import SessionLocal

from database.models import (
    UploadedFile,
    Invoice,
    Inventory,
    Payment,
    DocumentEmbedding
)

from services.parser import (
    save_invoices,
    save_inventory,
    save_payments
)
from services.auth import get_active_user
from services.rate_limiter import check_upload_rate_limit
from services.embeddings import index_new_file_records
from services.pdf_parser import (
    parse_pdf_text,
    extract_structured_invoice,
    save_pdf_invoice_to_db
)

router = APIRouter()
logger = logging.getLogger("bizassist.upload")

# -----------------------------------
# FILE UPLOAD
# -----------------------------------

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_active_user)
):
    active_user_id = current_user["id"]
    filename = file.filename

    # 1. Rate Limiting Check
    rl = check_upload_rate_limit(active_user_id)
    if not rl["allowed"]:
        raise HTTPException(status_code=429, detail=rl["reason"])

    logger.info(f"User {active_user_id} starting upload of file '{filename}'...")

    # 2. Chunked Reading and File Size Limitation
    MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
    MAX_ROW_COUNT = 1000

    content_length = file.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File size exceeds maximum limit of 5MB.")

    size = 0
    chunks = []
    try:
        while True:
            chunk = await file.read(65536)  # 64KB chunks
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(status_code=413, detail="File size exceeds maximum limit of 5MB.")
            chunks.append(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading chunks for file '{filename}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to read upload file: invalid format or corrupted file.")

    file_bytes = b"".join(chunks)

    # 3. Process according to format
    try:
        if filename.endswith(".pdf"):
            # Process PDF through structured parser
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            db = SessionLocal()
            try:
                existing_upload = db.query(UploadedFile).filter(
                    UploadedFile.file_hash == file_hash,
                    UploadedFile.business_id == active_user_id
                ).first()
                if existing_upload:
                    logger.warning(f"[Upload] Duplicate file detected for user {active_user_id}: '{filename}' (hash match with upload ID {existing_upload.id})")
                    raise HTTPException(
                        status_code=409,
                        detail=f"This file has already been uploaded (matched upload '{existing_upload.filename}' on {existing_upload.upload_time}). Upload a different file or wipe existing data first."
                    )
            finally:
                db.close()

            raw_text = parse_pdf_text(file_bytes)
            if not raw_text.strip():
                raise HTTPException(status_code=400, detail="Could not extract readable text from PDF. Ensure it is not a scanned image.")

            structured_data = extract_structured_invoice(raw_text)

            # Enforce limit of 200 items in structured PDF invoice
            items = structured_data.get("items", [])
            if len(items) > 200:
                raise HTTPException(status_code=400, detail="Too many invoice items in PDF. Maximum is 200.")

            save_result = save_pdf_invoice_to_db(structured_data, active_user_id, filename, file_hash=file_hash)
            
            invalidate_cache()
            
            return {
                "message": "Upload successful",
                "file_type": "invoice",
                "rows": save_result["items_count"],
                "added": save_result["items_count"],
                "updated": 0,
                "columns": ["invoice_id", "supplier", "customer", "invoice_date", "due_date", "total_amount", "items"]
            }
        elif filename.endswith(".csv") or filename.endswith(".xlsx"):
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # Duplicate check
            dup_db = SessionLocal()
            try:
                existing_upload = dup_db.query(UploadedFile).filter(
                    UploadedFile.file_hash == file_hash,
                    UploadedFile.business_id == active_user_id
                ).first()
                if existing_upload:
                    logger.warning(f"[Upload] Duplicate file detected for user {active_user_id}: '{filename}'")
                    raise HTTPException(
                        status_code=409,
                        detail=f"This file has already been uploaded (matched '{existing_upload.filename}' on {existing_upload.upload_time}). Upload a different file or wipe existing data first."
                    )
            finally:
                dup_db.close()

            import io
            if filename.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(file_bytes))
            else:
                df = pd.read_excel(io.BytesIO(file_bytes))

            # Enforce max row count
            if len(df) > MAX_ROW_COUNT:
                raise HTTPException(status_code=400, detail=f"Row count exceeds maximum limit of {MAX_ROW_COUNT} rows.")
        else:
            logger.warning(f"Failed upload attempt by user {active_user_id}: Unsupported file extension on '{filename}'")
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to parse upload file '{filename}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to parse file: invalid format or corrupted file.")

    # COLUMN DETECTION
    columns = [col.lower() for col in df.columns]
    db = SessionLocal()
    file_type = "unknown"
    stats = {"added": 0, "updated": 0}

    # Detect file type
    if "invoice_id" in columns:
        file_type = "invoice"
    elif "expiry_date" in columns:
        file_type = "inventory"
    elif "due_date" in columns:
        file_type = "payment"

    if file_type == "unknown":
        db.close()
        logger.warning(f"Unrecognized file schema in upload '{filename}' by user {active_user_id}. Columns: {columns}")
        raise HTTPException(status_code=400, detail="Could not detect schema/file type (unsupported columns)")

    logger.info(f"Detected file schema: {file_type} for file '{filename}' ({len(df)} rows) from user {active_user_id}.")
    try:
        # SAVE FILE HISTORY FIRST TO GENERATE FILE_ID WITHOUT COMMITTING
        uploaded_file = UploadedFile(
            filename=filename,
            file_type=file_type,
            rows_count=len(df),
            upload_time=str(datetime.now()),
            business_id=active_user_id,
            file_hash=file_hash if 'file_hash' in dir() else None
        )

        db.add(uploaded_file)
        db.flush()
        file_id = uploaded_file.id

        # PROCESS ACCORDING TO TYPE
        if file_type == "invoice":
            before = db.query(Invoice).filter(Invoice.business_id == active_user_id).count()
            save_invoices(df, db, active_user_id, file_id)
            after = db.query(Invoice).filter(Invoice.business_id == active_user_id).count()
            stats["added"] = max(0, after - before)
            stats["updated"] = len(df) - stats["added"]

        elif file_type == "inventory":
            before = db.query(Inventory).filter(Inventory.business_id == active_user_id).count()
            save_inventory(df, db, active_user_id, file_id)
            after = db.query(Inventory).filter(Inventory.business_id == active_user_id).count()
            stats["added"] = max(0, after - before)
            stats["updated"] = len(df) - stats["added"]

        elif file_type == "payment":
            before = db.query(Payment).filter(Payment.business_id == active_user_id).count()
            save_payments(df, db, active_user_id, file_id)
            after = db.query(Payment).filter(Payment.business_id == active_user_id).count()
            stats["added"] = max(0, after - before)
            stats["updated"] = len(df) - stats["added"]

        # Commit everything on success
        db.commit()

        # Generate and save document embeddings for semantic search (RAG)
        try:
            index_new_file_records(db, file_type, file_id, active_user_id)
        except Exception as embed_err:
            logger.error(f"Failed indexing file {file_id} embeddings: {embed_err}", exc_info=True)

        invalidate_cache()  # bust context cache — new data uploaded

        logger.info(f"Successfully processed {file_type} file upload '{filename}' for user {active_user_id}. Added: {stats['added']}, Updated: {stats['updated']}.")
        return {
            "message": "Upload successful",
            "file_type": file_type,
            "rows": len(df),
            "added": stats["added"],
            "updated": stats["updated"],
            "columns": columns
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error parsing file upload '{filename}' for user_id={active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to process file upload. Please verify the file structure.")
    finally:
        db.close()


# -----------------------------------
# GET UPLOAD DATA (rows for a specific upload)
# -----------------------------------

@router.get("/upload/{file_id}/data")
async def get_upload_data(
    file_id: int,
    current_user: dict = Depends(get_active_user)
):
    active_user_id = current_user["id"]
    db = SessionLocal()
    try:
        uploaded = db.query(UploadedFile).filter(
            UploadedFile.id == file_id,
            UploadedFile.business_id == active_user_id
        ).first()
        if not uploaded:
            raise HTTPException(status_code=404, detail="File not found")

        file_type = uploaded.file_type
        rows = []
        columns = []

        if file_type == "invoice":
            records = db.query(Invoice).filter(
                Invoice.file_id == file_id,
                Invoice.business_id == active_user_id
            ).all()
            columns = ["invoice_id", "customer", "product", "amount", "status", "due_date"]
            rows = [
                {
                    "invoice_id": r.invoice_id or "",
                    "customer": r.customer or "",
                    "product": r.product or "",
                    "amount": r.amount or 0,
                    "status": r.status or "",
                    "due_date": r.due_date or ""
                }
                for r in records
            ]
        elif file_type == "inventory":
            records = db.query(Inventory).filter(
                Inventory.file_id == file_id,
                Inventory.business_id == active_user_id
            ).all()
            columns = ["product_name", "stock", "expiry_date", "supplier"]
            rows = [
                {
                    "product_name": r.product_name or "",
                    "stock": r.stock or 0,
                    "expiry_date": r.expiry_date or "",
                    "supplier": r.supplier or ""
                }
                for r in records
            ]
        elif file_type == "payment":
            records = db.query(Payment).filter(
                Payment.file_id == file_id,
                Payment.business_id == active_user_id
            ).all()
            columns = ["customer", "amount", "due_date", "paid"]
            rows = [
                {
                    "customer": r.customer or "",
                    "amount": r.amount or 0,
                    "due_date": r.due_date or "",
                    "paid": r.paid or ""
                }
                for r in records
            ]

        return {
            "filename": uploaded.filename,
            "file_type": file_type,
            "total_rows": len(rows),
            "columns": columns,
            "rows": rows
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching upload data for file_id={file_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch upload data.")
    finally:
        db.close()


# -----------------------------------
# DELETE UPLOAD
# -----------------------------------


@router.delete("/upload/{file_id}")
async def delete_upload(
    file_id: int, 
    cascade: bool = False,
    current_user: dict = Depends(get_active_user)
):
    active_user_id = current_user["id"]
    logger.info(f"User {active_user_id} requesting deletion of upload file ID {file_id} (cascade={cascade})...")

    db = SessionLocal()
    try:
        uploaded = db.query(UploadedFile).filter(
            UploadedFile.id == file_id,
            UploadedFile.business_id == active_user_id
        ).first()

        if not uploaded:
            logger.warning(f"Deletion failed: Upload file ID {file_id} not found or doesn't belong to user {active_user_id}")
            db.close()
            raise HTTPException(status_code=404, detail="File not found")

        file_type = uploaded.file_type
        logger.info(f"Deleting upload record for file '{uploaded.filename}' of type '{file_type}'...")

        # Delete ALL database records parsed from this specific file (by file_id).
        # A single upload can populate multiple tables — e.g. a PDF invoice
        # writes Invoice + Inventory + Payment rows under one file_id — so we
        # purge from every table by file_id rather than only the table matching
        # the recorded file_type. Otherwise inventory/payment rows are orphaned.
        del_invoices = db.query(Invoice).filter(
            Invoice.file_id == file_id,
            Invoice.business_id == active_user_id
        ).delete()
        del_inventory = db.query(Inventory).filter(
            Inventory.file_id == file_id,
            Inventory.business_id == active_user_id
        ).delete()
        del_payments = db.query(Payment).filter(
            Payment.file_id == file_id,
            Payment.business_id == active_user_id
        ).delete()
        logger.info(
            f"Deleted records for file {file_id} — invoices: {del_invoices}, "
            f"inventory: {del_inventory}, payments: {del_payments}."
        )

        # delete the uploaded file record
        db.delete(uploaded)

        # Delete associated document embeddings
        deleted_embs = db.query(DocumentEmbedding).filter(
            DocumentEmbedding.file_id == file_id,
            DocumentEmbedding.business_id == active_user_id
        ).delete()
        logger.info(f"Deleted {deleted_embs} associated DocumentEmbedding records.")

        # Sync deletion with Chroma persistent vector database
        try:
            from services.embeddings import delete_file_chroma_embeddings
            delete_file_chroma_embeddings(file_id, active_user_id)
        except Exception as chroma_err:
            logger.error(f"Error purging Chroma document embeddings: {chroma_err}", exc_info=True)

        # optional cascade: delete all rows of that type for this business
        if cascade:
            logger.info(f"Cascading deletion of all '{file_type}' records for user {active_user_id}...")
            if file_type == "invoice":
                deleted_all = db.query(Invoice).filter(Invoice.business_id == active_user_id).delete()
                logger.info(f"Cascaded delete of all invoices: {deleted_all} records removed.")
            elif file_type == "inventory":
                deleted_all = db.query(Inventory).filter(Inventory.business_id == active_user_id).delete()
                logger.info(f"Cascaded delete of all inventory: {deleted_all} records removed.")
            elif file_type == "payment":
                deleted_all = db.query(Payment).filter(Payment.business_id == active_user_id).delete()
                logger.info(f"Cascaded delete of all payments: {deleted_all} records removed.")

        db.commit()
        invalidate_cache()   # bust context cache — data deleted
        logger.info(f"Successfully deleted file ID {file_id} and committed database changes.")

        return {
            "message": "deleted",
            "file_id": file_id,
            "cascade": cascade
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error during deletion of file ID {file_id} for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database deletion failed.")
    finally:
        db.close()