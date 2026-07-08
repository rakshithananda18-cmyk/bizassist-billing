"""
services/immediate_sync.py
===========================
Lightweight helpers for triggering an out-of-band sync push immediately after
a high-priority write — without waiting for the 25-30 second background cycle.

Usage (in any route):
    from services.immediate_sync import push_profile_to_cloud, trigger_data_sync

    # For users-table fields (not in MODEL_MAP):
    push_profile_to_cloud(business_id, {"business_name": "...", "gstin": "..."})

    # For any entity already in MODEL_MAP (settings, products, customers, etc.):
    trigger_data_sync(business_id, db)

Both are fire-and-forget (background thread). They never block the HTTP response
and silently swallow errors (the regular sync cycle is the safety net).
"""
from __future__ import annotations
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("bizassist.immediate_sync")

# Only run immediate pushes on local (SQLite) backends.
_IS_LOCAL = os.environ.get("DATABASE_URL", "sqlite").startswith("sqlite")


def push_profile_to_cloud(business_id: int, fields: dict) -> None:
    """
    Fire-and-forget POST /api/sync/profile-push to the cloud with the given
    profile field dict.  Only non-None values are sent.
    """
    if not _IS_LOCAL:
        return

    payload = {k: v for k, v in fields.items() if v is not None}
    if not payload:
        return

    def _run():
        try:
            import httpx
            from services.sync_worker import _get_cloud_token, CLOUD_URL
            token = _get_cloud_token(business_id)
            if not token:
                logger.warning("[PROFILE-SYNC] No cloud token for biz %s — skipped", business_id)
                return
            resp = httpx.post(
                f"{CLOUD_URL}/api/sync/profile-push",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=8.0,
            )
            if resp.status_code == 200:
                logger.info("[PROFILE-SYNC] Pushed %s to cloud for biz %s",
                            list(payload.keys()), business_id)
            else:
                logger.warning("[PROFILE-SYNC] Cloud returned %s: %s",
                               resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("[PROFILE-SYNC] Push failed (non-critical): %s", e)

    threading.Thread(target=_run, daemon=True).start()


def trigger_data_sync(business_id: int, db) -> None:
    """
    Force an immediate sync cycle for this business — flushes the SyncQueue
    without waiting for the 25-30s background interval.

    Used after high-priority writes: settings save, product create/update,
    customer create, godown create, etc.  The entity must already be in
    MODEL_MAP (i.e. written to SyncQueue by the event hook) for this to work.
    """
    if not _IS_LOCAL:
        return

    def _run():
        try:
            from database.db import SessionLocal
            from database.models import User
            from services.sync_worker import sync_business

            with SessionLocal() as session:
                owner = session.query(User).filter(
                    User.id == business_id,
                    User.parent_business_id.is_(None),
                ).first()
                if owner:
                    sync_business(session, owner, force=True)
                    logger.info("[IMMEDIATE-SYNC] Force sync complete for biz %s", business_id)
        except Exception as e:
            logger.warning("[IMMEDIATE-SYNC] Force sync failed (non-critical): %s", e)

    threading.Thread(target=_run, daemon=True).start()
