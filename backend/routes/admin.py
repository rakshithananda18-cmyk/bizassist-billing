import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from database.db import SessionLocal
from database.models import User, Invoice, Inventory, UploadedFile
from services.auth import get_active_user

router = APIRouter()
logger = logging.getLogger("bizassist.admin")


@router.get("/admin/businesses")
def admin_businesses(current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin businesses directory...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin (role={getattr(admin_user, 'role', None)})")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Get all businesses (excluding admins)
        businesses = db.query(User).filter(User.role == "enterprise").all()
        result = []
        
        logger.info(f"Admin found {len(businesses)} enterprise accounts. Aggregating statistics...")
        for b in businesses:
            inv_count = db.query(Invoice).filter(Invoice.business_id == b.id).count()
            total_rev = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == b.id).scalar() or 0
            stock_count = db.query(Inventory).filter(Inventory.business_id == b.id).count()
            uploads = db.query(UploadedFile).filter(UploadedFile.business_id == b.id).count()
            
            result.append({
                "id": b.id,
                "username": b.username,
                "business_name": b.business_name,
                "invoice_count": inv_count,
                "total_revenue": total_rev,
                "inventory_count": stock_count,
                "upload_count": uploads
            })
        logger.info("Successfully loaded administrative stats for all businesses.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching admin businesses database statistics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error retrieving admin database records")
    finally:
        db.close()
