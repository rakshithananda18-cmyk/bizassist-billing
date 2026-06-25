import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database.db import get_db, DATABASE_URL
from database.models import User
from services.auth import hash_password, verify_password, create_access_token, get_active_user
from services.rate_limiter import check_ip_rate_limit

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
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    logger.info(f"[AUTH] Login attempt for username '{req.username}'...")
    try:
        # Check IP-based rate limiting
        ip = request.client.host if request.client else "unknown"
        rl = check_ip_rate_limit(ip)
        if not rl["allowed"]:
            raise HTTPException(status_code=429, detail=rl["reason"])

        user = db.query(User).filter(User.username == req.username).first()
        if not user or not verify_password(req.password, user.password):
            logger.warning(f"[AUTH] Failed login for username '{req.username}': invalid credentials")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Staff sub-accounts scope to their owner's business: the JWT `id` (the
        # data scope every route reads) becomes the parent business id, while
        # `user_id` keeps the staff member's own identity.
        business_id = user.parent_business_id or user.id
        business_name = user.business_name
        if user.parent_business_id:
            owner = db.query(User).filter(User.id == user.parent_business_id).first()
            if owner:
                business_name = owner.business_name

        token = create_access_token({
            "id": business_id,
            "user_id": user.id,
            "username": user.username,
            "business_name": business_name,
            "role": user.role
        })

        logger.info(f"[AUTH] User '{req.username}' authenticated (role={user.role}, business={business_id}).")
        return {
            "token": token,
            "id": business_id,
            "user_id": user.id,
            "username": user.username,
            "business_name": business_name,
            "role": user.role
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Error during login for username '{req.username}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server login error")


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    logger.info(f"[AUTH] Signup attempt for username '{req.username}'...")
    try:
        # Enforce password strength policy
        password = req.password
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
        if not any(c.isupper() for c in password):
            raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in password):
            raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in password):
            raise HTTPException(status_code=400, detail="Password must contain at least one number.")

        existing = db.query(User).filter(User.username == req.username).first()
        if existing:
            logger.warning(f"[AUTH] Failed signup: username '{req.username}' already exists.")
            raise HTTPException(status_code=400, detail="Username already exists")
        
        from core.connection.utils import generate_bizid
        user = User(
            username=req.username,
            password=hash_password(req.password),
            business_name=req.business_name,
            role="enterprise",
            public_id=generate_bizid(db)
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        token = create_access_token({
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        })

        logger.info(f"[AUTH] User '{req.username}' registered and authenticated.")
        return {
            "token": token,
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[AUTH] Error during signup for username '{req.username}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server signup error")


class ProfileUpdateRequest(BaseModel):
    business_name: Optional[str] = None
    gstin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    pan: Optional[str] = None
    logo: Optional[str] = None


@router.get("/profile")
def get_profile(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    user_id = current_user["id"]
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "business_name": user.business_name,
        "role": user.role,
        "public_id": user.public_id,
        "gstin": user.gstin,
        "phone": user.phone,
        "email": user.email,
        "address": user.address,
        "state_code": user.state_code,
        "pan": user.pan,
        "logo": user.logo
    }


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    user_id = current_user["id"]
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if req.business_name is not None:
        user.business_name = req.business_name
    if req.gstin is not None:
        user.gstin = req.gstin
    if req.phone is not None:
        user.phone = req.phone
    if req.email is not None:
        user.email = req.email
    if req.address is not None:
        user.address = req.address
    if req.state_code is not None:
        user.state_code = req.state_code
    if req.pan is not None:
        user.pan = req.pan
    if req.logo is not None:
        user.logo = req.logo
        
    db.commit()
    db.refresh(user)
    
    return {
        "id": user.id,
        "username": user.username,
        "business_name": user.business_name,
        "role": user.role,
        "public_id": user.public_id,
        "gstin": user.gstin,
        "phone": user.phone,
        "email": user.email,
        "address": user.address,
        "state_code": user.state_code,
        "pan": user.pan,
        "logo": user.logo
    }


# ---------------------------------------------------------------------------
# APP SETTINGS — stored as JSON on the User record (own naming schema)
# ---------------------------------------------------------------------------

import json

# Canonical default settings — own naming, no Vyapar prefixes
_DEFAULT_SETTINGS = {
    # ── General ──────────────────────────────────────────────────────────────
    "general": {
        "passcode_lock": False,
        "lock_timeout_minutes": 60,      # 0=never, 30, 60, 120
        "privacy_mode": False,           # hides dashboard revenue figures
        "auto_backup": False,
        "backup_reminder_days": 7,
        "date_format": "DD/MM/YYYY",     # 0=DD/MM/YYYY, 1=MM/DD/YYYY, 2=YYYY-MM-DD
        "quantity_decimal_places": 2,
        "amount_decimal_places": 2,
        "app_zoom": 100,                 # UI scale percentage: 80-130
        "hosting_mode": "cloud" if "postgres" in DATABASE_URL or "postgresql" in DATABASE_URL else "local",         # local | hybrid | cloud
    },
    # ── Transactions ─────────────────────────────────────────────────────────
    "transactions": {
        "tax_invoice_enabled": False,
        "discount_enabled": True,
        "discount_in_amount": False,       # False = %, True = ₹
        "payment_reminder_enabled": True,
        "payment_reminder_days": 1,
        "estimate_enabled": True,          # Quotes / Estimates
        "proforma_invoice_enabled": True,
        "delivery_challan_enabled": True,
        "sale_order_enabled": True,
        "purchase_order_enabled": True,
        "prevent_negative_stock": False,
        "round_off_enabled": True,
        "round_off_type": "nearest",       # nearest | ceil | floor
        "payment_terms_enabled": False,
        "eway_bill_enabled": False,
        "composite_scheme": False,
        "pos_show_sku": True,
        "pos_show_unit": True,
        "pos_show_discount": True,
        "pos_show_tax": True,
        "pos_show_hsn": False,
        "pos_show_mrp": False,
    },
    # ── Items / Inventory ─────────────────────────────────────────────────────
    "inventory": {
        "stock_tracking": True,
        "item_units_enabled": True,
        "item_categories_enabled": True,
        "batch_tracking": False,
        "expiry_date_tracking": False,
        "manufacturing_date_tracking": False,
        "serial_tracking": False,
        "mrp_enabled": False,
        "wholesale_price": False,
        "barcode_scanning": False,
        "auto_update_sale_price": False,
    },
    # ── Print / PDF ───────────────────────────────────────────────────────────
    "print": {
        "theme_color": "#C2714F",          # terracotta default
        "page_size": "A4",                 # A4 | A5 | Letter
        "print_orientation": "portrait",   # portrait | landscape
        "invoice_theme": "classic",        # classic | modern | minimal
        "print_logo": True,
        "print_company_name": True,
        "print_company_address": True,
        "print_company_phone": True,
        "print_company_email": True,
        "print_gstin": True,
        "print_terms_conditions": True,
        "terms_conditions_text": "Thank you for your business!",
        "print_signature": True,
        "signature_label": "Authorised Signatory",
        "customer_signature": True,
        "customer_signature_label": "Customer Signature",
        "print_tax_breakdown": True,
        "print_item_sno": True,
        "print_item_hsn": True,
        "print_item_discount": True,
        "print_item_tax": True,
        "print_amount_in_words": False,
        "extra_space_enabled": False,
        "text_size": "medium",             # small | medium | large
        "copy_count": 1,
        "thermal_printer_mode": False,
        "thermal_page_size": "3inch",      # 3inch (80mm) | 2inch (58mm)
        "thermal_theme": "theme_standard", # theme_standard | theme_compact
    },
    # ── Transaction Names (custom labels) ────────────────────────────────────
    "labels": {
        "sale": "Sales Invoice",
        "purchase": "Purchase Bill",
        "estimate": "Estimate",
        "proforma": "Proforma Invoice",
        "delivery_challan": "Delivery Challan",
        "sale_return": "Credit Note",
        "purchase_return": "Debit Note",
        "payment_in": "Payment Receipt",
        "payment_out": "Payment Out",
        "expense": "Expense",
        "income": "Other Income",
        "sale_order": "Sale Order",
        "purchase_order": "Purchase Order",
    }
}


class SettingsUpdateRequest(BaseModel):
    general: Optional[dict] = None
    transactions: Optional[dict] = None
    inventory: Optional[dict] = None
    print: Optional[dict] = None
    labels: Optional[dict] = None


def _get_user_settings(user: User) -> dict:
    """Return merged settings: defaults overridden by what's saved on the user."""
    import copy
    logger.debug(f"[SETTINGS] Merging settings for user '{user.username}' (ID {user.id})")
    base = copy.deepcopy(_DEFAULT_SETTINGS)
    if user.settings:
        try:
            saved = json.loads(user.settings)
            for section, values in saved.items():
                if section in base and isinstance(values, dict):
                    base[section].update(values)
            logger.debug(f"[SETTINGS] Settings successfully merged for user '{user.username}'")
        except Exception as e:
            logger.warning(f"[SETTINGS] Failed to parse settings for user '{user.username}': {user.settings}, error: {str(e)}", exc_info=True)
    else:
        logger.debug(f"[SETTINGS] User '{user.username}' has no custom settings, using defaults")
    return base


@router.get("/settings")
def get_settings(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Return current user's app settings (merged with defaults)."""
    logger.info(f"[SETTINGS] GET /settings requested by user '{current_user.get('username')}' (ID {current_user.get('id')})")
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        logger.warning(f"[SETTINGS] User with ID {current_user.get('id')} not found")
        raise HTTPException(status_code=404, detail="User not found")
    return _get_user_settings(user)


@router.put("/settings")
def update_settings(
    req: SettingsUpdateRequest,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Merge-update the user's app settings and persist."""
    logger.info(f"[SETTINGS] PUT /settings requested by user '{current_user.get('username')}' (ID {current_user.get('id')})")

    # Restrict cashiers from modifying non-general settings
    is_cashier = (current_user.get("role") or "").lower() == "cashier"
    if is_cashier:
        if req.transactions is not None or req.inventory is not None or req.print is not None or req.labels is not None:
            logger.warning(f"[SETTINGS] Cashier '{current_user.get('username')}' blocked from modifying global settings")
            raise HTTPException(status_code=403, detail="Permission denied: cashier restricted from modifying global settings")

    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        logger.warning(f"[SETTINGS] User with ID {current_user.get('id')} not found during update")
        raise HTTPException(status_code=404, detail="User not found")

    current = _get_user_settings(user)

    # Merge each provided section
    for section in ("general", "transactions", "inventory", "print", "labels"):
        patch = getattr(req, section)
        if patch is not None:
            logger.debug(f"[SETTINGS] Patching section '{section}' for user '{user.username}': {patch}")
            current[section].update(patch)

    user.settings = json.dumps(current)
    db.commit()
    logger.info(f"[SETTINGS] Settings successfully updated and committed for user '{user.username}'")
    logger.debug(f"[SETTINGS] New settings structure: {current}")
    return current


