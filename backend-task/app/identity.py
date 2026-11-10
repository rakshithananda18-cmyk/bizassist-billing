"""Contact normalization for authentication; no cross-business fuzzy matching."""
from __future__ import annotations

import re

from sqlalchemy import func


def normalize_phone(value: str) -> str:
    """Match Billing's canonical international format and legacy Indian input."""
    raw = (value or "").strip()
    if not raw or not re.fullmatch(r"\+?[0-9 ()\-.]+", raw):
        raise ValueError("A valid phone number is required, including its country code.")
    digits = re.sub(r"[^0-9]", "", raw)
    if len(set(digits)) == 1:
        raise ValueError("Enter a valid phone number.")
    if not raw.startswith("+"):
        if len(digits) == 10:
            digits = "91" + digits
        elif not (len(digits) == 12 and digits.startswith("91")):
            raise ValueError("Include the phone number's country code (for example +91).")
    if not 8 <= len(digits) <= 15 or digits.startswith("0") or len(set(digits)) == 1:
        raise ValueError("Enter a valid phone number with 8 to 15 digits including country code.")
    if digits.startswith("91") and len(digits) != 12:
        raise ValueError("Enter a valid 10-digit Indian phone number.")
    return "+" + digits


def phone_filter(column, value: str):
    """Recognize canonical and old formatted numbers without suffix matching."""
    try:
        canonical = normalize_phone(value)
    except ValueError:
        return False
    digits = canonical[1:]
    candidates = [digits]
    if digits.startswith("91") and len(digits) == 12:
        candidates.append(digits[2:])
    stored = column
    for char in ("+", " ", "(", ")", "-", "."):
        stored = func.replace(stored, char, "")
    return stored.in_(candidates)
