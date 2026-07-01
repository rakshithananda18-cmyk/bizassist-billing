import hashlib
import io
import logging
from services.context_cache import invalidate_user_cache
from services.column_mapper import normalize_dataframe
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
from sqlalchemy.orm import Session
from database.db import SessionLocal, get_db

from database.models import (
    UploadedFile,
    Invoice,
    Inventory,
    LegacyPayment,
    DocumentEmbedding
)

from services.parser import (
    save_invoices,
    save_inventory,
    save_payments
)
from services.auth import get_active_user, restrict_cashier
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
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
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

            raw_text = parse_pdf_text(file_bytes)   # OCR-aware: handles scanned PDFs automatically
            if not raw_text.strip():
                raise HTTPException(status_code=400, detail="Could not extract readable text from this PDF even after OCR. Check scan quality (min 300 dpi).")

            structured_data = extract_structured_invoice(raw_text)

            # Enforce limit of 200 items in structured PDF invoice
            items = structured_data.get("items", [])
            if len(items) > 200:
                raise HTTPException(status_code=400, detail="Too many invoice items in PDF. Maximum is 200.")

            save_result = save_pdf_invoice_to_db(structured_data, active_user_id, filename, file_hash=file_hash)

            invalidate_user_cache(active_user_id)   # bust only this tenant's cache

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
            existing_upload = db.query(UploadedFile).filter(
                UploadedFile.file_hash == file_hash,
                UploadedFile.business_id == active_user_id
            ).first()
            if existing_upload:
                logger.warning(f"[Upload] Duplicate file detected for user {active_user_id}: '{filename}'")
                raise HTTPException(
                    status_code=409,
                    detail=f"This file has already been uploaded (matched '{existing_upload.filename}' on {existing_upload.upload_time}). Upload a different file or wipe existing data first."
                )

            import io
            if filename.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(file_bytes))
            else:
                df = pd.read_excel(io.BytesIO(file_bytes))

            # Enforce max row count
            if len(df) > MAX_ROW_COUNT:
                raise HTTPException(status_code=400, detail=f"Row count exceeds maximum limit of {MAX_ROW_COUNT} rows.")
        elif filename.endswith(".zip"):
            return await _process_zip_upload(file_bytes, active_user_id, filename)
        else:
            logger.warning(f"Failed upload attempt by user {active_user_id}: Unsupported file extension on '{filename}'")
            raise HTTPException(status_code=400, detail="Unsupported file format. Accepted: .csv, .xlsx, .pdf, .zip")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to parse upload file '{filename}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to parse file: invalid format or corrupted file.")

    # ── ADAPTIVE COLUMN MAPPING ──────────────────────────────────────────────
    # Normalises ANY column naming convention to canonical field names.
    # Works for Tally exports, shop Excel, pharmacy sheets, etc.
    mapping_result = normalize_dataframe(df, filename=filename)

    if mapping_result.detected_type == "unknown" or mapping_result.confidence < 0.3:
        logger.warning(
            f"Unrecognized schema in '{filename}' by user {active_user_id}. "
            f"Columns: {df.columns.tolist()} | "
            f"Mapped: {mapping_result.mapping} | Confidence: {mapping_result.confidence:.2f}"
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not recognise this file's columns. "
                f"Detected columns: {df.columns.tolist()}. "
                f"Expected: invoice columns (invoice_id/customer/amount), "
                f"inventory columns (product_name/stock), or payment columns."
            )
        )

    # Use the renamed DataFrame from here on — canonical column names guaranteed
    df        = mapping_result.renamed_df
    file_type = mapping_result.detected_type
    columns   = list(mapping_result.mapping.values())

    logger.info(
        f"[Upload] file='{filename}' type={file_type} confidence={mapping_result.confidence:.2f} "
        f"mapping={mapping_result.mapping} warnings={mapping_result.warnings}"
    )

    stats = {"added": 0, "updated": 0}
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
            # This analytics ingest keeps only name/stock/supplier/cost/sell/reorder.
            # For a full product import (SKU, barcode, HSN, MRP, GST rates, opening
            # stock → ledger), steer the user to the billing app's Import screen.
            mapping_result.warnings.append(
                "Imported for analytics only — SKU, barcode, HSN, MRP and GST rates "
                "were not stored. To import products with full details (and seed opening "
                "stock), use the billing app's Import screen (Products → Import)."
            )

        elif file_type == "payment":
            before = db.query(LegacyPayment).filter(LegacyPayment.business_id == active_user_id).count()
            save_payments(df, db, active_user_id, file_id)
            after = db.query(LegacyPayment).filter(LegacyPayment.business_id == active_user_id).count()
            stats["added"] = max(0, after - before)
            stats["updated"] = len(df) - stats["added"]

        # Commit everything on success
        db.commit()

        # Generate and save document embeddings for semantic search (RAG)
        try:
            index_new_file_records(db, file_type, file_id, active_user_id)
        except Exception as embed_err:
            logger.error(f"Failed indexing file {file_id} embeddings: {embed_err}", exc_info=True)

        invalidate_user_cache(active_user_id)  # bust only this tenant's cache — new data uploaded

        logger.info(f"Successfully processed {file_type} upload '{filename}' for user {active_user_id}. Added: {stats['added']}, Updated: {stats['updated']}.")
        return {
            "message": "Upload successful",
            "file_type": file_type,
            "rows": len(df),
            "added": stats["added"],
            "updated": stats["updated"],
            "columns": columns,
            "column_mapping": mapping_result.mapping,
            "warnings": mapping_result.warnings,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error parsing file upload '{filename}' for user_id={active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to process file upload. Please verify the file structure.")


# -----------------------------------
# GET UPLOAD DATA (rows for a specific upload)
# -----------------------------------

@router.get("/upload/{file_id}/data")
async def get_upload_data(
    file_id: int,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    active_user_id = current_user["id"]
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
            records = db.query(LegacyPayment).filter(
                LegacyPayment.file_id == file_id,
                LegacyPayment.business_id == active_user_id
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


# -----------------------------------
# DELETE UPLOAD
# -----------------------------------


@router.delete("/upload/{file_id}")
async def delete_upload(
    file_id: int,
    cascade: bool = False,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    active_user_id = current_user["id"]
    logger.info(f"User {active_user_id} requesting deletion of upload file ID {file_id} (cascade={cascade})...")

    try:
        uploaded = db.query(UploadedFile).filter(
            UploadedFile.id == file_id,
            UploadedFile.business_id == active_user_id
        ).first()

        if not uploaded:
            logger.warning(f"Deletion failed: Upload file ID {file_id} not found or doesn't belong to user {active_user_id}")
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
        del_payments = db.query(LegacyPayment).filter(
            LegacyPayment.file_id == file_id,
            LegacyPayment.business_id == active_user_id
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
                deleted_all = db.query(LegacyPayment).filter(LegacyPayment.business_id == active_user_id).delete()
                logger.info(f"Cascaded delete of all payments: {deleted_all} records removed.")

        db.commit()
        invalidate_user_cache(active_user_id)   # bust only this tenant's cache -- data deleted
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


# ---------------------------------------------------------------------------
# ZIP UPLOAD HELPER  (called inline from upload_file)
# ---------------------------------------------------------------------------

async def _process_zip_upload(zip_bytes: bytes, business_id: int, zip_filename: str) -> dict:
    """
    Extract every .pdf from a ZIP archive and process each through the
    full OCR-aware PDF pipeline.  Returns an aggregated result summary.

    Rules:
      - Max 20 PDFs per ZIP (to cap processing time)
      - Max 10 MB ZIP (generous for a batch of invoices)
      - Each PDF follows the same duplicate-hash check as single-file upload
      - Partial success: failures are recorded per-file, not bubbled as 500
    """
    import zipfile

    MAX_ZIP_SIZE  = 10 * 1024 * 1024   # 10 MB
    MAX_PDF_COUNT = 20

    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="ZIP file exceeds 10 MB limit.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid or corrupted ZIP file.")

    pdf_names = [
        name for name in zf.namelist()
        if name.lower().endswith(".pdf") and not name.startswith("__MACOSX")
    ]

    if not pdf_names:
        raise HTTPException(status_code=400, detail="ZIP contains no PDF files.")

    if len(pdf_names) > MAX_PDF_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"ZIP contains {len(pdf_names)} PDFs — maximum is {MAX_PDF_COUNT} per batch."
        )

    logger.info(f"[ZIP] Processing {len(pdf_names)} PDF(s) from '{zip_filename}' for user {business_id}.")

    results    = []
    total_rows = 0
    db         = SessionLocal()

    for pdf_name in pdf_names:
        short_name = pdf_name.split("/")[-1]   # strip folder prefix
        try:
            pdf_bytes = zf.read(pdf_name)

            # Duplicate check per PDF
            file_hash = hashlib.sha256(pdf_bytes).hexdigest()
            existing = db.query(UploadedFile).filter(
                UploadedFile.file_hash == file_hash,
                UploadedFile.business_id == business_id
            ).first()
            if existing:
                results.append({
                    "file":   short_name,
                    "status": "skipped",
                    "reason": f"duplicate of '{existing.filename}' (uploaded {existing.upload_time})"
                })
                continue

            # OCR-aware extraction → structured data → DB
            raw_text    = parse_pdf_text(pdf_bytes)
            structured  = extract_structured_invoice(raw_text)
            save_result = save_pdf_invoice_to_db(structured, business_id, short_name, file_hash=file_hash)

            total_rows += save_result["items_count"]
            results.append({
                "file":       short_name,
                "status":     "ok",
                "invoice_id": save_result["invoice_id"],
                "items":      save_result["items_count"],
                "amount":     save_result["total_amount"]
            })
            logger.info(f"[ZIP] '{short_name}' → {save_result['items_count']} items saved.")

        except Exception as e:
            logger.warning(f"[ZIP] '{short_name}' failed: {e}")
            results.append({"file": short_name, "status": "error", "reason": str(e)})

    db.close()
    zf.close()
    invalidate_user_cache(business_id)   # bust only this tenant's cache

    ok_count      = sum(1 for r in results if r["status"] == "ok")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    error_count   = sum(1 for r in results if r["status"] == "error")

    logger.info(
        f"[ZIP] '{zip_filename}': {ok_count} ok, {skipped_count} skipped, "
        f"{error_count} errors — {total_rows} total items saved."
    )

    return {
        "message":   f"ZIP processed: {ok_count} imported, {skipped_count} skipped, {error_count} failed",
        "file_type": "zip",
        "rows":      total_rows,
        "files":     results
    }
