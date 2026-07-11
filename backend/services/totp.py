"""
services/totp.py — RFC 6238 TOTP with the standard library only (REVIEW_1 §4.1).
================================================================================
Why hand-rolled: TOTP is ~20 lines of hmac/struct/base64 — pulling in pyotp for
the admin login adds a dependency to every desktop build for a feature that
only exists on the cloud (ADMIN_API_ENABLED). This implements the exact
algorithm Google Authenticator / Authy / 1Password expect:
  SHA-1, 6 digits, 30-second steps, ±1 step of clock drift tolerance.

Secrets are stored in the admin user's settings JSON under the reserved
"totp" key ({"secret", "enabled", "confirmed_at"}) — same schema-free pattern
as subscriptions; PUT /settings strips reserved keys so clients can't touch it.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time

DIGITS = 6
STEP_SECONDS = 30
DRIFT_STEPS = 1          # accept the previous/next 30s window (clock skew)


def generate_secret() -> str:
    """New 160-bit base32 secret (the format authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, account: str, issuer: str = "BizAssist Admin") -> str:
    """otpauth:// URI — paste/scan into any authenticator app."""
    from urllib.parse import quote
    label = quote(f"{issuer}:{account}")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def _hotp(secret: str, counter: int) -> str:
    # Base32 decode (re-pad — we strip '=' for display friendliness)
    pad = "=" * (-len(secret) % 8)
    key = base64.b32decode((secret + pad).upper())
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def current_code(secret: str, at: float = None) -> str:
    """The valid code for `at` (default: now). Exposed for tests."""
    counter = int((at if at is not None else time.time()) // STEP_SECONDS)
    return _hotp(secret, counter)


def verify_code(secret: str, code: str, at: float = None) -> bool:
    """Constant-time check across the ±DRIFT_STEPS windows."""
    if not secret or not code:
        return False
    code = str(code).strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    now = at if at is not None else time.time()
    counter = int(now // STEP_SECONDS)
    for delta in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        if hmac.compare_digest(_hotp(secret, counter + delta), code):
            return True
    return False
