"""Verify Google identity server-side before any account lookup/linking."""
import os
import time
from fastapi import HTTPException
from services.account_identity import normalize_email

DEFAULT_CLIENT_ID = "1076771386585-lt9gotlje2s5nrq509rokjngpufukuf0.apps.googleusercontent.com"


def verify_google_identity(credential):
    if not credential:
        raise HTTPException(status_code=400, detail="Missing Google credential token.")
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    from google.auth.exceptions import TransportError

    class TimedRequest(Request):
        def __call__(self, *args, **kwargs):
            kwargs["timeout"] = 10
            return super().__call__(*args, **kwargs)

    audience = os.environ.get("GOOGLE_CLIENT_ID", DEFAULT_CLIENT_ID).strip()
    if not audience:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")
    try:
        data = id_token.verify_oauth2_token(credential, TimedRequest(), audience=audience)
        if data.get("aud") != audience or data.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("Invalid token audience or issuer")
        if not isinstance(data.get("sub"), str) or not data["sub"].strip() or float(data.get("exp", 0)) <= time.time():
            raise ValueError("Invalid subject or expired token")
        if data.get("email_verified") is not True:
            raise ValueError("Unverified email")
        email = normalize_email(data.get("email"), required=True)
    except TransportError:
        raise HTTPException(status_code=503, detail="Unable to verify Google credentials. Please try again.") from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid Google authentication token.") from None
    return {"sub": data["sub"], "email": email, "name": str(data.get("name") or "").strip(),
            "picture": str(data.get("picture") or ""), "hd": data.get("hd"),
            "email_authoritative": email.endswith("@gmail.com") or bool(data.get("hd"))}
