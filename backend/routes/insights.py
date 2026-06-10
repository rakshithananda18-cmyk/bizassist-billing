"""
routes/insights.py
==================
Thin HTTP adapters for dashboard/data endpoints.
All business logic lives in services/insights_service.py.
"""
import logging
from fastapi import APIRouter, Header, HTTPException
from database.db import SessionLocal
from services.auth import get_active_user
import services.insights_service as svc

router = APIRouter()
logger = logging.getLogger("bizassist.routes.insights")


def _user_id(authorization):
    return get_active_user(authorization)["id"]


@router.get("/insights")
def get_business_insights(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.business_insights(uid, db)
    except Exception as e:
        logger.error("insights error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch business insights")
    finally:
        db.close()


@router.get("/uploads")
def get_uploads(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.uploads_list(uid, db)
    except Exception as e:
        logger.error("uploads error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch uploads list")
    finally:
        db.close()


@router.get("/dashboard-summary")
def get_dashboard_summary(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.dashboard_summary(uid, db)
    except Exception as e:
        logger.error("dashboard-summary error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate dashboard summary")
    finally:
        db.close()


@router.get("/database")
def get_database(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.database_view(uid, db)
    except Exception as e:
        logger.error("database error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve database state")
    finally:
        db.close()


@router.delete("/database/delete")
def delete_entire_database(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.wipe_database(uid, db)
    except Exception as e:
        db.rollback()
        logger.error("database/delete error uid=%s: %s", uid, e, exc_info=True)
        return {"error": str(e), "message": "Failed to delete database"}
    finally:
        db.close()


@router.get("/top-customers")
def top_customers(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.top_customers(uid, db)
    except Exception as e:
        logger.error("top-customers error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch top customers")
    finally:
        db.close()


@router.get("/payments")
def get_payments(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.payments_view(uid, db)
    except Exception as e:
        logger.error("payments error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch payments")
    finally:
        db.close()


@router.get("/clients")
def get_clients(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.clients_view(uid, db)
    except Exception as e:
        logger.error("clients error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch clients list")
    finally:
        db.close()


@router.delete("/delete-upload/{upload_id}")
def delete_upload(upload_id: int, authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.delete_upload(uid, upload_id, db)
    except Exception as e:
        db.rollback()
        logger.error("delete-upload error uid=%s upload=%s: %s", uid, upload_id, e, exc_info=True)
        return {"error": str(e), "message": "Failed to delete upload"}
    finally:
        db.close()


@router.get("/dashboard-charts")
def dashboard_charts(authorization: str = Header(None)):
    uid = _user_id(authorization)
    db = SessionLocal()
    try:
        return svc.dashboard_charts(uid, db)
    except Exception as e:
        logger.error("dashboard-charts error uid=%s: %s", uid, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard data.")
    finally:
        db.close()
