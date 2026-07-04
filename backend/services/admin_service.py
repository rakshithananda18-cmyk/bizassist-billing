"""
services/admin_service.py
==========================
Business logic for admin endpoints.
Routes call these functions; all DB/logic lives here.

Phase A hardening (Admin Console plan):
- ADMIN_API_ENABLED env gate, **default OFF** (fail closed). The desktop /
  PyInstaller build never sets it, so /admin/* effectively does not exist on
  customer machines (404, not 403 — don't advertise the surface). The HF Space
  sets ADMIN_API_ENABLED=1 (see root Dockerfile).
- audit_log(): every /admin/* mutation appends who/what/when to
  logs/admin_audit.jsonl (same pattern as telemetry — no DB migration).
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException
import os
import json
from database.models import (
    User, Invoice, InvoiceLineItem, Inventory, LegacyPayment, UploadedFile,
    DocumentEmbedding, ChatMessage, TokenUsage, RateLimitConfig,
    Customer, Vendor, Product, PurchaseOrder, PurchaseOrderLineItem,
    PurchaseInvoice, PurchaseInvoiceLineItem, AIFeedback, AIQueryOverride,
    BusinessFact, AlertConfig, SyncQueue, SyncLog
)
from core.models import (
    StockLedger, ProductBarcode, BusinessSettings, InvoicePayment,
    B2BConnection, B2BInviteCode, B2BOrder, B2BOrderLineItem,
    B2BLedger, Expense, Godown, StockTransfer, StockTransferLineItem,
    JournalEntry, JournalLine, PeriodLock
)
from services.auth import hash_password
from services.context_cache import invalidate, invalidate_user_cache, get_cache_stats
from services.rate_limiter import get_usage_summary

logger = logging.getLogger("bizassist.admin_service")

# Subscription plans (Phase B.5) — stored in users.settings JSON under the
# reserved "subscription" key. No migration; syncs with the settings machinery.
VALID_PLANS = ("free", "pro")


def _admin_api_enabled() -> bool:
    """Fail closed: admin API only exists when explicitly enabled (HF Space)."""
    return os.getenv("ADMIN_API_ENABLED", "0") == "1"


def audit_log(admin, action: str, details: dict = None, db: Session = None):
    """Append who/what/when for every admin mutation (JSONL + DB fallback).

    Identities are recorded by **BizID** (users.public_id) + username, not the
    numeric row id — numeric ids differ between the cloud and local databases,
    while the BizID is the stable cross-DB identity spine. `admin` may be a
    User row (preferred) or a bare int id (legacy callers)."""
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "admin_audit.jsonl")
        with open(log_file, "a") as f:
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "admin_id": getattr(admin, "id", admin),
                "admin_bizid": getattr(admin, "public_id", None),
                "admin_username": getattr(admin, "username", None),
                "action": action,
                "details": details or {}
            }
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Audit log JSONL failed: {e}")

    if db is not None:
        try:
            from database.models import ActionLog
            business_id = getattr(admin, "id", admin)
            target = None
            if details and "target" in details:
                target = str(details["target"])
            elif details and "target_username" in details:
                target = str(details["target_username"])
                
            log_row = ActionLog(
                business_id=business_id,
                action=action,
                target=target,
                detail=json.dumps(details) if details else None,
                status="success"
            )
            db.add(log_row)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Audit log DB write failed: {e}")


def require_admin(user_id: int, db: Session, action: str = None, details: dict = None) -> User:
    """Raises 404 if the admin API is disabled (fail closed — don't advertise
    the surface on customer installs), 403 if the caller is not an admin.
    Returns the admin User row. Pass `action` on mutations to audit-log them
    (targets referenced by numeric id are enriched with their BizID)."""
    if not _admin_api_enabled():
        logger.warning(f"[AUTH] Admin API disabled — blocked user_id={user_id}")
        raise HTTPException(status_code=404, detail="Not found")

    u = db.query(User).filter(User.id == user_id).first()
    if not u or u.role != "admin":
        logger.warning(f"[AUTH] Admin access denied for user_id={user_id} (role={getattr(u, 'role', None)})")
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    if action:
        det = dict(details or {})
        if det.get("target") is not None:
            t = db.query(User).filter(User.id == det["target"]).first()
            if t:
                det["target_bizid"] = t.public_id
                det["target_username"] = t.username
        audit_log(u, action, det, db=db)

    return u


def require_target_user(user_id: int, db: Session) -> User:
    """Raises 404 if target user does not exist."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


# ── Fleet monitor (Phase B.1) ────────────────────────────────────────────────

def _settings_dict(u: User) -> dict:
    try:
        return json.loads(u.settings) if u.settings else {}
    except Exception:
        return {}


def list_businesses(db: Session) -> list:
    """Per business: core stats + fleet fields (hosting mode, last sync,
    queue depth, online-in-last-24h) + subscription plan."""
    now = datetime.utcnow()
    businesses = db.query(User).filter(User.role == "enterprise").all()
    result = []
    for b in businesses:
        s = _settings_dict(b)
        sub = s.get("subscription") or {}
        last_sync = (
            db.query(func.max(SyncLog.synced_at))
            .filter(SyncLog.business_id == b.id).scalar()
        )
        queue_depth = (
            db.query(SyncQueue)
            .filter(SyncQueue.business_id == b.id, SyncQueue.synced_at.is_(None))
            .count()
        )
        online_24h = bool(last_sync and (now - last_sync) < timedelta(hours=24))
        result.append({
            "id":              b.id,
            "bizid":           b.public_id,   # stable identity across cloud/local DBs
            "username":        b.username,
            "business_name":   b.business_name,
            "invoice_count":   db.query(Invoice).filter(Invoice.business_id == b.id).count(),
            "total_revenue":   db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == b.id).scalar() or 0,
            "inventory_count": db.query(Inventory).filter(Inventory.business_id == b.id).count(),
            "upload_count":    db.query(UploadedFile).filter(UploadedFile.business_id == b.id).count(),
            # Fleet fields
            "hosting_mode":    s.get("general", {}).get("hosting_mode", "local"),
            "last_sync_at":    last_sync.isoformat() if last_sync else None,
            "sync_queue_depth": queue_depth,
            "online_last_24h": online_24h,
            # Subscription
            "plan":            sub.get("plan", "free"),
            "plan_status":     sub.get("status"),
            "plan_expires_at": sub.get("expires_at"),
        })
    return result


# ── Telemetry / logs viewer (Phase B.2 + B.3) ────────────────────────────────

def _telemetry_path() -> str:
    """Match routes/telemetry.py: logs/telemetry.jsonl relative to CWD."""
    return os.path.join("logs", "telemetry.jsonl")


def _business_telemetry_path(bizid: str) -> str:
    """Per-business mirror written by routes/telemetry.py."""
    import re
    token = re.sub(r"[^A-Za-z0-9_\-]", "", bizid or "")[:64]
    return os.path.join("logs", "businesses", token, "telemetry.jsonl") if token else ""


def _read_telemetry_db(device: str = None, event: str = None, level: str = None,
                       since: str = None, bizid: str = None, limit: int = 200,
                       db=None):
    """DB-first reader over telemetry_events (the durable store — the JSONL
    files are ephemeral on the HF Space). Returns None when the table is
    unavailable/empty so the caller can fall back to the files."""
    try:
        from core.models import TelemetryEvent
        q = db.query(TelemetryEvent)
        if bizid:
            q = q.filter(TelemetryEvent.bizid == bizid)
        if device:
            q = q.filter(TelemetryEvent.device_id.contains(device))
        if event:
            q = q.filter(TelemetryEvent.event == event)
        if level:
            q = q.filter(TelemetryEvent.level == level)
        if since:
            try:
                since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00")).replace(tzinfo=None)
                q = q.filter(TelemetryEvent.received_at >= since_dt)
            except Exception:
                pass
        total = q.count()
        if total == 0:
            return None
        rows = q.order_by(TelemetryEvent.received_at.desc(), TelemetryEvent.id.desc()).limit(limit).all()
        events = []
        for r in rows:
            rec = {
                "received_at": r.received_at.isoformat() if r.received_at else None,
                "source": r.source, "device_id": r.device_id,
                "level": r.level, "event": r.event,
            }
            if r.at:           rec["at"] = r.at
            if r.app_version:  rec["app_version"] = r.app_version
            if r.platform:     rec["platform"] = r.platform
            if r.bizid:        rec["bizid"] = r.bizid
            if r.relay_device: rec["relay_device"] = r.relay_device
            if r.relayed_at:   rec["relayed_at"] = r.relayed_at
            if r.payload:
                try:
                    rec["payload"] = json.loads(r.payload)
                except Exception:
                    rec["payload"] = r.payload
            events.append(rec)
        return {"events": events, "total_scanned": total, "path": "db:telemetry_events"}
    except Exception:
        return None


def read_telemetry(device: str = None, event: str = None, level: str = None,
                   since: str = None, bizid: str = None, limit: int = 200,
                   db=None) -> dict:
    """Newest-first, filterable reader. Prefers the persistent DB table
    (survives HF restarts); falls back to the JSONL files. With a bizid
    filter, reads that business's segregated file when it exists."""
    limit = max(1, min(int(limit or 200), 1000))

    if db is not None:
        db_out = _read_telemetry_db(device=device, event=event, level=level,
                                    since=since, bizid=bizid, limit=limit, db=db)
        if db_out is not None:
            return db_out

    path = _telemetry_path()
    filtering_bizid = None
    if bizid:
        bpath = _business_telemetry_path(bizid)
        if bpath and os.path.exists(bpath):
            path = bpath                      # segregated file — no bizid filter needed
        else:
            filtering_bizid = bizid           # fall back to global + filter
    if not os.path.exists(path):
        return {"events": [], "total_scanned": 0, "path": path}

    rows = []
    scanned = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read telemetry log: {e}")

    for line in reversed(lines):          # newest-first
        line = line.strip()
        if not line:
            continue
        scanned += 1
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if device and device not in (rec.get("device_id") or ""):
            continue
        if event and event != rec.get("event"):
            continue
        if level and level != rec.get("level"):
            continue
        if since and (rec.get("received_at") or "") < since:
            continue
        if filtering_bizid and filtering_bizid != rec.get("bizid"):
            continue
        rows.append(rec)
        if len(rows) >= limit:
            break
    return {"events": rows, "total_scanned": scanned, "path": path}


def telemetry_devices(db=None) -> list:
    """Aggregate per device: app version, platform, last seen — and every
    BizID the device has reported under, so shared devices (multiple
    businesses on one install) are visible at a glance. DB-first, JSONL
    fallback."""
    if db is not None:
        try:
            from core.models import TelemetryEvent
            from sqlalchemy import func
            if (db.query(func.count(TelemetryEvent.id)).scalar() or 0) > 0:
                devices = {}
                for r in db.query(TelemetryEvent).order_by(TelemetryEvent.received_at.asc()).all():
                    did = r.device_id
                    if not did:
                        continue
                    cur = devices.setdefault(did, {"device_id": did, "_bizids": set(), "last_seen": ""})
                    if r.bizid:
                        cur["_bizids"].add(r.bizid)
                    seen = r.received_at.isoformat() if r.received_at else ""
                    if seen >= (cur.get("last_seen") or ""):
                        cur.update({
                            "app_version": r.app_version, "platform": r.platform,
                            "source": r.source, "last_seen": seen,
                            "last_event": r.event, "last_level": r.level,
                            "last_bizid": r.bizid or cur.get("last_bizid"),
                        })
                out = []
                for d in devices.values():
                    bizids = sorted(d.pop("_bizids"))
                    d["bizids"] = bizids
                    d["bizid_count"] = len(bizids)
                    d["shared"] = len(bizids) > 1
                    out.append(d)
                return sorted(out, key=lambda d: d.get("last_seen") or "", reverse=True)
        except Exception:
            pass  # fall back to file

    path = _telemetry_path()
    if not os.path.exists(path):
        return []
    devices = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                did = rec.get("device_id")
                if not did:
                    continue
                cur = devices.setdefault(did, {"device_id": did, "_bizids": set(), "last_seen": ""})
                if rec.get("bizid"):
                    cur["_bizids"].add(rec["bizid"])
                if (rec.get("received_at") or "") > (cur.get("last_seen") or ""):
                    cur.update({
                        "app_version": rec.get("app_version"),
                        "platform":    rec.get("platform"),
                        "source":      rec.get("source"),
                        "last_seen":   rec.get("received_at"),
                        "last_event":  rec.get("event"),
                        "last_level":  rec.get("level"),
                        "last_bizid":  rec.get("bizid") or cur.get("last_bizid"),
                    })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read telemetry log: {e}")

    out = []
    for d in devices.values():
        bizids = sorted(d.pop("_bizids"))
        d["bizids"] = bizids
        d["bizid_count"] = len(bizids)
        d["shared"] = len(bizids) > 1        # one install used by multiple businesses
        out.append(d)
    return sorted(out, key=lambda d: d.get("last_seen") or "", reverse=True)


def server_log_tail(lines: int = 200, q: str = None) -> dict:
    """Tail of the backend server log (bizassist.log) for the Debug tab.
    Optional `q` substring filter (e.g. a BizID or username) gives a segregated
    view of one business's lines without shipping the whole log."""
    lines = max(1, min(int(lines or 200), 2000))
    candidates = ("bizassist.log", os.path.join("logs", "bizassist.log"))
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = [l.rstrip("\n") for l in f.readlines()]
                if q:
                    all_lines = [l for l in all_lines if q in l]
                return {"path": path, "filter": q, "lines": all_lines[-lines:]}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to read server log: {e}")
    return {"path": None, "filter": q, "lines": []}


def telemetry_businesses(db=None) -> list:
    """Businesses that have telemetry. DB-first (durable), folder fallback."""
    if db is not None:
        try:
            from core.models import TelemetryEvent
            from sqlalchemy import func
            rows = (db.query(
                        TelemetryEvent.bizid,
                        func.count(TelemetryEvent.id),
                        func.max(TelemetryEvent.received_at),
                    )
                    .filter(TelemetryEvent.bizid.isnot(None))
                    .group_by(TelemetryEvent.bizid)
                    .all())
            if rows:
                return [{
                    "bizid": b, "events": int(n),
                    "last_write": mx.isoformat() if mx else None,
                } for b, n, mx in sorted(rows, key=lambda r: r[0] or "")]
        except Exception:
            pass  # fall back to folders

    root = os.path.join("logs", "businesses")
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        f = os.path.join(root, name, "telemetry.jsonl")
        if os.path.isfile(f):
            try:
                size = os.path.getsize(f)
                mtime = datetime.utcfromtimestamp(os.path.getmtime(f)).isoformat()
            except OSError:
                size, mtime = 0, None
            out.append({"bizid": name, "size_bytes": size, "last_write": mtime})
    return out


def read_audit_log(limit: int = 200, db: Session = None) -> list:
    """Newest-first reader over DB action_logs table, falling back to logs/admin_audit.jsonl."""
    limit = max(1, min(int(limit or 200), 1000))
    
    if db is not None:
        try:
            from database.models import ActionLog
            logs = db.query(ActionLog).order_by(ActionLog.id.desc()).limit(limit).all()
            if logs:
                return [
                    {
                        "timestamp": log.created_at.isoformat() if log.created_at else None,
                        "admin_id": log.business_id,
                        "admin_bizid": None,
                        "admin_username": "admin",
                        "action": log.action,
                        "details": json.loads(log.detail) if log.detail else {}
                    }
                    for log in logs
                ]
        except Exception as e:
            logger.error(f"Failed to read audit log from DB: {e}")

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "admin_audit.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for line in reversed(lines):
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
        if len(rows) >= limit:
            break
    return rows


# ── Subscriptions (Phase B.5 — schema-free, lives in users.settings JSON) ────

def get_subscription(business_id: int, db: Session) -> dict:
    target = require_target_user(business_id, db)
    s = _settings_dict(target)
    sub = s.get("subscription") or {}
    return {
        "business_id": business_id,
        "username":    target.username,
        "business_name": target.business_name,
        "plan":        sub.get("plan", "free"),
        "status":      sub.get("status", "none"),
        "expires_at":  sub.get("expires_at"),
        "granted_by":  sub.get("granted_by"),
        "granted_at":  sub.get("granted_at"),
        "note":        sub.get("note"),
    }


def set_subscription(business_id: int, body, admin: User, db: Session) -> dict:
    """Grant / extend / revoke a plan. Stored under the reserved `subscription`
    key in users.settings — routes/auth.py strips this key from client PUT
    /settings patches and preserves it on every save, so only admins can
    change it."""
    target = require_target_user(business_id, db)
    plan = (body.plan or "free").lower()
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Valid: {', '.join(VALID_PLANS)}")

    s = _settings_dict(target)
    if plan == "free":
        # Revoke: drop the key entirely — free is the absence of a grant.
        s.pop("subscription", None)
    else:
        s["subscription"] = {
            "plan":       plan,
            "status":     body.status or "active",
            "expires_at": body.expires_at,
            "granted_by": admin.username,
            "granted_at": datetime.utcnow().isoformat(),
            "note":       body.note,
        }
    target.settings = json.dumps(s)
    db.commit()
    invalidate_user_cache(business_id)
    return get_subscription(business_id, db)


def effective_plan(user: User) -> str:
    """The user's current plan, accounting for expiry. Staff inherit the owner's
    plan via the caller passing the owner row."""
    sub = _settings_dict(user).get("subscription") or {}
    plan = (sub.get("plan") or "free").lower()
    if plan == "free":
        return "free"
    exp = sub.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(str(exp).replace("Z", "+00:00")).replace(tzinfo=None) < datetime.utcnow():
                return "free"
        except Exception:
            pass
    return plan


# ── Existing admin ops ───────────────────────────────────────────────────────

def wipe_all_data(db: Session) -> dict:
    db.query(Invoice).delete()
    db.query(Inventory).delete()
    db.query(LegacyPayment).delete()
    db.query(UploadedFile).delete()
    db.query(DocumentEmbedding).delete()
    db.query(ChatMessage).delete()
    db.commit()
    invalidate()
    return {"status": "success", "message": "All business data deleted and cache flushed."}


def wipe_user_data(user_id: int, db: Session) -> dict:
    target = require_target_user(user_id, db)

    # 1. Delete child lines that do NOT have business_id directly
    db.query(InvoiceLineItem).filter(
        InvoiceLineItem.invoice_id.in_(
            db.query(Invoice.id).filter(Invoice.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    db.query(PurchaseInvoiceLineItem).filter(
        PurchaseInvoiceLineItem.purchase_invoice_id.in_(
            db.query(PurchaseInvoice.id).filter(PurchaseInvoice.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    db.query(PurchaseOrderLineItem).filter(
        PurchaseOrderLineItem.purchase_order_id.in_(
            db.query(PurchaseOrder.id).filter(PurchaseOrder.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    db.query(B2BOrderLineItem).filter(
        B2BOrderLineItem.order_id.in_(
            db.query(B2BOrder.id).filter(
                (B2BOrder.seller_business_id == user_id) | (B2BOrder.buyer_business_id == user_id)
            )
        )
    ).delete(synchronize_session=False)

    db.query(JournalLine).filter(
        JournalLine.entry_id.in_(
            db.query(JournalEntry.id).filter(JournalEntry.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    db.query(StockTransferLineItem).filter(
        StockTransferLineItem.transfer_id.in_(
            db.query(StockTransfer.id).filter(StockTransfer.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    db.query(ProductBarcode).filter(
        ProductBarcode.product_id.in_(
            db.query(Product.id).filter(Product.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    # 2. Delete parent records in correct dependency order
    db.query(InvoicePayment).filter(InvoicePayment.business_id == user_id).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.business_id == user_id).delete(synchronize_session=False)
    db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == user_id).delete(synchronize_session=False)
    db.query(PurchaseOrder).filter(PurchaseOrder.business_id == user_id).delete(synchronize_session=False)
    db.query(B2BOrder).filter(
        (B2BOrder.seller_business_id == user_id) | (B2BOrder.buyer_business_id == user_id)
    ).delete(synchronize_session=False)
    db.query(JournalEntry).filter(JournalEntry.business_id == user_id).delete(synchronize_session=False)
    db.query(StockTransfer).filter(StockTransfer.business_id == user_id).delete(synchronize_session=False)
    db.query(StockLedger).filter(StockLedger.business_id == user_id).delete(synchronize_session=False)
    db.query(Inventory).filter(Inventory.business_id == user_id).delete(synchronize_session=False)
    db.query(Product).filter(Product.business_id == user_id).delete(synchronize_session=False)
    db.query(Customer).filter(Customer.business_id == user_id).delete(synchronize_session=False)
    db.query(Vendor).filter(Vendor.business_id == user_id).delete(synchronize_session=False)

    # B2B network relationships (use correct key names)
    db.query(B2BConnection).filter(
        (B2BConnection.seller_business_id == user_id) | (B2BConnection.buyer_business_id == user_id)
    ).delete(synchronize_session=False)
    db.query(B2BInviteCode).filter(B2BInviteCode.seller_business_id == user_id).delete(synchronize_session=False)
    db.query(B2BLedger).filter(
        (B2BLedger.seller_business_id == user_id) | (B2BLedger.buyer_business_id == user_id)
    ).delete(synchronize_session=False)

    # 3. Delete all other business-scoped data
    for model in (
        LegacyPayment, UploadedFile, DocumentEmbedding, ChatMessage, TokenUsage,
        RateLimitConfig, AlertConfig, AIFeedback, AIQueryOverride, BusinessFact,
        BusinessSettings, Expense, Godown, PeriodLock
    ):
        db.query(model).filter(model.business_id == user_id).delete(synchronize_session=False)

    # 4. Purge embeddings from Chroma vector store
    try:
        from services.embeddings import delete_user_chroma_memories
        delete_user_chroma_memories(user_id)
    except Exception as e:
        logger.error("Chroma purge failed for user %s: %s", user_id, e, exc_info=True)

    # 5. Delete the target user and invalidate cache
    db.delete(target)
    db.commit()
    invalidate_user_cache(user_id)
    return {"status": "success", "message": "All data for " + target.username + " deleted."}


def token_usage(db: Session) -> list:
    rows = db.query(
        TokenUsage.business_id, TokenUsage.model_tier, TokenUsage.model,
        func.sum(TokenUsage.input_tokens).label("total_input"),
        func.sum(TokenUsage.output_tokens).label("total_output"),
        func.sum(TokenUsage.total_tokens).label("total_tokens"),
        func.sum(TokenUsage.cached_tokens).label("total_cached"),
        func.count(TokenUsage.id).label("call_count"),
    ).group_by(TokenUsage.business_id, TokenUsage.model_tier, TokenUsage.model).all()
    result = []
    for r in rows:
        u = db.query(User).filter(User.id == r.business_id).first()
        result.append({
            "business_id":   r.business_id,
            "business_name": u.business_name if u else "Unknown",
            "model_tier":    r.model_tier,
            "model":         r.model,
            "call_count":    r.call_count,
            "input_tokens":  r.total_input,
            "output_tokens": r.total_output,
            "total_tokens":  r.total_tokens,
            "cached_tokens": r.total_cached,
        })
    return result


def reset_chroma_docs() -> dict:
    from services.embeddings import get_chroma_client
    client = get_chroma_client()
    deleted = []
    for name in ("document_embeddings", "document_embeddings_v2"):
        try:
            client.delete_collection(name=name)
            deleted.append(name)
        except Exception:
            pass
    client.get_or_create_collection(name="document_embeddings_v2")
    return {"status": "success", "deleted_collections": deleted,
            "message": "Chroma document collections reset. Re-upload your files to rebuild the index."}


def business_details(user_id: int, db: Session) -> dict:
    target = require_target_user(user_id, db)
    uploads  = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).all()
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    inventory = db.query(Inventory).filter(Inventory.business_id == user_id).all()
    payments = db.query(LegacyPayment).filter(LegacyPayment.business_id == user_id).all()
    msgs = db.query(ChatMessage).filter(ChatMessage.business_id == user_id).order_by(ChatMessage.timestamp.desc()).all()
    return {
        "id": target.id, "username": target.username, "business_name": target.business_name,
        "uploads":  [{"id": u.id, "filename": u.filename, "file_type": u.file_type, "rows_count": u.rows_count, "upload_time": u.upload_time} for u in uploads],
        "invoices": [{"id": i.id, "invoice_id": i.invoice_id, "customer": i.customer, "product": i.product, "amount": i.amount, "status": i.status, "invoice_date": i.invoice_date, "due_date": i.due_date} for i in invoices],
        "inventory":[{"id": it.id, "product_name": it.product_name, "stock": it.stock, "expiry_date": it.expiry_date, "supplier": it.supplier} for it in inventory],
        "payments": [{"id": p.id, "customer": p.customer, "amount": p.amount, "due_date": p.due_date, "paid": p.paid} for p in payments],
        "chat_history": [{"id": m.id, "role": m.role, "content": m.content, "session_id": m.session_id, "session_title": m.session_title, "timestamp": m.timestamp.isoformat() if m.timestamp else None} for m in msgs],
    }


def get_rate_limit_config(user_id: int, db: Session) -> dict:
    cfg = db.query(RateLimitConfig).filter(RateLimitConfig.business_id == user_id).first()
    if not cfg:
        return {"configured": False, "defaults": {"requests_per_minute": 10, "requests_per_day": 500, "max_tokens_per_day": 50000, "complex_per_day": 20, "active": True}}
    return {"configured": True, "requests_per_minute": cfg.requests_per_minute, "requests_per_day": cfg.requests_per_day, "max_tokens_per_day": cfg.max_tokens_per_day, "complex_per_day": cfg.complex_per_day, "active": cfg.active}


def set_rate_limit_config(user_id: int, body, db: Session) -> dict:
    require_target_user(user_id, db)
    cfg = db.query(RateLimitConfig).filter(RateLimitConfig.business_id == user_id).first()
    if cfg:
        cfg.requests_per_minute = body.requests_per_minute
        cfg.requests_per_day    = body.requests_per_day
        cfg.max_tokens_per_day  = body.max_tokens_per_day
        cfg.complex_per_day     = body.complex_per_day
        cfg.active              = body.active
        cfg.updated_at          = datetime.utcnow()
    else:
        db.add(RateLimitConfig(business_id=user_id, requests_per_minute=body.requests_per_minute, requests_per_day=body.requests_per_day, max_tokens_per_day=body.max_tokens_per_day, complex_per_day=body.complex_per_day, active=body.active))
    db.commit()
    target = db.query(User).filter(User.id == user_id).first()
    return {"success": True, "message": "Rate limits saved for " + (target.business_name if target else str(user_id)) + "."}


def all_usage_stats(db: Session) -> list:
    businesses = db.query(User).filter(User.role == "enterprise").all()
    result = []
    for b in businesses:
        s = get_usage_summary(b.id)
        s["business_name"] = b.business_name
        s["username"]      = b.username
        result.append(s)
    return result


def create_merchant(username: str, password: str, business_name: str, db: Session) -> dict:
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    u = User(username=username, password=hash_password(password), business_name=business_name, role="enterprise")
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"status": "success", "message": "Merchant user " + username + " created successfully.", "user_id": u.id}


def update_merchant(user_id: int, req, db: Session) -> dict:
    target = require_target_user(user_id, db)
    if req.username and req.username != target.username:
        if db.query(User).filter(User.username == req.username).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        target.username = req.username
    if req.business_name:
        target.business_name = req.business_name
    if req.password:
        target.password = hash_password(req.password)
    db.commit()
    invalidate_user_cache(user_id)
    return {"status": "success", "message": "Merchant user " + target.username + " updated successfully."}
