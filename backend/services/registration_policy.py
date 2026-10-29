"""Signup contact validation and durable first-time trial eligibility."""
import hashlib
import re

TRIAL_DAYS = 14


def normalize_phone(value):
    raw = (value or "").strip()
    if not raw or not re.fullmatch(r"\+?[0-9 ()\-.]+", raw):
        raise ValueError("A valid phone number is required, including its country code.")
    digits = re.sub(r"[^0-9]", "", raw)
    if not raw.startswith("+"):
        if len(digits) == 10:
            digits = "91" + digits  # legacy Indian local-number entry
        elif not (len(digits) == 12 and digits.startswith("91")):
            raise ValueError("Include the phone number's country code (for example +91).")
    if not 8 <= len(digits) <= 15 or digits.startswith("0") or len(set(digits)) == 1:
        raise ValueError("Enter a valid phone number with 8 to 15 digits including country code.")
    if digits.startswith("91") and len(digits) != 12:
        raise ValueError("Enter a valid 10-digit Indian phone number.")
    return "+" + digits


def phone_key(value):
    try:
        canonical = normalize_phone(value)
    except ValueError:
        return None
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def retain_trial_claim(db, user):
    """Keep an already used trial from restarting after account deletion/rekey.

    The standalone ledger stores a fingerprint, not the contact number or a FK
    to the account. Existing accounts from before this ledger are covered too.
    """
    import json
    from database.models import TrialPhoneClaim
    from sqlalchemy.exc import IntegrityError
    settings = json.loads(user.settings or "{}")
    subscription = settings.get("subscription") or {}
    key = phone_key(user.phone)
    if not key or subscription.get("granted_by") != "trial":
        return
    if db.get(TrialPhoneClaim, key) is None:
        try:
            with db.begin_nested():
                db.add(TrialPhoneClaim(phone_hash=key))
                db.flush()
        except IntegrityError:
            # A concurrent signup/delete may already have recorded this claim.
            if db.get(TrialPhoneClaim, key) is None:
                raise
