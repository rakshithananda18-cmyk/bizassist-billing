import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from database.db import get_db, DATABASE_URL
from database.models import User
from services.auth import hash_password, verify_password, create_access_token, get_active_user
from services.rate_limiter import check_ip_rate_limit

router = APIRouter()
logger = logging.getLogger("bizassist.auth")

# Auto-detect which type of DB this backend is running on.
# The frontend stores this as the user's "home mode" so API requests
# always route back to the correct backend after a mode switch.
_DB_MODE = "cloud" if ("postgresql" in DATABASE_URL or "postgres" in DATABASE_URL) else "local"


class LoginRequest(BaseModel):
    username: str
    password: str


class IdentityCheckRequest(BaseModel):
    username: str


@router.post("/api/biz_id/check")
def biz_id_check(req: IdentityCheckRequest, db: Session = Depends(get_db)):
    """
    Lightweight, PUBLIC existence check for the registration UX.

    Returns ONLY {"exists": bool} — no business name or any other field — so it
    can't be used to enumerate account details. Lets the signup form branch to
    "log in & link" vs "create new" before the user fills the whole form.
    """
    uname = (req.username or "").strip()
    exists = bool(uname) and db.query(User).filter(User.username == uname).first() is not None
    return {"exists": exists}


class SignupRequest(BaseModel):
    username: str
    password: str
    business_name: str
    # Optional cloud-issued BizID. When the downloaded app registers, it creates
    # the account on the cloud first (the single authority), then mirrors it
    # locally passing the cloud's public_id here so both sides share one BizID.
    # When omitted (web signup / standalone), a new BizID is minted.
    public_id: Optional[str] = None


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

        # (§9.5) Staff are not OFFERED a direct login in the UI — the login screen
        # is owner-gated (owner username → Owner / Staff buttons → /login/staff),
        # and a staff name that collides cross-business gets an internal username
        # they don't know. We keep /login working here for backward compat (API +
        # existing flows); the UI never exposes a direct staff-username login.
        # (A strict server-side block is a clean follow-up, paired with migrating
        #  the test suite + any internal callers to /login/staff.)

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
            "public_id": user.public_id,   # BizID — the stable cross-DB identity spine (D9)
            "business_name": business_name,
            "role": user.role
        })

        logger.info(f"[AUTH] User '{req.username}' authenticated (role={user.role}, business={business_id}).")
        return {
            "token": token,
            "id": business_id,
            "user_id": user.id,
            "username": user.username,
            "public_id": user.public_id,   # BizID — lets the client confirm/unify identity
            "business_name": business_name,
            "role": user.role,
            "counter_prefix": user.counter_prefix,   # POS counter series for this login (§9.3a)
            "db_mode": _DB_MODE,   # 'local' | 'cloud' — tells frontend which backend this account lives on
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Error during login for username '{req.username}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server login error")


class StaffLoginRequest(BaseModel):
    owner_username: str
    staff_login_name: str
    password: str


@router.get("/staff-counters")
def staff_counters(owner: str, db: Session = Depends(get_db)):
    """(§9.5) Public lookup for the owner-gated staff-login dropdown: resolve an
    OWNER username → that business's name + its staff counters. Staff names are
    only reachable by knowing the owner's username (never enumerable directly).
    Returns an empty `staff` list if the owner has none; 404 if no such owner."""
    owner_row = db.query(User).filter(
        User.username == owner, User.parent_business_id.is_(None)
    ).first()
    if not owner_row:
        raise HTTPException(status_code=404, detail="No business found for that owner username")
    staff = (
        db.query(User)
        .filter(User.parent_business_id == owner_row.id)
        .order_by(User.staff_login_name.asc())
        .all()
    )
    return {
        "business_name": owner_row.business_name,
        "owner_username": owner_row.username,
        "staff": [
            {
                "login_name": s.staff_login_name or s.username,
                "counter_prefix": s.counter_prefix,
                "role": s.role,
            }
            for s in staff
        ],
    }


@router.post("/login/staff")
def staff_login(req: StaffLoginRequest, request: Request, db: Session = Depends(get_db)):
    """(§9.5) Staff login scoped to the owner's business — staff never use a global
    username. Resolve owner → staff by per-business `staff_login_name` → verify
    password → issue the same business-scoped JWT as /login. The JWT carries the
    internal global-unique username (routes resolve by it); the response returns
    the bare name for display."""
    try:
        ip = request.client.host if request.client else "unknown"
        rl = check_ip_rate_limit(ip)
        if not rl["allowed"]:
            raise HTTPException(status_code=429, detail=rl["reason"])

        owner = db.query(User).filter(
            User.username == req.owner_username, User.parent_business_id.is_(None)
        ).first()
        if not owner:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        staff = (
            db.query(User)
            .filter(
                User.parent_business_id == owner.id,
                func.lower(User.staff_login_name) == (req.staff_login_name or "").strip().lower(),
            )
            .first()
        )
        if not staff or not verify_password(req.password, staff.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        business_id = owner.id
        token = create_access_token({
            "id": business_id,
            "user_id": staff.id,
            "username": staff.username,          # internal global-unique → route resolution
            "public_id": staff.public_id,
            "business_name": owner.business_name,
            "role": staff.role,
        })
        logger.info(f"[AUTH] Staff '{staff.staff_login_name}' logged into business {business_id} (owner {owner.username}).")
        return {
            "token": token,
            "id": business_id,
            "user_id": staff.id,
            "username": staff.staff_login_name or staff.username,   # bare name for display
            "public_id": staff.public_id,
            "business_name": owner.business_name,
            "role": staff.role,
            "counter_prefix": staff.counter_prefix,
            "db_mode": _DB_MODE,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Staff login error: {str(e)}", exc_info=True)
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
        
        # Test User Policy (leakage prevention):
        # 1. Test usernames (legacy fixture prefixes + 'biz_test_') are ONLY allowed
        #    on a test database, OR when ALLOW_TEST_USERS is explicitly set.
        # 2. Otherwise blocked on production/development DBs to prevent pollution.
        # The ALLOW_TEST_USERS escape hatch exists so a CI/staging run — or a real
        # user whose name happens to start with one of these prefixes — isn't hard-
        # blocked: the operator opts in deliberately rather than relying solely on
        # the fragile "'test' in the DB URL" substring check.
        import os
        db_url = os.environ.get("DATABASE_URL", "")
        allow_test_users = os.environ.get("ALLOW_TEST_USERS", "").lower() in ("1", "true", "yes")
        is_test_db = "test" in db_url
        test_prefixes = ("own_", "test_", "idem_", "pull_", "u_", "o_", "biz_test_", "rec_")
        is_test_username = req.username.startswith(test_prefixes)

        if is_test_username and not (is_test_db or allow_test_users):
            logger.critical(f"[AUTH] Blocked test username '{req.username}' registration attempt on non-test database.")
            raise HTTPException(
                status_code=400,
                detail="Test user registration is not allowed on this database."
            )

        from core.connection.utils import generate_bizid
        # Adopt a cloud-issued BizID when provided (local mirror of a cloud
        # account); otherwise mint a fresh one (web signup / standalone).
        bizid = (req.public_id or "").strip() or generate_bizid(db)
        user = User(
            username=req.username,
            password=hash_password(req.password),
            business_name=req.business_name,
            role="enterprise",
            public_id=bizid
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        token = create_access_token({
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "public_id": user.public_id,   # BizID — stable cross-DB identity spine (D9)
            "business_name": user.business_name,
            "role": user.role
        })

        logger.info(f"[AUTH] User '{req.username}' registered and authenticated.")
        return {
            "token": token,
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "public_id": user.public_id,   # BizID — client mirrors this to the local account
            "business_name": user.business_name,
            "role": user.role,
            "counter_prefix": user.counter_prefix,   # POS counter series for this login (§9.3a)
            "db_mode": _DB_MODE,   # 'local' | 'cloud' — tells frontend which backend this account lives on
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
    counter_prefix: Optional[str] = None   # owner sets their OWN POS counter series (§9.3a)


@router.get("/profile")
def get_profile(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == current_user.get("username")).first()
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
        "logo": user.logo,
        "counter_prefix": user.counter_prefix,
    }


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == current_user.get("username")).first()
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
    if req.counter_prefix is not None:
        import re
        token = re.sub(r"[^A-Za-z0-9_]", "", req.counter_prefix.strip()).rstrip("-")[:8]
        user.counter_prefix = token or None

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
        "logo": user.logo,
        "counter_prefix": user.counter_prefix,
    }


# ---------------------------------------------------------------------------
# APP SETTINGS — stored as JSON on the User record (own naming schema)
# ---------------------------------------------------------------------------

import json

# Canonical default settings — own naming, no competitor prefixes
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
        "pos_show_serial": False,
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
        # Invoice-template system (plan Phase 1): the business's default template
        # for the invoice viewer. classic | modern | thermal. Per-user last-used
        # lives client-side; this is the business default.
        "invoice_template": "classic",
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


def _get_user_settings(user: User, db: Session = None) -> dict:
    """Return merged settings: defaults overridden by what's saved on the user."""
    import copy
    logger.debug(f"[SETTINGS] Merging settings for user '{user.username}' (ID {user.id})")
    base = copy.deepcopy(_DEFAULT_SETTINGS)

    # 1. Start with the owner settings if this is a staff user
    if user.parent_business_id and db:
        owner = db.query(User).filter(User.id == user.parent_business_id).first()
        if owner and owner.settings:
            try:
                owner_saved = json.loads(owner.settings)
                for section, values in owner_saved.items():
                    if section in base and isinstance(values, dict):
                        base[section].update(values)
                logger.debug(f"[SETTINGS] Merged settings from owner '{owner.username}' as base config")
            except Exception as e:
                logger.warning(f"[SETTINGS] Failed to parse owner settings: {str(e)}")

    # 2. Merge user's own settings on top (covers cashier-specific preferences)
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
        logger.debug(f"[SETTINGS] User '{user.username}' has no custom settings, using base/defaults")
    return base


@router.get("/settings")
def get_settings(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Return current user's app settings (merged with defaults)."""
    logger.info(f"[SETTINGS] GET /settings requested by user '{current_user.get('username')}' (ID {current_user.get('id')})")
    user = db.query(User).filter(User.username == current_user.get("username")).first()
    if not user:
        logger.warning(f"[SETTINGS] User with ID {current_user.get('id')} not found")
        raise HTTPException(status_code=404, detail="User not found")
    return _get_user_settings(user, db)


@router.put("/settings")
def update_settings(
    req: SettingsUpdateRequest,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Merge-update the user's app settings and persist."""
    logger.info(f"[SETTINGS] PUT /settings requested by user '{current_user.get('username')}' (ID {current_user.get('id')})")

    user = db.query(User).filter(User.username == current_user.get("username")).first()
    if not user:
        logger.warning(f"[SETTINGS] User with ID {current_user.get('id')} not found during update")
        raise HTTPException(status_code=404, detail="User not found")

    current = _get_user_settings(user, db)

    # Restrict cashiers from modifying non-general settings
    is_cashier = (current_user.get("role") or "").lower() == "cashier"
    if is_cashier:
        # Ignore sections if they are identical to what's already saved
        if req.transactions and req.transactions == current.get("transactions", {}): req.transactions = None
        if req.inventory and req.inventory == current.get("inventory", {}): req.inventory = None
        if req.print and req.print == current.get("print", {}): req.print = None
        if req.labels and req.labels == current.get("labels", {}): req.labels = None

        if req.transactions is not None or req.inventory is not None or req.print is not None or req.labels is not None:
            logger.warning(f"[SETTINGS] Cashier '{current_user.get('username')}' blocked from modifying global settings")
            raise HTTPException(status_code=403, detail="Permission denied: cashier restricted from modifying global settings")
        if req.general is not None:
            blocked_keys = ("realtime_sync_global", "hosting_mode")
            if any(k in req.general and req.general[k] != current.get("general", {}).get(k) for k in blocked_keys):
                logger.warning(f"[SETTINGS] Cashier '{current_user.get('username')}' blocked from modifying global general configurations")
                raise HTTPException(status_code=403, detail="Permission denied: cashier restricted from modifying global configurations")

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

