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

# ── Helper Serializers ────────────────────────────────────────────────────────

def _conn_out(conn: B2BConnection, db: Session) -> dict:
    seller = db.query(User).filter(User.id == conn.seller_business_id).first()
    buyer = db.query(User).filter(User.id == conn.buyer_business_id).first()
    
    return {
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
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }

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
def connect_via_bizid(req: ConnectRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Connect directly to a business using their BizID."""
    try:
        conn = conn_service.create_direct_connection(
            db,
            initiator_id=current_user["id"],
            target_bizid=req.bizid.strip().upper(),
            connect_as=req.connect_as
        )
        return _conn_out(conn, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to connect via BizID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not establish connection")

@router.get("/connections")
def list_connections(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """List connections where the user acts as either buyer or seller."""
    bid = current_user["id"]
    conns_as_seller = db.query(B2BConnection).filter(B2BConnection.seller_business_id == bid).all()
    conns_as_buyer = db.query(B2BConnection).filter(B2BConnection.buyer_business_id == bid).all()
    
    return {
        "as_seller": [_conn_out(c, db) for c in conns_as_seller],
        "as_buyer": [_conn_out(c, db) for c in conns_as_buyer]
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



