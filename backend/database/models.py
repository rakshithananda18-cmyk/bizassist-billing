from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean
)

from database.db import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    business_name = Column(String)
    role = Column(String, default="enterprise") # "enterprise" or "admin"


class UploadedFile(Base):

    __tablename__ = "uploaded_files"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    filename = Column(String)

    file_type = Column(String)

    rows_count = Column(Integer)

    upload_time = Column(String)
    
    business_id = Column(Integer, nullable=True, index=True)


# -------------------------
# INVOICE TABLE
# -------------------------

class Invoice(Base):

    __tablename__ = "invoices"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    invoice_id = Column(String)

    customer = Column(String)

    product = Column(String)

    amount = Column(Float)

    status = Column(String)

    invoice_date = Column(String)

    due_date = Column(String)
    
    business_id = Column(Integer, nullable=True, index=True)
    file_id = Column(Integer, nullable=True, index=True)

# -------------------------
# INVENTORY TABLE
# -------------------------

class Inventory(Base):

    __tablename__ = "inventory"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    product_name = Column(String)

    stock = Column(Integer)

    expiry_date = Column(String)

    supplier = Column(String)
    
    business_id = Column(Integer, nullable=True, index=True)
    file_id = Column(Integer, nullable=True, index=True)

# -------------------------
# PAYMENTS TABLE
# -------------------------

class Payment(Base):

    __tablename__ = "payments"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    customer = Column(String)

    amount = Column(Float)

    due_date = Column(String)

    paid = Column(String)
    
    business_id = Column(Integer, nullable=True, index=True)
    file_id = Column(Integer, nullable=True, index=True)


# -------------------------
# CHAT MESSAGES TABLE
# -------------------------

class ChatMessage(Base):

    __tablename__ = "chat_messages"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    business_id = Column(Integer, index=True)
    role = Column(String)  # "user" or "assistant"
    content = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    session_id = Column(String, index=True, nullable=True)
    session_title = Column(String, nullable=True)


# -------------------------
# DOCUMENT EMBEDDINGS TABLE
# -------------------------

class DocumentEmbedding(Base):

    __tablename__ = "document_embeddings"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    business_id = Column(Integer, index=True)
    file_id = Column(Integer, nullable=True, index=True)
    document_type = Column(String)  # "invoice", "inventory", "payment"
    record_id = Column(Integer, nullable=True)  # References the ID of the matched row
    text_content = Column(String)  # The text representation that was embedded
    embedding_json = Column(String)  # JSON-serialized list of floats (embedding vector)


# -------------------------
# TOKEN USAGE TABLE
# -------------------------

class TokenUsage(Base):

    __tablename__ = "token_usage"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, index=True)
    model         = Column(String)              # e.g. "llama-3.1-8b-instant"
    model_tier    = Column(String)              # "AI_SIMPLE" or "AI_COMPLEX"
    input_tokens  = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens  = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)  # prompt cache hits (Claude)
    endpoint      = Column(String, default="/ask")
    timestamp     = Column(DateTime, default=datetime.utcnow)


# -------------------------
# ALERT CONFIG TABLE
# -------------------------

class AlertConfig(Base):

    __tablename__ = "alert_configs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, unique=True, index=True)
    business_name = Column(String, nullable=True)

    # Notification channels
    email = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)  # e.g. "+919876543210"

    # Alert toggles
    alert_overdue = Column(Boolean, default=True)
    alert_low_stock = Column(Boolean, default=True)
    alert_expiry = Column(Boolean, default=True)
    alert_daily_summary = Column(Boolean, default=True)

    # Thresholds
    low_stock_threshold = Column(Integer, default=10)
    expiry_days_threshold = Column(Integer, default=30)

    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)