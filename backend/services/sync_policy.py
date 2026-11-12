"""One fail-closed policy for automatic desktop cloud data and diagnostics."""
import json
import logging

logger = logging.getLogger(__name__)


def cloud_egress_allowed(business_id, *, diagnostics=False, session_factory=None, bind_engine=None):
    from database.db import SessionLocal, engine
    from database.models import User
    session_factory = session_factory or SessionLocal
    bind_engine = bind_engine or engine
    if bind_engine.dialect.name != "sqlite":
        return False
    try:
        with session_factory() as db:
            owner = db.get(User, business_id)
            if owner is not None and owner.parent_business_id is not None:
                owner = db.get(User, owner.parent_business_id)
            if owner is None or (owner.role or "").lower() in {"deleted", "retired"}:
                return False
            general = (json.loads(owner.settings or "{}") or {}).get("general") or {}
            return general.get("hosting_mode") == "hybrid" and (
                not diagnostics or general.get("diagnostic_upload_enabled") is True)
    except Exception as exc:
        logger.warning("Cannot verify cloud consent for business %s: %s", business_id, exc)
        return False
