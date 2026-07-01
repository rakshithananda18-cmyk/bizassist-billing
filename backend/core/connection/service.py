"""
core/connection/service.py
==========================
Domain service logic for B2B Connections and Codes.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from core.models import B2BConnection, B2BInviteCode
from core.connection.utils import generate_connection_code
from database.models import User

def create_connection_code(db: Session, seller_business_id: int, expires_in_hours: int = 24) -> B2BInviteCode:
    """Generate a temporary single-use connection code for a seller."""
    code_str = generate_connection_code(db)
    expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
    
    code_obj = B2BInviteCode(
        seller_business_id=seller_business_id,
        code=code_str,
        is_used=False,
        expires_at=expires_at
    )
    db.add(code_obj)
    db.commit()
    db.refresh(code_obj)
    return code_obj

def redeem_connection_code(db: Session, buyer_business_id: int, code: str) -> B2BConnection:
    """
    Redeem a connection code as a buyer to establish a B2B connection with the seller.
    Automatically accepts the connection link.
    """
    code_obj = db.query(B2BInviteCode).filter(B2BInviteCode.code == code).first()
    if not code_obj:
        raise ValueError("Invalid connection code")
    
    if code_obj.is_used:
        raise ValueError("This connection code has already been used")
        
    if code_obj.expires_at < datetime.utcnow():
        raise ValueError("This connection code has expired")
        
    seller_id = code_obj.seller_business_id
    if seller_id == buyer_business_id:
        raise ValueError("Cannot connect to your own business")
        
    # Check if a connection already exists
    conn = db.query(B2BConnection).filter(
        B2BConnection.seller_business_id == seller_id,
        B2BConnection.buyer_business_id == buyer_business_id
    ).first()
    
    if conn:
        conn.status = "accepted"
        conn.updated_at = datetime.utcnow()
    else:
        conn = B2BConnection(
            seller_business_id=seller_id,
            buyer_business_id=buyer_business_id,
            price_tier="standard",
            discount_pct=0.0,
            credit_limit=0.0,
            outstanding_balance=0.0,
            stock_visibility="exact",
            status="accepted"
        )
        db.add(conn)
        
    code_obj.is_used = True
    db.commit()
    db.refresh(conn)
    return conn

def update_connection_policy(
    db: Session,
    seller_business_id: int,
    connection_id: int,
    price_tier: str,
    discount_pct: float,
    credit_limit: float,
    stock_visibility: str,
    catalog_category: str = None
) -> B2BConnection:
    """
    Update B2BConnection settings. Allowed only for the seller.
    """
    conn = db.query(B2BConnection).filter(B2BConnection.id == connection_id).first()
    if not conn:
        raise ValueError("Connection not found")
        
    if conn.seller_business_id != seller_business_id:
        raise PermissionError("Only the seller can update connection settings")
        
    if price_tier not in ["standard", "wholesale", "distributor"]:
        raise ValueError("Invalid price tier")
        
    if stock_visibility not in ["exact", "band", "hidden"]:
        raise ValueError("Invalid stock visibility policy")
        
    conn.price_tier = price_tier
    conn.discount_pct = max(0.0, float(discount_pct))
    conn.credit_limit = max(0.0, float(credit_limit))
    conn.stock_visibility = stock_visibility
    conn.catalog_category = catalog_category
    conn.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(conn)
    return conn

def revoke_connection(db: Session, business_id: int, connection_id: int) -> B2BConnection:
    """
    Revoke a connection partnership. Can be initiated by either party.
    """
    conn = db.query(B2BConnection).filter(B2BConnection.id == connection_id).first()
    if not conn:
        raise ValueError("Connection not found")
        
    if business_id not in [conn.seller_business_id, conn.buyer_business_id]:
        raise PermissionError("Not authorized to revoke this connection")
        
    conn.status = "revoked"
    conn.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(conn)
    return conn

def create_direct_connection(
    db: Session,
    initiator_id: int,
    target_bizid: str,
    connect_as: str
) -> B2BConnection:
    """
    Connect directly to another business using their public BizID.
    """
    target = db.query(User).filter(User.public_id == target_bizid).first()
    if not target:
        raise ValueError("Business with this BizID not found")
        
    if target.id == initiator_id:
        raise ValueError("Cannot connect to your own business")
        
    if connect_as == "buyer":
        seller_id = target.id
        buyer_id = initiator_id
    elif connect_as == "seller":
        seller_id = initiator_id
        buyer_id = target.id
    else:
        raise ValueError("Invalid connection role")
        
    # Check if a connection already exists
    conn = db.query(B2BConnection).filter(
        B2BConnection.seller_business_id == seller_id,
        B2BConnection.buyer_business_id == buyer_id
    ).first()
    
    if conn:
        conn.status = "accepted"
        conn.updated_at = datetime.utcnow()
    else:
        conn = B2BConnection(
            seller_business_id=seller_id,
            buyer_business_id=buyer_id,
            price_tier="standard",
            discount_pct=0.0,
            credit_limit=0.0,
            outstanding_balance=0.0,
            stock_visibility="exact",
            status="accepted"
        )
        db.add(conn)
        
    db.commit()
    db.refresh(conn)
    return conn
