import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database.db import SessionLocal
from database.models import User
from services.auth import hash_password, verify_password, create_access_token

router = APIRouter()
logger = logging.getLogger("bizassist.auth")


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str
    business_name: str


@router.post("/login")
def login(req: LoginRequest):
    db = SessionLocal()
    logger.info(f"Login attempt for username '{req.username}'...")
    try:
        user = db.query(User).filter(User.username == req.username).first()
        if not user or not verify_password(req.password, user.password):
            logger.warning(f"Failed login attempt for username '{req.username}': Invalid credentials")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        token = create_access_token({
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        })
        
        logger.info(f"User '{req.username}' successfully authenticated (role={user.role}).")
        return {
            "token": token,
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login flow for username '{req.username}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server login error")
    finally:
        db.close()


@router.post("/signup")
def signup(req: SignupRequest):
    db = SessionLocal()
    logger.info(f"Signup attempt for username '{req.username}'...")
    try:
        existing = db.query(User).filter(User.username == req.username).first()
        if existing:
            logger.warning(f"Failed signup attempt: username '{req.username}' already exists.")
            raise HTTPException(status_code=400, detail="Username already exists")
        
        user = User(
            username=req.username,
            password=hash_password(req.password),
            business_name=req.business_name,
            role="enterprise"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        token = create_access_token({
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        })
        
        logger.info(f"User '{req.username}' successfully registered and authenticated.")
        return {
            "token": token,
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error during signup flow for username '{req.username}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server signup error")
    finally:
        db.close()
