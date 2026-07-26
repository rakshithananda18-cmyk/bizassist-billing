"""
core/api/connections.py
========================
FastAPI routes for BizIDs and B2B Connections.
"""
import json
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import User
from core.models import B2BConnection, BusinessSettings
from services.auth import get_active_user, restrict_cashier, restrict_cashier_or_ticket, get_active_user_or_ticket
from services.realtime import realtime_manager
from core.connection import service as conn_service
from core.order import service as order_service

router = APIRouter(tags=["connections"])
logger = logging.getLogger("bizassist.core.api.connections")

# ── Schemas ──────────────────────────────────────────────────────────────────


class PolicyRequest(BaseModel):
    price_tier: str = Field(..., description="standard | wholesale | distributor")
    discount_pct: float = Field(0.0, ge=0.0, le=100.0)
    credit_limit: float = Field(0.0, ge=0.0)
    stock_visibility: str = Field(..., description="exact | band | hidden")
    catalog_category: Optional[str] = None

class RedeemRequest(BaseModel):
    code: str

class ConnectRequest(BaseModel):
    bizid: str
    connect_as: str = Field(..., description="buyer | seller")
    message: Optional[str] = Field(None, max_length=500,
                                   description="Optional note shown to the counterparty")

# ── Helper Serializers ────────────────────────────────────────────────────────

def _business_map(db: Session, conns) -> dict:
    """Resolve every business referenced by ``conns`` in ONE query.

    Replaces the previous two-queries-per-row pattern in ``_conn_out`` (review
    finding F-5: N+1). With 200 connections that was 400 round-trips per page
    load; it is now exactly one.
    """
    ids = set()
    for c in conns:
        ids.add(c.seller_business_id)
        ids.add(c.buyer_business_id)
    ids.discard(None)
    if not ids:
        return {}
    rows = db.query(User.id, User.business_name, User.public_id).filter(User.id.in_(ids)).all()
    return {r.id: r for r in rows}


def _conn_out(conn: B2BConnection, db: Session, *, viewer_id: int = None,
              businesses: dict = None) -> dict:
    """Serialize a connection.

    ``businesses`` is the pre-resolved map from :func:`_business_map`; when it is
    omitted (single-row endpoints) we fall back to resolving just this row.
    ``viewer_id`` adds the caller-relative fields the UI needs to decide whether
    to render Approve/Reject buttons or a "waiting on them" chip.
    """
    if businesses is None:
        businesses = _business_map(db, [conn])

    seller = businesses.get(conn.seller_business_id)
    buyer = businesses.get(conn.buyer_business_id)
    requested_by = businesses.get(getattr(conn, "requested_by_business_id", None))

    out = {
        "id": conn.id,
        "seller_business_id": conn.seller_business_id,
        "buyer_business_id": conn.buyer_business_id,
        "seller_name": seller.business_name if seller else "Unknown Seller",
        "seller_bizid": seller.public_id if seller else "",
        "buyer_name": buyer.business_name if buyer else "Unknown Buyer",
        "buyer_bizid": buyer.public_id if buyer else "",
        "price_tier": conn.price_tier,
        "discount_pct": conn.discount_pct,
        "credit_limit": conn.credit_limit,
        "outstanding_balance": conn.outstanding_balance,
        "stock_visibility": conn.stock_visibility,
        "catalog_category": conn.catalog_category,
        "status": conn.status,
        "requested_by_business_id": getattr(conn, "requested_by_business_id", None),
        "requested_by_name": requested_by.business_name if requested_by else None,
        "request_message": getattr(conn, "request_message", None),
        "responded_at": conn.responded_at.isoformat() if getattr(conn, "responded_at", None) else None,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }

    if viewer_id is not None:
        # Direction, from the caller's point of view. The frontend must never
        # infer this from buyer/seller roles — either side can initiate.
        out["my_role"] = ("seller" if viewer_id == conn.seller_business_id
                          else "buyer" if viewer_id == conn.buyer_business_id else None)
        out["is_incoming_request"] = conn_service.is_awaiting(conn, viewer_id)
        out["is_outgoing_request"] = (
            conn.status == conn_service.STATUS_PENDING
            and conn_service.is_requester(conn, viewer_id)
        )
        # Pending, but we don't know who asked (legacy / imported / mirrored
        # row). Under R3 nobody may approve it, so it is neither incoming nor
        # outgoing — without this flag it would be a row that exists in the
        # database and appears in NO bucket in the UI. The client renders it as
        # "needs re-sending"; re-requesting claims it and restores a normal
        # pending request addressed to the counterparty.
        out["requester_unknown"] = (
            conn.status == conn_service.STATUS_PENDING
            and not conn_service.has_known_requester(conn)
        )
        cp_id = conn_service.counterparty_id(conn, viewer_id)
        cp = businesses.get(cp_id)
        out["counterparty_id"] = cp_id
        out["counterparty_name"] = cp.business_name if cp else None
        out["counterparty_bizid"] = cp.public_id if cp else None

    return out

def _is_reachable(business_id: int, db: Session) -> bool:
    """True when this business talks to the cloud at all (hybrid or cloud mode).

    A pure-local install never polls the cloud, so nothing addressed to it there
    is ever delivered. Mirrors core/api/biz_id.py::lookup_bizid so the pre-send
    check and the post-send warning can never disagree."""
    try:
        row = db.query(User.settings).filter(User.id == business_id).first()
        blob = json.loads(row.settings) if (row and row.settings) else {}
        return (blob.get("general") or {}).get("hosting_mode") in ("hybrid", "cloud")
    except Exception:
        # Unknown -> assume reachable. A false warning is worse than none.
        return True


def _notify_counterparty(conn: B2BConnection, actor_id: int, db: Session,
                         event: str = "connection.requested") -> None:
    """Push a realtime nudge to the OTHER business on the link.

    A connection request is only a growth loop if the counterparty finds out
    without having to go looking. These handlers are sync, so we use the
    thread-safe broadcast rather than awaiting. Never raises — a failed
    notification must not fail the state transition that already committed.
    """
    try:
        target_id = conn_service.counterparty_id(conn, actor_id)
        if not target_id:
            return
        actor = db.query(User.business_name, User.public_id).filter(User.id == actor_id).first()
        realtime_manager.broadcast_threadsafe(target_id, {
            "type": event,
            "connection_id": conn.id,
            "status": conn.status,
            "from_name": actor.business_name if actor else None,
            "from_bizid": actor.public_id if actor else None,
        })
    except Exception:
        logger.warning("Realtime notify failed for connection %s", conn.id, exc_info=True)


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/connections/code")
def generate_join_code(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Generate a single-use expiring connection code (Seller flow)."""
    try:
        code_obj = conn_service.create_connection_code(db, seller_business_id=current_user["id"])
        return {
            "code": code_obj.code,
            "expires_at": code_obj.expires_at.isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to generate connection code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not generate connection code")

@router.post("/connections/redeem")
def redeem_join_code(req: RedeemRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Redeem a connection code to link to a seller (Buyer flow)."""
    try:
        conn = conn_service.redeem_connection_code(db, buyer_business_id=current_user["id"], code=req.code)
        return _conn_out(conn, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to redeem connection code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not redeem connection code")

@router.post("/connections/accept")
@router.post("/connections/connect")
def connect_via_bizid(req: ConnectRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Send a connection REQUEST to a business identified by its BizID.

    This does NOT create a live link. BizID is public, so a request lands in the
    other business's inbox as ``pending`` and only becomes usable once they
    approve it (see ``POST /connections/{id}/approve``). Until then no catalog,
    pricing or stock data is exposed.
    """
    try:
        conn = conn_service.request_connection(
            db,
            initiator_id=current_user["id"],
            target_bizid=req.bizid.strip().upper(),
            connect_as=req.connect_as,
            message=req.message,
        )
        _notify_counterparty(conn, current_user["id"], db)
        out = _conn_out(conn, db, viewer_id=current_user["id"])

        # A request is a row in the CLOUD database that the counterparty's app
        # must read. A local-only business never reaches the cloud, so it will
        # never see this. We don't BLOCK the request — they may switch modes
        # tomorrow, and the row is then already waiting — but we say so plainly
        # instead of leaving the sender waiting on a reply that can't come.
        if conn.status == conn_service.STATUS_PENDING:
            target_id = conn_service.counterparty_id(conn, current_user["id"])
            if target_id and not _is_reachable(target_id, db):
                out["warning"] = (
                    "This business is running in offline (local-only) mode, so it "
                    "cannot receive your request yet. It will appear for them as "
                    "soon as they enable cloud sync."
                )
        return out
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to request connection via BizID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not send connection request")


@router.post("/connections/{id}/approve")
def approve_connection(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Approve a pending request addressed to you. The requester cannot call this."""
    try:
        conn = conn_service.approve_connection(db, business_id=current_user["id"], connection_id=id)
        _notify_counterparty(conn, current_user["id"], db, event="connection.approved")
        return _conn_out(conn, db, viewer_id=current_user["id"])
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to approve connection {id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not approve connection")


@router.post("/connections/{id}/reject")
def reject_connection(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Decline a pending request addressed to you."""
    try:
        conn = conn_service.reject_connection(db, business_id=current_user["id"], connection_id=id)
        _notify_counterparty(conn, current_user["id"], db, event="connection.rejected")
        return _conn_out(conn, db, viewer_id=current_user["id"])
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to reject connection {id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not reject connection")


@router.post("/connections/{id}/cancel")
def cancel_connection_request(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Withdraw a pending request YOU raised."""
    try:
        conn_service.cancel_request(db, business_id=current_user["id"], connection_id=id)
        return {"ok": True, "id": id}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to cancel connection request {id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not cancel connection request")


@router.get("/connections")
def list_connections(
    status: Optional[str] = Query(None, description="Filter: pending | accepted | rejected | revoked"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """List connections where the caller acts as either buyer or seller.

    Response shape (backward compatible — ``as_seller`` / ``as_buyer`` are
    unchanged, everything else is additive):

        {
          "as_seller": [...],           # links where I sell
          "as_buyer":  [...],           # links where I buy
          "incoming_requests": [...],   # pending, waiting on ME to decide
          "outgoing_requests": [...],   # pending, waiting on THEM
          "counts": {"accepted": n, "incoming": n, "outgoing": n},
          "total": n, "limit": n, "offset": n
        }

    Paginated and single-query-resolved (review finding F-5).
    """
    bid = current_user["id"]

    base = db.query(B2BConnection).filter(
        (B2BConnection.seller_business_id == bid) | (B2BConnection.buyer_business_id == bid)
    )
    if status:
        if status not in conn_service.VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        base = base.filter(B2BConnection.status == status)

    total = base.count()
    rows = base.order_by(B2BConnection.updated_at.desc(), B2BConnection.id.desc()) \
               .offset(offset).limit(limit).all()

    businesses = _business_map(db, rows)
    serialized = [_conn_out(c, db, viewer_id=bid, businesses=businesses) for c in rows]

    accepted = [c for c in serialized if c["status"] == conn_service.STATUS_ACCEPTED]
    incoming = [c for c in serialized if c["is_incoming_request"]]
    outgoing = [c for c in serialized if c["is_outgoing_request"]]
    unclaimed = [c for c in serialized if c["requester_unknown"]]

    return {
        # Only ACCEPTED links appear in the buyer/seller lists — a pending
        # request must never be usable as if it were a live relationship.
        "as_seller": [c for c in accepted if c["seller_business_id"] == bid],
        "as_buyer": [c for c in accepted if c["buyer_business_id"] == bid],
        "incoming_requests": incoming,
        "outgoing_requests": outgoing,
        # Pending rows with no recorded sender (R3). Actionable only by
        # re-sending the request, which claims them.
        "unclaimed_requests": unclaimed,
        "counts": {
            "accepted": len(accepted),
            "incoming": len(incoming),
            "outgoing": len(outgoing),
            "unclaimed": len(unclaimed),
        },
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@router.post("/connections/{id}/policy")
def set_connection_policy(id: int, req: PolicyRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Update connection pricing and visibility parameters (Seller flow)."""
    try:
        conn = conn_service.update_connection_policy(
            db,
            seller_business_id=current_user["id"],
            connection_id=id,
            price_tier=req.price_tier,
            discount_pct=req.discount_pct,
            credit_limit=req.credit_limit,
            stock_visibility=req.stock_visibility,
            catalog_category=req.catalog_category
        )
        return _conn_out(conn, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        logger.error(f"Failed to set connection policy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update connection policy")

@router.post("/connections/{id}/revoke")
def revoke_partnership(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Revoke partnership (either buyer or seller can trigger)."""
    try:
        conn = conn_service.revoke_connection(db, business_id=current_user["id"], connection_id=id)
        return _conn_out(conn, db)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to revoke partnership: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not revoke partnership")

@router.get("/catalog/{seller_bizid}")
def get_catalog(seller_bizid: str, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Buyer browses connected supplier's catalog (scoped by connection policies)."""
    seller = db.query(User).filter(User.public_id == seller_bizid).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Supplier BizID not found")
        
    try:
        catalog = order_service.get_supplier_catalog(
            db,
            buyer_business_id=current_user["id"],
            seller_business_id=seller.id
        )
        return {"items": catalog}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        logger.error(f"Catalog retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve catalogue")



