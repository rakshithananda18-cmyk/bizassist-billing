import io
import os
import re
import tarfile
import logging
import httpx
from datetime import datetime
from database.db import SessionLocal
from database.models import User
from services.sync_worker import _get_cloud_token, CLOUD_URL
from services.immediate_sync import syncs_to_cloud

from typing import Optional
from services.dates import utc_now

logger = logging.getLogger("bizassist.log_uploader")

# See core/identity.py: an integer business id is meaningful only inside the
# database that issued it. This archive is uploaded to the shared cloud, so its
# name has to carry the BizID.
from core.identity import bizid_for as _bizid_for

# Archives hold ONE business's lines (filter_log_for). Archives named the old
# way (`logs_biz_*`) hold the whole log — every business on the computer and
# every sign-in typed before the BizID is known — so they are deleted unsent.
ARCHIVE_PREFIX = "bizlog_"
_LEGACY_PREFIX = "logs_biz_"

_NEW_LINE = re.compile(r"^\d\d:\d\d:\d\d ")   # logging_config.py: datefmt "%H:%M:%S"


def filter_log_for(bizid: str, lines) -> list:
    """The lines logged inside this business's requests and jobs (tagged
    `[BizId=<its BizID>]`), with any traceback lines that follow them.

    Untagged `[BizId=-]` lines are left out: they include start-up, other
    businesses' work and sign-in attempts, where a password typed into the
    username box would otherwise travel."""
    tag = f"[BizId={bizid}]"
    kept, keep = [], False
    for line in lines:
        if _NEW_LINE.match(line):
            keep = tag in line
        if keep:
            kept.append(line)
    return kept


def archive_logs(business_id: int) -> Optional[str]:
    """Compress this business's lines of bizassist.log to a tar.gz archive."""
    log_dir = "logs"
    log_file = os.path.join(log_dir, "bizassist.log")
    if not os.path.exists(log_file):
        logger.warning("[LOG_UPLOADER] bizassist.log does not exist, skipping archive")
        return None

    # Name the archive by BizID, not by the local integer id.
    #
    # This filename CROSSES A DATABASE BOUNDARY — the archive is uploaded to the
    # cloud, where it sits next to every other customer's. `logs_biz_7_*.tar.gz`
    # names a different business depending on which installation wrote it, so on
    # the cloud it identifies nothing. The BizID is the same string everywhere.
    # It is also what picks this business's lines, so without one there is
    # nothing safe to send.
    bizid = _bizid_for(business_id)
    if not bizid:
        logger.info("[LOG_UPLOADER] business %s has no BizID - nothing to upload", business_id)
        return None

    # Create backup directory
    backup_dir = os.path.join(log_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{ARCHIVE_PREFIX}{bizid}_{timestamp}.tar.gz"
    archive_path = os.path.join(backup_dir, archive_name)

    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            body = "".join(filter_log_for(bizid, f)).encode("utf-8")
        if not body:
            logger.info("[LOG_UPLOADER] No log lines for %s since the last rotation - nothing to upload", bizid)
            return None
        # admin_audit.jsonl (Admin Console actions across businesses) is no
        # longer included: it is not this business's diagnostics.
        with tarfile.open(archive_path, "w:gz") as tar:
            info = tarfile.TarInfo("bizassist.log")
            info.size = len(body)
            info.mtime = int(utc_now().timestamp())
            tar.addfile(info, io.BytesIO(body))
        logger.info("[LOG_UPLOADER] Archived %d bytes of %s's log lines to %s", len(body), bizid, archive_path)
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
    except Exception as e:
        logger.warning("[LOG_UPLOADER] Network error during log upload for business %s: %s", business_id, e)
        return False

    if resp.status_code != 200:
        logger.warning(
            "[LOG_UPLOADER] Upload failed for business %s: HTTP %s - %s",
            business_id, resp.status_code, resp.text
        )
        return False
    logger.info("[LOG_UPLOADER] Upload succeeded for business %s", business_id)
    # Success -> delete the local archive to free space. Only once the file is
    # closed: Windows refuses to delete an open file, and inside the `with` the
    # removal failed silently on every desktop, so each archive was sent again
    # the next night.
    try:
        os.remove(file_path)
    except Exception as e:
        logger.warning("[LOG_UPLOADER] Could not delete sent archive %s: %s", file_path, e)
    return True

def run_daily_log_upload():
    """Daily job to archive and upload logs for all active local businesses."""
    logger.info("[LOG_UPLOADER] Running daily scheduled log upload")
    
    # 1. Clean up old unsent archives in backups folder if they exceed retention
    log_dir = "logs"
    backup_dir = os.path.join(log_dir, "backups")
    if os.path.exists(backup_dir):
        try:
            # Delete backups older than 7 days to prevent disk bloat, and every
            # old-style whole-log archive (see ARCHIVE_PREFIX) without sending it.
            now = utc_now()
            for f in os.listdir(backup_dir):
                fp = os.path.join(backup_dir, f)
                if os.path.isfile(fp):
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(fp))
                    if f.startswith(_LEGACY_PREFIX):
                        os.remove(fp)
                        logger.info("[LOG_UPLOADER] Deleted unsent whole-log archive %s", f)
                    elif (now - mtime).days > 7:
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
            # "Local only" sends nothing, logs included - a cloud token alone
            # is not consent (see syncs_to_cloud).
            if not syncs_to_cloud(business_id):
                continue
            token = _get_cloud_token(business_id)
            if not token:
                continue

            # First, retry this business's unsent archives from earlier days.
            _bizid = _bizid_for(business_id)
            if _bizid and os.path.exists(backup_dir):
                for f in os.listdir(backup_dir):
                    fp = os.path.join(backup_dir, f)
                    if os.path.isfile(fp) and f.startswith(f"{ARCHIVE_PREFIX}{_bizid}_") and f.endswith(".tar.gz"):
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
