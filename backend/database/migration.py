import logging
from sqlalchemy import text
from database.db import engine, SessionLocal
from database.models import Base, User, ChatMessage, DocumentEmbedding, AlertConfig, TokenUsage, RateLimitConfig
from services.auth import hash_password

logger = logging.getLogger("bizassist.migration")

def run_migrations_and_seed():
    """Checks database tables, runs required schema migrations, and seeds default users/data."""
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    
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
                        logger.info(f"Added business_id column to {table}")
                    except Exception as e:
                        logger.error(f"Failed to add column to {table}: {e}")
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
                        logger.info(f"Added file_id column to {table}")
                    except Exception as e:
                        logger.error(f"Failed to add file_id column to {table}: {e}")
            conn.commit()

        # Check if session_id exists in chat_messages, if not add columns
        with engine.connect() as conn:
            try:
                conn.execute(text("SELECT session_id FROM chat_messages LIMIT 1"))
            except Exception:
                try:
                    conn.execute(text("ALTER TABLE chat_messages ADD COLUMN session_id TEXT"))
                    conn.execute(text("ALTER TABLE chat_messages ADD COLUMN session_title TEXT"))
                    conn.execute(text("UPDATE chat_messages SET session_id = 'default', session_title = 'Previous Chat' WHERE session_id IS NULL"))
                    logger.info("Added session_id and session_title columns to chat_messages")
                except Exception as e:
                    logger.error(f"Failed to add session columns to chat_messages: {e}")
            conn.commit()

        # Seed users if they don't exist
        import os
        is_test = "test" in os.environ.get("DATABASE_URL", "")
        
        if is_test:
            default_users = [
                {"id": 1, "username": "admin", "password": "admin123", "business_name": "Admin Central", "role": "admin"},
                {"id": 2, "username": "pharmacy", "password": "pharmacy123", "business_name": "MediCare Pharmacy", "role": "enterprise"},
                {"id": 3, "username": "supermarket", "password": "supermarket123", "business_name": "Daily Needs Supermarket", "role": "enterprise"},
                {"id": 4, "username": "store", "password": "store123", "business_name": "Apna Bazaar Store", "role": "enterprise"}
            ]
        else:
            _admin_pw = os.environ.get("ADMIN_SEED_PASSWORD", "admin123")
            default_users = [
                {"id": 1, "username": "admin", "password": _admin_pw, "business_name": "Admin Central", "role": "admin"}
            ]
            
            # Delete demo users and their data in production
            from database.models import Invoice, Inventory, Payment, UploadedFile, DocumentEmbedding, ChatMessage
            demo_usernames = ["pharmacy", "supermarket", "store"]
            demo_users = db.query(User).filter(User.username.in_(demo_usernames)).all()
            for du in demo_users:
                logger.info(f"Removing demo user '{du.username}' and their associated data...")
                db.query(Invoice).filter(Invoice.business_id == du.id).delete()
                db.query(Inventory).filter(Inventory.business_id == du.id).delete()
                db.query(Payment).filter(Payment.business_id == du.id).delete()
                db.query(UploadedFile).filter(UploadedFile.business_id == du.id).delete()
                db.query(DocumentEmbedding).filter(DocumentEmbedding.business_id == du.id).delete()
                db.query(ChatMessage).filter(ChatMessage.business_id == du.id).delete()
                db.delete(du)
            db.commit()
        
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
                    logger.error(f"Failed migrating null values in {table}: {e}")
            conn.commit()

        # Add file_hash column to uploaded_files if missing
        with engine.connect() as conn:
            try:
                conn.execute(text("SELECT file_hash FROM uploaded_files LIMIT 1"))
            except Exception:
                try:
                    conn.execute(text("ALTER TABLE uploaded_files ADD COLUMN file_hash TEXT"))
                    logger.info("Added file_hash column to uploaded_files")
                except Exception as e:
                    logger.error(f"Failed to add file_hash column: {e}")
            conn.commit()

        # Ensure alert_configs table exists (created by Base.metadata.create_all above)
        logger.info("alert_configs table ensured.")

        logger.info("Database schema migration and seeding completed successfully.")

    except Exception as e:
        logger.error(f"Initialization/migration error: {e}")
    finally:
        db.close()
