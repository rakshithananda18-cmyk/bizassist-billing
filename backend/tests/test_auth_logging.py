"""
tests/test_auth_logging.py
==========================
Failed authentication must NOT be silent. The token path (missing / expired /
invalid) previously raised 401 with no log line; these tests pin that it now
logs a [AUTH] line.
"""
import os
import sys
import logging

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-tests-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi import HTTPException
import services.auth as auth


def _auth_lines(caplog):
    return [r.message for r in caplog.records if "[AUTH]" in r.message]


def test_invalid_token_logs_auth_warning(caplog):
    with caplog.at_level(logging.INFO, logger="bizassist.auth"):
        with pytest.raises(HTTPException) as exc:
            auth.get_active_user("Bearer not.a.real.jwt")
    assert exc.value.status_code == 401
    assert any("invalid token" in m.lower() for m in _auth_lines(caplog)), \
        "invalid token must produce a [AUTH] log line"


def test_missing_header_logs_auth(caplog):
    with caplog.at_level(logging.INFO, logger="bizassist.auth"):
        with pytest.raises(HTTPException) as exc:
            auth.get_active_user(None)
    assert exc.value.status_code == 401
    assert any("authorization header" in m.lower() for m in _auth_lines(caplog)), \
        "missing header must produce a [AUTH] log line"


def test_expired_token_logs_auth_warning(caplog):
    from datetime import timedelta
    # create a token that is already expired
    token = auth.create_access_token({"id": 1, "username": "x"}, expires_delta=timedelta(seconds=-5))
    with caplog.at_level(logging.INFO, logger="bizassist.auth"):
        with pytest.raises(HTTPException) as exc:
            auth.get_active_user(f"Bearer {token}")
    assert exc.value.status_code == 401
    assert any("expired" in m.lower() for m in _auth_lines(caplog)), \
        "expired token must produce a [AUTH] log line"


def test_valid_token_does_not_log_failure(caplog):
    token = auth.create_access_token({"id": 7, "username": "ok"})
    with caplog.at_level(logging.INFO, logger="bizassist.auth"):
        payload = auth.get_active_user(f"Bearer {token}")
    assert payload["id"] == 7
    assert not _auth_lines(caplog), "a valid token should not log an [AUTH] rejection"
