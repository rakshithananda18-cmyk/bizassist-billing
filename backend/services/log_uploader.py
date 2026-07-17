import os
import tarfile
import logging
import httpx
from datetime import datetime
from database.db import SessionLocal
from database.models import User
from services.sync_worker import _get_cloud_token, CLOUD_URL

from typing import Optional
from services.dates import utc_now

logger = logging.getLogger("bizassist.log_uploader")

def archive_logs(business_id: int) -> Optional[str]:
    """Compress bizassist.log to a tar.gz archive."""
    log_dir = "logs"
    log_file = os.path.join(log_dir, "bizassist.log")
    if not os.path.exists(log_file):
        logger.warning("[LOG_UPLOADER] bizassist.log does not exist, skipping archive")
        return None

    # Create backup directory
    backup_dir = os.path.join(log_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"logs_biz_{business_id}_{timestamp}.tar.gz"
    archive_path = os.path.join(backup_dir, archive_name)

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            # Add bizassist.log
            tar.add(log_file, arcname="bizassist.log")
            # Optionally add admin_audit.jsonl if exists
            audit_file = os.path.join(log_dir, "admin_audit.jsonl")
            if os.path.exists(audit_file):
                tar.add(audit_file, arcname="admin_audit.jsonl")
        logger.info("[LOG_UPLOADER] Archived logs to %s", archive_path)
        return archive_path
    except Exception as e:
        logger.error("[LOG_UPLOADER] Failed to archive logs: %s", e, exc_info=True)
        return None

def upload_logs_to_cloud(business_id: int, file_path: str, message: str = "Scheduled log upload") -> bool:
    """Upload archived logs to the cloud backend."""
    token = _get_cloud_token(business_id)
    if not token:
        logger.info("[LOG_UPLOADER] No cloud token found for business_id=%s, skipping upload", business_id)
        return False

    url = f"{CLOUD_URL}/api/feedback/submit"
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/gzip")}
            data = {"message": message}
            headers = {"Authorization": f"Bearer {token}"}
            
            logger.info("[LOG_UPLOADER] Uploading logs to %s for business %s", url, business_id)
            resp = httpx.post(url, data=data, files=files, headers=headers, timeout=15.0)
            
            if resp.status_code == 200:
                logger.info("[LOG_UPLOADER] Upload succeeded for business %s", business_id)
                # Success -> we can safely delete the local archive file to free space
                try:
                    os.remove(file_path)
                except Exception:
                    pass
                return True
            else:
                logger.warning(
                    "[LOG_UPLOADER] Upload failed for business %s: HTTP %s - %s",
                    business_id, resp.status_code, resp.text
                )
                return False
    except Exception as e:
        logger.warning("[LOG_UPLOADER] Network error during log upload for business %s: %s", business_id, e)
        return False

def run_daily_log_upload():
    """Daily job to archive and upload logs for all active local businesses."""
    logger.info("[LOG_UPLOADER] Running daily scheduled log upload")
    
    # 1. Clean up old unsent archives in backups folder if they exceed retention
    log_dir = "logs"
    backup_dir = os.path.join(log_dir, "backups")
    if os.path.exists(backup_dir):
        try:
            # Delete backups older than 7 days to prevent disk bloat
            now = utc_now()
            for f in os.listdir(backup_dir):
                fp = os.path.join(backup_dir, f)
                if os.path.isfile(fp):
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(fp))
                    if (now - mtime).days > 7:
                        os.remove(fp)
                        logger.info("[LOG_UPLOADER] Cleaned up old backup log %s", f)
        except Exception as e:
            logger.warning("[LOG_UPLOADER] Failed to clean backups directory: %s", e)

    # 2. Process active users/businesses
    db = SessionLocal()
    try:
        # Owners only (staff share the owner's business). There is no `User.active`
        # column — the old filter raised AttributeError and crashed this daily job.
        users = db.query(User).filter(User.parent_business_id.is_(None)).all()
        for user in users:
            business_id = user.id
            token = _get_cloud_token(business_id)
            if not token:
                continue

            # First, check if there are any old unsent files in backups directory, try uploading them first!
            if os.path.exists(backup_dir):
                for f in os.listdir(backup_dir):
                    fp = os.path.join(backup_dir, f)
                    if os.path.isfile(fp) and f.startswith(f"logs_biz_{business_id}_") and f.endswith(".tar.gz"):
                        logger.info("[LOG_UPLOADER] Retrying upload of old archive %s", f)
                        if upload_logs_to_cloud(business_id, fp, "Retry upload of old unsent diagnostic log"):
                            # Delete on success (handled inside upload_logs_to_cloud)
                            pass

            # Create new log archive
            archive_path = archive_logs(business_id)
            if archive_path:
                upload_logs_to_cloud(business_id, archive_path, "Scheduled daily diagnostic log upload")
    except Exception as e:
        logger.error("[LOG_UPLOADER] Error in daily log upload task: %s", e, exc_info=True)
    finally:
        db.close()
