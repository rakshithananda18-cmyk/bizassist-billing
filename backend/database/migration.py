import logging
from sqlalchemy import text
from database.db import engine, SessionLocal
from database.models import Base, User
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
                    logger.error(f"Failed migrating null values in {table}: {e}")
            conn.commit()

        logger.info("Database schema migration and seeding completed successfully.")

    except Exception as e:
        logger.error(f"Initialization/migration error: {e}")
    finally:
        db.close()
