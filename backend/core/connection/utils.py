"""
core/connection/utils.py
========================
Helper utilities for generating human-friendly Crockford Base32 identifiers
and checking for collisions in the database.
"""
import random
from sqlalchemy.orm import Session
from database.models import User
from core.models import ConnectionCode

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def generate_crockford_base32(length: int) -> str:
    """Generate a random string of Crockford Base32 characters of given length."""
    return "".join(random.choice(CROCKFORD_ALPHABET) for _ in range(length))

def generate_bizid(db: Session) -> str:
    """
    Generate a unique BizID formatted as BA-XXXXXX.
    Checks for collisions in the database.
    """
    while True:
        suffix = generate_crockford_base32(6)
        bizid = f"BA-{suffix}"
        
        # Check collision in users table
        exists = db.query(User).filter(User.public_id == bizid).first()
        if not exists:
            return bizid

def generate_connection_code(db: Session) -> str:
    """
    Generate a unique 8-character Crockford Base32 connection code.
    Checks for collisions in the connection_codes table.
    """
    while True:
        code = generate_crockford_base32(8)
        
        # Check collision in connection_codes table
        exists = db.query(ConnectionCode).filter(ConnectionCode.code == code).first()
        if not exists:
            return code
