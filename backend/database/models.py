from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime
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