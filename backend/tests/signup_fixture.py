"""Explicit valid signup fixtures shared by legacy API workflow tests."""
import hashlib


def signup_payload(payload):
    # Copy, so a payload later reused for /login remains unchanged. Explicit
    # phone values (including invalid values in negative tests) are preserved.
    token = str(payload.get("username", "fixture"))
    digits = str(int(hashlib.sha256(token.encode()).hexdigest(), 16) % 1_000_000_000).zfill(9)
    return {"phone": "+919" + digits, **payload}
