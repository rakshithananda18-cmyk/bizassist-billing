import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from core.models import Godown
from services.auth import get_active_user

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.godowns")

class CreateGodown(BaseModel):
    name: str
    address: Optional[str] = None

def _godown_out(g: Godown) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "address": g.address,
        "is_active": g.is_active,
    }

@router.get("/godowns")
def list_godowns(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    bid = current_user["id"]
    godowns = db.query(Godown).filter(Godown.business_id == bid, Godown.is_active == True).all()
    if not godowns:
        # Auto-seed "Main Warehouse"
        main_godown = Godown(
            business_id=bid,
            name="Main Warehouse",
            address="Primary business storage",
            is_active=True
        )
        db.add(main_godown)
        db.commit()
        db.refresh(main_godown)
        godowns = [main_godown]
        logger.info("[GODOWNS] Auto-seeded default 'Main Warehouse' for biz=%s", bid)
    
    return [_godown_out(g) for g in godowns]

@router.post("/godowns", status_code=201)
def create_godown(
    req: CreateGodown,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    bid = current_user["id"]
    name_stripped = req.name.strip()
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Godown name cannot be empty")
        
    existing = db.query(Godown).filter(
        Godown.business_id == bid,
        Godown.name.ilike(name_stripped),
        Godown.is_active == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Godown '{name_stripped}' already exists")

    godown = Godown(
        business_id=bid,
        name=name_stripped,
        address=req.address,
        is_active=True
    )
    db.add(godown)
    db.commit()
    db.refresh(godown)
    logger.info("[GODOWNS] Created godown %s (biz=%s)", godown.id, bid)
    return _godown_out(godown)
