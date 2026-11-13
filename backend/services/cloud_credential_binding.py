"""Reject cloud credentials that cannot belong to the current local owner.

This is a negative identity filter, never authentication. The local install does
not have the cloud signing key. Only the cloud authenticates the token, checks
its expiry/revocation and authorizes the request. Reading its public claims here
lets us refuse a valid credential left behind by a restored/replaced local DB.
"""
from typing import Optional

import jwt


OWNER_ROLES = frozenset({"enterprise", "owner", "admin"})


def _positive_identity(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        identity = int(value)
    except (ValueError, TypeError):
        return None
    return identity if identity > 0 else None


def owner_claim_public_id(token: str) -> Optional[str]:
    """Read only enough untrusted claims to DENY mismatches or staff credentials.

    Expired same-owner tokens must reach /auth/refresh. Neither matching these
    claims nor passing this helper establishes that a credential is authentic.
    """
    if not isinstance(token, str) or not token:
        return None
    try:
        # A match never authenticates: the cloud must still verify the signature.
        claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})  # NOSONAR python:S5659 — reject-only identity filter
        public_id = claims.get("public_id")
        role = claims.get("role")
        owner_id = _positive_identity(claims.get("id"))
        subject_id = _positive_identity(claims.get("user_id"))
        if (not isinstance(public_id, str) or not public_id.strip()
                or not isinstance(role, str) or role.strip().lower() not in OWNER_ROLES
                or owner_id is None or owner_id != subject_id
                or claims.get("parent_business_id") not in (None, "")):
            return None
        return public_id.strip()
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        return None


def matches_current_local_owner(business_id: int, token: str, *, expected_public_id=None) -> bool:
    """Compare to the active DB, not a remembered row or database-local token ID."""
    public_id = owner_claim_public_id(token)
    if public_id is None or expected_public_id is not None and public_id != expected_public_id:
        return False
    try:
        from database import db as database
        from database.models import User

        # Resolve the factory on every lookup: restore/import can replace the DB
        # or reuse an integer primary key without replacing the credential file.
        with database.SessionLocal() as session:
            owner = session.query(User.public_id, User.role, User.parent_business_id).filter(
                User.id == business_id,
            ).one_or_none()
            return bool(owner is not None and owner.parent_business_id is None
                        and isinstance(owner.public_id, str) and owner.public_id.strip() == public_id
                        and isinstance(owner.role, str) and owner.role.strip().lower() in OWNER_ROLES)
    except Exception:
        # An unreadable owner is not permission to send this installation's data.
        return False
