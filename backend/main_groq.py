from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv
import os

from routes.upload import router as upload_router
from routes.insights import router as insights_router
from database.db import engine
from database.models import Base, User

from services.query_router import classify
from services.direct_query_handler import handle as direct_handle
from services.context_cache import get_focused_context
from services.auth import hash_password, verify_password, create_access_token, get_active_user

from sqlalchemy import text, func
from database.db import SessionLocal

load_dotenv()

app = FastAPI(title="BizAssist API")

# Schema migration and seeding
Base.metadata.create_all(bind=engine)

def run_migrations_and_seed():
    db = SessionLocal()
    try:
        # Check if business_id exists in invoices, if not add columns
        with engine.connect() as conn:
            tables = ["invoices", "inventory", "payments", "uploaded_files"]
            for table in tables:
                try:
                    conn.execute(text(f"SELECT business_id FROM {table} LIMIT 1"))
                except Exception:
                    # Column doesn't exist, let's add it
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN business_id INTEGER"))
                        print(f"Added business_id column to {table}")
                    except Exception as e:
                        print(f"Failed to add column to {table}: {e}")
            conn.commit()

        # Check if file_id exists in invoices, inventory, payments
        with engine.connect() as conn:
            tables = ["invoices", "inventory", "payments"]
            for table in tables:
                try:
                    conn.execute(text(f"SELECT file_id FROM {table} LIMIT 1"))
                except Exception:
                    # Column doesn't exist, let's add it
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN file_id INTEGER"))
                        print(f"Added file_id column to {table}")
                    except Exception as e:
                        print(f"Failed to add file_id column to {table}: {e}")
            conn.commit()

        # Seed users if they don't exist
        default_users = [
            {"id": 1, "username": "admin", "password": "admin123", "business_name": "Admin Central", "role": "admin"},
            {"id": 2, "username": "pharmacy", "password": "pharmacy123", "business_name": "MediCare Pharmacy", "role": "enterprise"},
            {"id": 3, "username": "supermarket", "password": "supermarket123", "business_name": "Daily Needs Supermarket", "role": "enterprise"},
            {"id": 4, "username": "store", "password": "store123", "business_name": "Apna Bazaar Store", "role": "enterprise"}
        ]
        
        for u in default_users:
            existing = db.query(User).filter(User.username == u["username"]).first()
            if not existing:
                user = User(
                    id=u["id"],
                    username=u["username"],
                    password=hash_password(u["password"]),
                    business_name=u["business_name"],
                    role=u["role"]
                )
                db.add(user)
        db.commit()

        # Migrate existing plaintext passwords to bcrypt
        all_users = db.query(User).all()
        for user in all_users:
            if not user.password.startswith("$2b$") and not user.password.startswith("$2a$"):
                user.password = hash_password(user.password)
        db.commit()

        # Migrate existing data with NULL business_id to user_id = 2 (Pharmacy)
        with engine.connect() as conn:
            for table in ["invoices", "inventory", "payments", "uploaded_files"]:
                try:
                    conn.execute(text(f"UPDATE {table} SET business_id = 2 WHERE business_id IS NULL"))
                except Exception as e:
                    print(f"Failed migrating null values in {table}: {e}")
            conn.commit()

    except Exception as e:
        print("Initialization/migration error:", e)
    finally:
        db.close()

run_migrations_and_seed()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(insights_router)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class Prompt(BaseModel):
    message: str
    user_id: int = None


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str
    business_name: str


@app.get("/")
def home():
    return {"message": "BizAssist AI server running"}


@app.post("/login")
def login(req: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == req.username).first()
        if not user or not verify_password(req.password, user.password):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        token = create_access_token({
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        })
        
        return {
            "token": token,
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        }
    finally:
        db.close()


@app.post("/signup")
def signup(req: SignupRequest):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == req.username).first()
        if existing:
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
        
        return {
            "token": token,
            "id": user.id,
            "username": user.username,
            "business_name": user.business_name,
            "role": user.role
        }
    finally:
        db.close()


@app.get("/admin/businesses")
def admin_businesses(current_user: dict = Depends(get_active_user)):
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Get all businesses (excluding admins)
        businesses = db.query(User).filter(User.role == "enterprise").all()
        result = []
        
        from database.models import Invoice, Inventory, UploadedFile
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
        return result
    finally:
        db.close()


@app.post("/ask")
def ask_ai(prompt: Prompt, current_user: dict = Depends(get_active_user)):
    """
    Hybrid AI endpoint.

    DIRECT path  →  DB query only, 0 tokens, ~5ms
    AI path      →  cached context + Groq, ~300-600 tokens
    """

    try:

        user_query = prompt.message.strip()

        # Determine user_id
        active_user_id = current_user["id"]

        # ── Layer 1: classify ────────────────────────────────────
        route, handler_key = classify(user_query)

        # ── Layer 2: direct DB answer ────────────────────────────
        if route == "DIRECT":
            answer = direct_handle(handler_key, user_query, active_user_id)

            if answer:
                return {
                    "response" : answer,
                    "source"   : "db",      # tells frontend: no AI token used
                }
            # If handler returned None (DB error), fall through to AI

        # ── Layer 3: Groq with cached context ────────────────────
        context = get_focused_context(user_query, active_user_id)

        system_prompt = (
            "You are BIZASSIST, an AI business intelligence assistant "
            "for Indian retail businesses (pharmacies, supermarkets, stores).\n\n"
            "Rules:\n"
            "- Answer ONLY using the data below. Never invent numbers.\n"
            "- Use ₹ for Indian Rupees. Be specific: name customers, amounts.\n"
            "- Format lists with bullet points. Keep answers concise.\n"
            "- If data is missing, say so clearly.\n\n"
            f"{context}"
        )

        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_query},
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.2,
            max_tokens=800,
        )

        return {
            "response" : completion.choices[0].message.content,
            "source"   : "ai",
        }

    except Exception as e:
        error_str = str(e)
        
        # Check for rate limit / quota exceeded (429)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            return {
                "error": "API quota exceeded. Rate limit hit. Please wait a moment and try again.",
                "status_code": 429,
                "details": error_str
            }
        
        return {
            "error": str(e),
            "status_code": 500
        }