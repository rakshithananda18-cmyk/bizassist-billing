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

    logger.info(f"User {active_user_id} starting upload of file '{filename}'...")

    # READ FILE
    try:
        if filename.endswith(".pdf"):
            # Process PDF through structured parser
            file_bytes = await file.read()
            raw_text = parse_pdf_text(file_bytes)
            if not raw_text.strip():
                raise HTTPException(status_code=400, detail="Could not extract readable text from PDF. Ensure it is not a scanned image.")
            
            structured_data = extract_structured_invoice(raw_text)
            save_result = save_pdf_invoice_to_db(structured_data, active_user_id, filename)
            
            invalidate_cache()
            
            return {
                "message": "Upload successful",
                "file_type": "invoice",
                "rows": save_result["items_count"],
                "added": save_result["items_count"],
                "updated": 0,
                "columns": ["invoice_id", "supplier", "customer", "invoice_date", "due_date", "total_amount", "items"]
            }
        elif filename.endswith(".csv"):
            df = pd.read_csv(file.file)
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(file.file)
        else:
            logger.warning(f"Failed upload attempt by user {active_user_id}: Unsupported file extension on '{filename}'")
            raise HTTPException(status_code=400, detail="Unsupported file format")
    except Exception as e:
        logger.error(f"Failed to read upload file '{filename}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

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
            business_id=active_user_id
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
    except Exception as e:
        db.rollback()
        logger.error(f"Error parsing file upload '{filename}' for user_id={active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
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

        # Delete all database records parsed from this specific file (file_id matches)
        if file_type == "invoice":
            deleted = db.query(Invoice).filter(
                Invoice.file_id == file_id,
                Invoice.business_id == active_user_id
            ).delete()
            logger.info(f"Deleted {deleted} associated Invoice records.")
        elif file_type == "inventory":
            deleted = db.query(Inventory).filter(
                Inventory.file_id == file_id,
                Inventory.business_id == active_user_id
            ).delete()
            logger.info(f"Deleted {deleted} associated Inventory records.")
        elif file_type == "payment":
            deleted = db.query(Payment).filter(
                Payment.file_id == file_id,
                Payment.business_id == active_user_id
            ).delete()
            logger.info(f"Deleted {deleted} associated Payment records.")

        # delete the uploaded file record
        db.delete(uploaded)

        # Delete associated document embeddings
        deleted_embs = db.query(DocumentEmbedding).filter(
            DocumentEmbedding.file_id == file_id,
            DocumentEmbedding.business_id == active_user_id
        ).delete()
        logger.info(f"Deleted {deleted_embs} associated DocumentEmbedding records.")

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
    except Exception as e:
        db.rollback()
        logger.error(f"Error during deletion of file ID {file_id} for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database deletion failed: {str(e)}")
    finally:
        db.close()