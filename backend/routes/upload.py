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
    Payment
)

from services.parser import (
    save_invoices,
    save_inventory,
    save_payments
)
from services.auth import get_active_user

router = APIRouter()

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

    # READ FILE
    if filename.endswith(".csv"):
        df = pd.read_csv(file.file)
    elif filename.endswith(".xlsx"):
        df = pd.read_excel(file.file)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format")

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
        raise HTTPException(status_code=400, detail="Could not detect schema/file type (unsupported columns)")

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
        invalidate_cache()  # bust context cache — new data uploaded

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

    db = SessionLocal()

    uploaded = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.business_id == active_user_id
    ).first()

    if not uploaded:
        db.close()
        raise HTTPException(status_code=404, detail="File not found")

    file_type = uploaded.file_type

    # Delete all database records parsed from this specific file (file_id matches)
    if file_type == "invoice":
        db.query(Invoice).filter(
            Invoice.file_id == file_id,
            Invoice.business_id == active_user_id
        ).delete()
    elif file_type == "inventory":
        db.query(Inventory).filter(
            Inventory.file_id == file_id,
            Inventory.business_id == active_user_id
        ).delete()
    elif file_type == "payment":
        db.query(Payment).filter(
            Payment.file_id == file_id,
            Payment.business_id == active_user_id
        ).delete()

    # delete the uploaded file record
    db.delete(uploaded)

    # optional cascade: delete all rows of that type for this business
    if cascade:
        if file_type == "invoice":
            db.query(Invoice).filter(Invoice.business_id == active_user_id).delete()

        elif file_type == "inventory":
            db.query(Inventory).filter(Inventory.business_id == active_user_id).delete()

        elif file_type == "payment":
            db.query(Payment).filter(Payment.business_id == active_user_id).delete()

    db.commit()
    invalidate_cache()   # bust context cache — data deleted

    db.close()

    return {
        "message": "deleted",
        "file_id": file_id,
        "cascade": cascade
    }