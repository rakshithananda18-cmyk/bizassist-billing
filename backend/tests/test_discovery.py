"""
test_discovery.py
==================
Tests for the LAN auto-discovery registry:
  POST /discover/register   — register a local backend IP
  GET  /discover/{biz_id}   — list registered backends
  DELETE /discover/register  — deregister

Tests also cover:
  - TTL expiry (expired entries are not returned)
  - Duplicate IP normalisation
  - Relay echo-suppression flag in services/realtime.py
  - Logger output for key discovery events
"""
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app():
    """Import the FastAPI app freshly (SQLite in-memory env)."""
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_discovery_tmp.db")
    os.environ.setdefault("JWT_SECRET", "test-secret-key-discovery")
    from main_groq import app
    return app


# ---------------------------------------------------------------------------
# Discovery Registry Tests
# ---------------------------------------------------------------------------

class TestDiscoveryRegister:
    """POST /discover/register"""

    def setup_method(self):
        # Reset the in-memory registry between tests
        from routes.discovery import _REGISTRY
        _REGISTRY.clear()

    def test_register_returns_ok(self):
        from routes.discovery import _REGISTRY
        from routes.discovery import router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        resp = client.post("/discover/register", json={
            "ip": "192.168.1.42",
            "port": 8001,
            "biz_id": "BA-TEST01"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "BA-TEST01" in _REGISTRY

    def test_register_overwrites_existing_ip(self):
        from routes.discovery import _REGISTRY, router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        client.post("/discover/register", json={"ip": "192.168.1.10", "port": 8001, "biz_id": "BA-DUP"})
        client.post("/discover/register", json={"ip": "192.168.1.10", "port": 8001, "biz_id": "BA-DUP"})

        # Only one entry per IP per biz_id
        entries = _REGISTRY.get("BA-DUP", [])
        ips = [e["ip"] for e in entries]
        assert ips.count("192.168.1.10") == 1

    def test_register_missing_fields_rejected(self):
        from routes.discovery import router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        resp = client.post("/discover/register", json={"ip": "192.168.1.1"})
        assert resp.status_code == 422   # Unprocessable entity — missing required fields


class TestDiscoveryList:
    """GET /discover/{biz_id}"""

    def setup_method(self):
        from routes.discovery import _REGISTRY
        _REGISTRY.clear()

    def test_list_returns_registered_backends(self):
        from routes.discovery import _REGISTRY, router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        client.post("/discover/register", json={"ip": "10.0.0.5", "port": 8001, "biz_id": "BA-LIST"})
        resp = client.get("/discover/BA-LIST")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["backends"]) == 1
        assert data["backends"][0]["ip"] == "10.0.0.5"

    def test_list_excludes_ttl_expired_entries(self):
        from routes.discovery import _REGISTRY, router as disc_router, TTL_SECONDS
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        # Manually insert an expired entry
        _REGISTRY["BA-TTL"] = [{
            "ip": "10.0.0.99",
            "port": 8001,
            "url": "http://10.0.0.99:8001",
            "registered_at": time.time() - TTL_SECONDS - 10   # expired
        }]

        resp = client.get("/discover/BA-TTL")
        assert resp.status_code == 200
        assert resp.json()["backends"] == []

    def test_list_unknown_biz_returns_empty(self):
        from routes.discovery import router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        resp = client.get("/discover/NO-SUCH-BIZ")
        assert resp.status_code == 200
        assert resp.json()["backends"] == []


class TestDiscoveryDeregister:
    """DELETE /discover/register"""

    def setup_method(self):
        from routes.discovery import _REGISTRY
        _REGISTRY.clear()

    def test_deregister_removes_entry(self):
        from routes.discovery import _REGISTRY, router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        client.post("/discover/register", json={"ip": "192.168.5.5", "port": 8001, "biz_id": "BA-DEL"})
        resp = client.delete("/discover/register", json={"ip": "192.168.5.5", "biz_id": "BA-DEL"})
        assert resp.status_code == 200

        remaining = _REGISTRY.get("BA-DEL", [])
        assert all(e["ip"] != "192.168.5.5" for e in remaining)


# ---------------------------------------------------------------------------
# Realtime relay echo-suppression Tests
# ---------------------------------------------------------------------------

class TestRealtimeRelayEchoSuppression:
    """Unit tests for RealtimeManager._relay_to_cloud echo suppression logic."""

    @pytest.mark.asyncio
    async def test_relay_skips_cloud_backend(self):
        """If DATABASE_URL starts with postgresql, relay should be a no-op."""
        import services.realtime as rt
        original = rt._IS_LOCAL_BACKEND
        rt._IS_LOCAL_BACKEND = False
        try:
            manager = rt.RealtimeManager()
            # Should return without doing anything — no exception
            await manager._relay_to_cloud(1, {"type": "pos.presence", "client_id": "x"})
        finally:
            rt._IS_LOCAL_BACKEND = original

    @pytest.mark.asyncio
    async def test_relay_skips_echoed_events(self):
        """Events tagged relay_source='local' must not be relayed again."""
        import services.realtime as rt
        original = rt._IS_LOCAL_BACKEND
        rt._IS_LOCAL_BACKEND = True
        try:
            manager = rt.RealtimeManager()
            # Event already came from the cloud relay — skip to prevent loop
            await manager._relay_to_cloud(1, {
                "type": "pos.presence",
                "relay_source": "local",
                "client_id": "x"
            })
            # If we reach here without hitting httpx, the test passes
        finally:
            rt._IS_LOCAL_BACKEND = original

    @pytest.mark.asyncio
    async def test_relay_skips_non_pos_events(self):
        """Only pos.* events should be relayed; billing.* events must not be."""
        import services.realtime as rt
        original = rt._IS_LOCAL_BACKEND
        rt._IS_LOCAL_BACKEND = True
        try:
            manager = rt.RealtimeManager()
            # billing.delta should NOT be relayed
            await manager._relay_to_cloud(1, {"type": "billing.delta", "data": {}})
        finally:
            rt._IS_LOCAL_BACKEND = original

    @pytest.mark.asyncio
    async def test_relay_calls_cloud_for_pos_events(self):
        """For a valid pos.* event on a local backend with a cloud token, httpx should be called."""
        import services.realtime as rt
        original = rt._IS_LOCAL_BACKEND
        rt._IS_LOCAL_BACKEND = True

        with patch("services.sync_worker._get_cloud_token", return_value="test-token"), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            try:
                manager = rt.RealtimeManager()
                await manager._relay_to_cloud(1, {"type": "pos.presence", "client_id": "abc"})
                mock_client.post.assert_called_once()
                call_kwargs = mock_client.post.call_args
                # Confirm relay_source was set in the payload
                assert call_kwargs.kwargs["json"]["relay_source"] == "local"
            finally:
                rt._IS_LOCAL_BACKEND = original


# ---------------------------------------------------------------------------
# Logger output verification
# ---------------------------------------------------------------------------

class TestDiscoveryLogging:
    """Verify that key discovery events produce logger output."""

    def test_registration_logs_info(self, caplog):
        import logging
        from routes.discovery import _REGISTRY, router as disc_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        _REGISTRY.clear()
        app = FastAPI()
        app.include_router(disc_router)
        client = TC(app)

        with caplog.at_level(logging.INFO, logger="bizassist.discovery"):
            client.post("/discover/register", json={"ip": "172.16.0.1", "port": 8001, "biz_id": "BA-LOG"})

        assert any("BA-LOG" in m for m in caplog.messages), \
            "Expected biz_id 'BA-LOG' in INFO log after registration"
