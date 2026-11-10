"""Validation shared by account edits; values never change password whitespace."""
import re


def normalize_email(value, *, required=False):
    clean = (value or "").strip().lower()
    if not clean:
        if required:
            raise ValueError("A valid registered email address is required for password updates.")
        return None
    if len(clean) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", clean):
        raise ValueError("Enter a valid email address.")
    return clean


def validate_password(value):
    if not isinstance(value, str) or len(value) < 8 or not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c.isdigit() for c in value):
        raise ValueError("Password must be at least 8 characters with uppercase, lowercase and a digit.")
