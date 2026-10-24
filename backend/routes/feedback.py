"""
routes/feedback.py
==================
Answer-quality feedback. Thumbs up/down on an answer; a thumbs-down may name the
intent the user actually wanted, which creates an instant per-query override.

  POST /feedback   {session_id?, query, route?, handler_key?, verdict, correction?}
  GET  /feedback/intents   -> the list of correctable intents (for the UI picker)
"""
from services.dates import utc_now
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import get_active_user, restrict_cashier, require_business_owner
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
import os
from pathlib import Path
from uuid import uuid4


_MAX_FEEDBACK_MESSAGE_CHARS = 8_000
_MAX_FEEDBACK_UPLOAD_BYTES = 5 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 64 * 1024
_ALLOWED_LOG_CONTENT_TYPES = {
    "application/gzip",
    "application/x-gzip",
    "application/octet-stream",  # common browser label for a .tar.gz download
}


async def _store_bounded_log_upload(upload: UploadFile, destination: Path) -> None:
    """Stream an expected support archive with a hard byte limit.

    ``UploadFile`` can be backed by a temporary file, but it is still attacker
    controlled.  Do not use ``copyfileobj`` here: it has no byte ceiling.
    """
    total = 0
    try:
        with destination.open("xb") as out:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_FEEDBACK_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Support log archive exceeds the 5 MB limit.",
                    )
                out.write(chunk)
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise

@router.post("/feedback/submit")
async def submit_merchant_feedback(
    message: str = Form(...),
    attach_logs: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_active_user)
):
    """Submit support feedback. On local, forwards to cloud with logs zipped. On cloud, stores feedback & logs file on disk."""
    if not message.strip():
        raise HTTPException(status_code=422, detail="Feedback message is required.")
    if len(message) > _MAX_FEEDBACK_MESSAGE_CHARS:
        raise HTTPException(status_code=413, detail="Feedback message exceeds the 8,000 character limit.")

    if file:
        supplied_name = Path(file.filename or "").name
        if not supplied_name.lower().endswith((".gz", ".tgz", ".tar.gz")):
            raise HTTPException(status_code=415, detail="Only gzip-compressed support log archives are accepted.")
        if file.content_type and file.content_type.lower() not in _ALLOWED_LOG_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="Unsupported support log archive type.")
        declared_size = file.headers.get("content-length")
        try:
            if declared_size and int(declared_size) > _MAX_FEEDBACK_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Support log archive exceeds the 5 MB limit.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid support log Content-Length.")

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
                
                timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
                # Never use a client filename as a path component.  The random
                # suffix avoids overwrite races between simultaneous uploads.
                filename = f"feedback_{timestamp}_{uuid4().hex}.tar.gz"
                dest_path = Path(upload_dir) / filename
                await _store_bounded_log_upload(file, dest_path)
                log_file_path = str(dest_path).replace("\\", "/")
                
            from database.models import UserFeedback
            feedback_row = UserFeedback(
                business_id=business_id,
                username=username,
                message=message,
                log_file_path=log_file_path,
                created_at=utc_now()
            )
            db.add(feedback_row)
            db.commit()
            return {"ok": True, "message": "Feedback received successfully."}
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("Failed to save feedback on cloud: %s", e)
            raise HTTPException(status_code=500, detail="Internal server error saving feedback.")
        finally:
            db.close()


def _on_cloud_db() -> bool:
    """True on the shared cloud database (Postgres); a desktop runs SQLite."""
    from database.db import engine
    return engine.dialect.name == "postgresql"


@router.get("/diagnostics/logs")
def download_diagnostics_logs(current_user: dict = Depends(restrict_cashier)):
    """Build and stream a .tar.gz of THIS backend's diagnostic logs so the user
    can download them (Settings → "Download logs") and share them for debugging.

    Collects, if present: the app log file (LOG_FILE env, else logs/bizassist.log)
    and its rotations. The Admin Console's audit log is never included.

    Owners only. On a desktop that is the owner's own computer's log. On the
    cloud the log covers EVERY customer's requests (and every sign-in typed),
    so there only the platform admin may download it.
    """
    import io, os, glob, tarfile
    from fastapi.responses import StreamingResponse

    if _on_cloud_db() and (current_user.get("role") or "").lower() != "admin":
        logger.warning("[DIAG] refused cloud log download for '%s' (role=%s)",
                       current_user.get("username"), current_user.get("role"))
        raise HTTPException(status_code=403, detail="The cloud server's logs cover every business; only the platform admin can download them.")

    candidates = []
    log_file = os.getenv("LOG_FILE") or os.path.join("logs", "bizassist.log")
    # the file + any rotations (bizassist.log.1, .2, …)
    candidates.extend(sorted(glob.glob(log_file + "*")))
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

    fname = f"bizassist-logs-{utc_now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    logger.info("[DIAGNOSTICS] Served %d log file(s) to user '%s'", len(existing), current_user.get("username"))
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
