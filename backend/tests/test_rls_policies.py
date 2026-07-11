import pytest
from unittest.mock import MagicMock, patch
from database.db import current_business_id_var, get_db
from main_groq import _set_rls_business_id
from fastapi import Request

def test_contextvar_lifecycle():
    assert current_business_id_var.get() is None
    token = current_business_id_var.set(42)
    assert current_business_id_var.get() == 42
    current_business_id_var.reset(token)
    assert current_business_id_var.get() is None

import asyncio

def test_middleware_sets_and_resets_contextvar():
    # Mock JWT decode inside middleware
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer fake-token"}
    
    async def fake_call_next(req):
        # When route executes, contextvar should be set to the decoded business_id
        assert current_business_id_var.get() == 99
        return "response"

    with patch("jwt.decode") as mock_decode:
        mock_decode.return_value = {"id": 99}
        
        response = asyncio.run(_set_rls_business_id(request, fake_call_next))
        assert response == "response"
        
        # After request completes, contextvar should be reset to None
        assert current_business_id_var.get() is None

def test_get_db_postgresql_rls_execution():
    # Set contextvar
    token = current_business_id_var.set(123)
    
    # Mock SessionLocal and its connection/dialect
    mock_db = MagicMock()
    mock_db.bind.dialect.name = "postgresql"
    
    with patch("database.db.SessionLocal", return_value=mock_db):
        generator = get_db()
        # Advance generator to yield block
        db_yielded = next(generator)
        assert db_yielded == mock_db
        
        # Verify the RLS GUC was set via parameterized set_config() (REVIEW_1
        # P2 hardening: SET can't take bound params, set_config can).
        mock_db.execute.assert_any_call(
            pytest.approx(sa_text_expr("SELECT set_config('app.current_business_id', :bid, false)")),
            {"bid": "123"},
        )
        
        # Complete get_db generator (executes finally block)
        try:
            next(generator)
        except StopIteration:
            pass
            
        # Verify that RESET app.current_business_id was executed
        mock_db.execute.assert_any_call(
            pytest.approx(sa_text_expr("RESET app.current_business_id"))
        )
        mock_db.close.assert_called_once()
        
    current_business_id_var.reset(token)

def test_get_db_sqlite_ignored():
    token = current_business_id_var.set(123)
    
    mock_db = MagicMock()
    mock_db.bind.dialect.name = "sqlite"
    
    with patch("database.db.SessionLocal", return_value=mock_db):
        generator = get_db()
        db_yielded = next(generator)
        assert db_yielded == mock_db
        
        # Should NOT execute any Postgres RLS statements on SQLite
        assert mock_db.execute.call_count == 0
        
        try:
            next(generator)
        except StopIteration:
            pass
            
        assert mock_db.execute.call_count == 0
        mock_db.close.assert_called_once()
        
    current_business_id_var.reset(token)

# Helper to compare SQLAlchemy text() object values in tests
class sa_text_expr:
    def __init__(self, text_val):
        self.text_val = text_val
    def __eq__(self, other):
        return hasattr(other, "text") and other.text == self.text_val


def test_get_active_user_query_param():
    """REVIEW_1 GAP-1: generic ?token= auth is OFF by default (tokens leak into
    logs/proxies/history). It only works when ALLOW_QUERY_TOKEN_AUTH=1."""
    import services.auth as auth_mod
    from services.auth import get_active_user
    from fastapi import HTTPException

    with patch("services.auth.decode_access_token") as mock_decode, \
         patch("services.auth._validate_token_version"):
        mock_decode.return_value = {"id": 99, "username": "test"}

        # Default: query token is rejected exactly like a missing header
        with pytest.raises(HTTPException) as exc:
            get_active_user(authorization=None, token="query-param-token")
        assert exc.value.status_code == 401

        # Opt-in flag restores the old fallback for legacy integrations
        with patch.object(auth_mod, "ALLOW_QUERY_TOKEN_AUTH", True):
            res = get_active_user(authorization=None, token="query-param-token")
            assert res == {"id": 99, "username": "test"}
            mock_decode.assert_called_with("query-param-token")

        # Missing both always raises
        with pytest.raises(HTTPException) as exc:
            get_active_user(authorization=None, token=None)
        assert exc.value.status_code == 401
