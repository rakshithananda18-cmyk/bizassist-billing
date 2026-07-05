"""
routes/feedback.py
==================
Answer-quality feedback. Thumbs up/down on an answer; a thumbs-down may name the
intent the user actually wanted, which creates an instant per-query override.

  POST /feedback   {session_id?, query, route?, handler_key?, verdict, correction?}
  GET  /feedback/intents   -> the list of correctable intents (for the UI picker)
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import get_active_user, restrict_cashier
from services.feedback_service import record_feedback, CORRECTION_ROUTES

logger = logging.getLogger("bizassist.routes.feedback")
router = APIRouter()


class FeedbackRequest(BaseModel):
    query:       str
    verdict:     str                      # 'up' | 'down'
    session_id:  Optional[str] = None
    route:       Optional[str] = None
    handler_key: Optional[str] = None
    correction:  Optional[str] = None     # an intent key from /feedback/intents


# Human labels for the correctable intents (drives the down-vote picker).
_INTENT_LABELS = {
    "overdue_list":     "Overdue invoices",
    "overdue_amount":   "Total overdue amount",
    "pending_list":     "Pending invoices",
    "total_revenue":    "Revenue / sales",
    "invoice_count":    "Invoice count",
    "top_customers":    "Top customers",
    "top_debtors":      "Top debtors",
    "inventory_count":  "Inventory count",
    "low_stock":        "Low stock",
    "expiring_soon":    "Expiring soon",
    "client_summary":   "A specific customer",
    "business_summary": "Business overview",
    "ai_complex":       "Deep analysis / plan",
    "ai_simple":        "Write / draft something",
    "conversational":   "Just chatting",
}


@router.get("/feedback/intents")
def feedback_intents(current_user: dict = Depends(restrict_cashier)):
    """The correctable intents, in display order, for the 'what did you want?' picker."""
    return {"intents": [
        {"key": k, "label": _INTENT_LABELS.get(k, k)}
        for k in CORRECTION_ROUTES
    ]}


@router.post("/feedback")
def submit_feedback(body: FeedbackRequest, current_user: dict = Depends(restrict_cashier)):
    if not (body.query or "").strip():
        raise HTTPException(status_code=400, detail="query is required")

    result = record_feedback(
        current_user["id"],
        session_id=body.session_id,
        query=body.query,
        route=body.route,
        handler_key=body.handler_key,
        verdict=body.verdict,
        correction=body.correction,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "feedback failed"))

    return {
        "ok": True,
        "override": result["override"],
        "message": ("Got it — I'll answer that the right way next time."
                    if result["override"] else "Thanks for the feedback."),
    }


from fastapi import File, UploadFile, Form
import shutil
import os
from datetime import datetime

@router.post("/feedback/submit")
async def submit_merchant_feedback(
    message: str = Form(...),
    attach_logs: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_active_user)
):
    """Submit support feedback. On local, forwards to cloud with logs zipped. On cloud, stores feedback & logs file on disk."""
    from database.db import engine
    is_cloud = engine.dialect.name == "postgresql"
    
    business_id = current_user.get("id")
    username = current_user.get("username")
    
    if not is_cloud:
        # ── LOCAL CLIENT BEHAVIOR ──
        archive_path = None
        if attach_logs:
            from services.log_uploader import archive_logs
            archive_path = archive_logs(business_id)
            
        from services.sync_worker import _get_cloud_token, CLOUD_URL
        token = _get_cloud_token(business_id)
        if not token:
            raise HTTPException(status_code=400, detail="Cloud integration is not enabled.")
            
        url = f"{CLOUD_URL}/feedback/submit"
        try:
            import httpx
            headers = {"Authorization": f"Bearer {token}"}
            # FastAPI Form parsing requires string values
            data = {"message": message, "attach_logs": "true" if attach_logs else "false"}
            
            files = None
            if archive_path and os.path.exists(archive_path):
                f = open(archive_path, "rb")
                files = {"file": (os.path.basename(archive_path), f, "application/gzip")}
                
            resp = httpx.post(url, data=data, files=files, headers=headers, timeout=30.0)
            
            if files:
                f.close()
                try:
                    os.remove(archive_path)
                except Exception:
                    pass
                    
            if resp.status_code == 200:
                return {"ok": True, "message": "Feedback and logs submitted to cloud successfully."}
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"Cloud upload failed: {resp.text}")
        except Exception as e:
            logger.error("Failed to forward feedback to cloud: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {e}")
            
    else:
        # ── CLOUD RECEIVER BEHAVIOR ──
        # Save feedback text to user_feedback table
        from database.db import SessionLocal
        db = SessionLocal()
        try:
            log_file_path = None
            if file:
                upload_dir = os.path.join("logs", "remote_clients", str(business_id))
                os.makedirs(upload_dir, exist_ok=True)
                
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                filename = f"feedback_{timestamp}_{file.filename}"
                dest_path = os.path.join(upload_dir, filename)
                
                with open(dest_path, "wb") as f_out:
                    shutil.copyfileobj(file.file, f_out)
                log_file_path = dest_path.replace("\\", "/")
                
            from database.models import UserFeedback
            feedback_row = UserFeedback(
                business_id=business_id,
                username=username,
                message=message,
                log_file_path=log_file_path,
                created_at=datetime.utcnow()
            )
            db.add(feedback_row)
            db.commit()
            return {"ok": True, "message": "Feedback received successfully."}
        except Exception as e:
            db.rollback()
            logger.error("Failed to save feedback on cloud: %s", e)
            raise HTTPException(status_code=500, detail="Internal server error saving feedback.")
        finally:
            db.close()


@router.get("/diagnostics/logs")
def download_diagnostics_logs(current_user: dict = Depends(get_active_user)):
    """Build and stream a .tar.gz of THIS backend's diagnostic logs so the user
    can download them (Settings → "Download logs") and share them for debugging.

    Collects, if present: the app log file (LOG_FILE env, else logs/bizassist.log)
    and its rotations, plus the admin audit log. No business data — only app logs.
    """
    import io, os, glob, tarfile
    from datetime import datetime as _dt
    from fastapi.responses import StreamingResponse

    candidates = []
    log_file = os.getenv("LOG_FILE") or os.path.join("logs", "bizassist.log")
    # the file + any rotations (bizassist.log.1, .2, …)
    candidates.extend(sorted(glob.glob(log_file + "*")))
    for extra in (os.path.join("logs", "admin_audit.jsonl"),):
        if os.path.exists(extra):
            candidates.append(extra)

    existing = [p for p in dict.fromkeys(candidates) if os.path.isfile(p)]

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if existing:
            for p in existing:
                try:
                    tar.add(p, arcname=os.path.basename(p))
                except Exception as ex:
                    logger.warning("diagnostics: could not add %s: %s", p, ex)
        else:
            # Never hand back an empty/confusing archive — include a note.
            note = (
                "No on-disk log file was found on this backend.\n"
                "On the desktop app, backend logs are also captured in the app's "
                "Electron log (main.log) under %APPDATA%\\<app>\\logs.\n"
            ).encode("utf-8")
            info = tarfile.TarInfo(name="README.txt")
            info.size = len(note)
            tar.addfile(info, io.BytesIO(note))
    buf.seek(0)

    fname = f"bizassist-logs-{_dt.utcnow().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    logger.info("[DIAGNOSTICS] Served %d log file(s) to user '%s'", len(existing), current_user.get("username"))
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
