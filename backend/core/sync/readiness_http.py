from fastapi import Depends, Request
from database.db import get_db
from services.auth import get_active_user, resolve_business_id_in_db
from core.sync.readiness import assert_financial_ready


def require_financial_ready(request: Request, current_user=Depends(get_active_user), db=Depends(get_db)):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        assert_financial_ready(db, resolve_business_id_in_db(current_user, db))
