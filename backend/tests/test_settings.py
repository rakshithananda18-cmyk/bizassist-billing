"""
tests/test_settings.py
======================
Integration tests for the App Settings API endpoints:
  GET  /settings  — returns merged default+saved settings
  PUT  /settings  — persists a partial or full settings update

Coverage:
  1. GET returns all expected top-level sections for a fresh user
  2. GET returns sensible defaults (no garbled/null sections)
  3. PUT updates a single section without clobbering others
  4. PUT updates multiple sections in one call
  5. PUT deep-merges within a section (partial update)
  6. Saved settings persist across separate GET calls
  7. Unauthenticated GET returns 401
  8. Unauthenticated PUT returns 401
  9. Invalid section key in PUT is silently ignored (no 500)
  10. PUT with empty body returns current settings unchanged
"""
import os
import sys
import logging

os.environ.setdefault("JWT_SECRET",    "test-secret-for-settings-tests-abcdef123")
os.environ.setdefault("DATABASE_URL",  "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY",  "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from app import app
from database.db import SessionLocal
from database.models import Base, User
from services.auth import hash_password, create_access_token

logger = logging.getLogger("bizassist.test.settings")

# ─── Constants ────────────────────────────────────────────────────────────────
TEST_USER_ID   = 88800
TEST_USERNAME  = "settings_test_user"
TEST_PASSWORD  = "TestPass1!"
TEST_BIZ_NAME  = "Settings Test Biz"

EXPECTED_SECTIONS = {"general", "transactions", "inventory", "print", "labels"}


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    """Create all tables (idempotent) before the module runs."""
    logger.debug("[Settings Test] Ensuring DB schema is up-to-date")
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


@pytest.fixture(scope="module")
def test_user():
    """Create a test user for the module, yield it, then clean up."""
    logger.debug("[Settings Test] Creating test user: %s", TEST_USERNAME)
    db = SessionLocal()
    try:
        # Remove any stale data from previous runs
        existing = db.query(User).filter(User.username == TEST_USERNAME).first()
        if existing:
            logger.debug("[Settings Test] Removing stale user id=%s", existing.id)
            db.delete(existing)
            db.commit()

        user = User(
            id=TEST_USER_ID,
            username=TEST_USERNAME,
            password=hash_password(TEST_PASSWORD),
            business_name=TEST_BIZ_NAME,
            role="enterprise",
            settings=None,          # start fresh — no saved settings
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("[Settings Test] Created user id=%s username=%s", user.id, user.username)
        yield user
    finally:
        db.query(User).filter(User.username == TEST_USERNAME).delete()
        db.commit()
        db.close()
        logger.debug("[Settings Test] Test user cleaned up")


@pytest.fixture(scope="module")
def auth_headers(test_user):
    """Return Authorization header dict with a valid JWT for the test user."""
    token = create_access_token({
        "id":            test_user.id,
        "username":      test_user.username,
        "business_name": test_user.business_name,
        "role":          test_user.role,
    })
    logger.debug("[Settings Test] JWT token created for user id=%s", test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client():
    """Return a synchronous TestClient wrapping the FastAPI app."""
    logger.debug("[Settings Test] Initialising TestClient")
    return TestClient(app)


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestGetSettings:
    """GET /settings endpoint tests."""

    def test_get_returns_200(self, client, auth_headers):
        """Happy-path GET returns HTTP 200."""
        logger.debug("[Settings Test] test_get_returns_200")
        res = client.get("/settings", headers=auth_headers)
        logger.debug("[Settings Test] GET /settings status=%s", res.status_code)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_get_returns_all_sections(self, client, auth_headers):
        """Response must contain all five top-level setting sections."""
        logger.debug("[Settings Test] test_get_returns_all_sections")
        res = client.get("/settings", headers=auth_headers)
        data = res.json()
        logger.debug("[Settings Test] sections returned: %s", list(data.keys()))
        for section in EXPECTED_SECTIONS:
            assert section in data, f"Missing section '{section}' in GET /settings response"

    def test_get_general_has_defaults(self, client, auth_headers):
        """General section must include known default keys with sensible values."""
        logger.debug("[Settings Test] test_get_general_has_defaults")
        res = client.get("/settings", headers=auth_headers)
        general = res.json()["general"]
        logger.debug("[Settings Test] general section: %s", general)
        assert "passcode_lock"           in general
        assert "privacy_mode"            in general
        assert "auto_backup"             in general
        assert "date_format"             in general
        assert "quantity_decimal_places" in general
        assert "amount_decimal_places"   in general
        assert general["passcode_lock"]  is False,  "Default passcode_lock should be False"
        assert general["privacy_mode"]   is False,  "Default privacy_mode should be False"
        assert general["date_format"]    == "DD/MM/YYYY"

    def test_get_print_has_default_theme_color(self, client, auth_headers):
        """Print section must include a valid hex theme_color default."""
        logger.debug("[Settings Test] test_get_print_has_default_theme_color")
        res = client.get("/settings", headers=auth_headers)
        pr = res.json()["print"]
        logger.debug("[Settings Test] print.theme_color=%s", pr.get("theme_color"))
        assert "theme_color" in pr
        assert pr["theme_color"].startswith("#"), "theme_color must be a hex colour string"

    def test_get_labels_has_sale_key(self, client, auth_headers):
        """Labels section must contain at least the 'sale' custom label."""
        logger.debug("[Settings Test] test_get_labels_has_sale_key")
        res = client.get("/settings", headers=auth_headers)
        labels = res.json()["labels"]
        logger.debug("[Settings Test] labels keys: %s", list(labels.keys()))
        assert "sale" in labels

    def test_get_unauthenticated_returns_401(self, client):
        """GET /settings without a token must return 401."""
        logger.debug("[Settings Test] test_get_unauthenticated_returns_401")
        res = client.get("/settings")
        logger.debug("[Settings Test] Unauthenticated GET /settings status=%s", res.status_code)
        assert res.status_code == 401


class TestPutSettings:
    """PUT /settings endpoint tests."""

    def test_put_unauthenticated_returns_401(self, client):
        """PUT /settings without a token must return 401."""
        logger.debug("[Settings Test] test_put_unauthenticated_returns_401")
        res = client.put("/settings", json={})
        logger.debug("[Settings Test] Unauthenticated PUT /settings status=%s", res.status_code)
        assert res.status_code == 401

    def test_put_empty_body_returns_200(self, client, auth_headers):
        """PUT with empty body is valid — returns current settings unchanged."""
        logger.debug("[Settings Test] test_put_empty_body_returns_200")
        res = client.put("/settings", json={}, headers=auth_headers)
        logger.debug("[Settings Test] Empty PUT /settings status=%s", res.status_code)
        assert res.status_code == 200
        data = res.json()
        for section in EXPECTED_SECTIONS:
            assert section in data

    def test_put_updates_single_section(self, client, auth_headers):
        """PUT with a single section only changes that section."""
        logger.debug("[Settings Test] test_put_updates_single_section")
        payload = {"general": {"privacy_mode": True, "auto_backup": True}}
        res = client.put("/settings", json=payload, headers=auth_headers)
        logger.debug("[Settings Test] PUT /settings single-section status=%s", res.status_code)
        assert res.status_code == 200
        data = res.json()
        assert data["general"]["privacy_mode"] is True,  "privacy_mode should be True after PUT"
        assert data["general"]["auto_backup"]  is True,  "auto_backup should be True after PUT"
        # Other sections should still be present and intact
        assert "transactions" in data
        assert "inventory"    in data

    def test_put_change_persists_on_next_get(self, client, auth_headers):
        """A value changed via PUT must be returned on the next GET."""
        logger.debug("[Settings Test] test_put_change_persists_on_next_get")
        unique_color = "#ABCDEF"
        client.put("/settings", json={"print": {"theme_color": unique_color}}, headers=auth_headers)
        res = client.get("/settings", headers=auth_headers)
        logger.debug("[Settings Test] GET after PUT theme_color=%s", res.json()["print"]["theme_color"])
        assert res.json()["print"]["theme_color"] == unique_color, \
            "theme_color change must persist across requests"

    def test_put_partial_section_update_preserves_other_keys(self, client, auth_headers):
        """Partial section update must not wipe keys not included in payload."""
        logger.debug("[Settings Test] test_put_partial_section_update_preserves_other_keys")
        # Get current state of transactions
        before = client.get("/settings", headers=auth_headers).json()["transactions"]
        # Patch only one key
        client.put("/settings", json={"transactions": {"prevent_negative_stock": True}}, headers=auth_headers)
        after = client.get("/settings", headers=auth_headers).json()["transactions"]
        logger.debug("[Settings Test] transactions before: %s | after: %s", before, after)
        assert after["prevent_negative_stock"] is True
        # estimate_enabled must remain unchanged
        assert after["estimate_enabled"] == before["estimate_enabled"], \
            "estimate_enabled must be preserved during partial update"

    def test_put_multi_section_update(self, client, auth_headers):
        """PUT can update multiple sections at once."""
        logger.debug("[Settings Test] test_put_multi_section_update")
        payload = {
            "general":      {"passcode_lock": True},
            "inventory":    {"wholesale_price": True, "serial_tracking": True},
            "labels":       {"sale": "Tax Invoice"},
        }
        res = client.put("/settings", json=payload, headers=auth_headers)
        logger.debug("[Settings Test] Multi-section PUT /settings status=%s", res.status_code)
        assert res.status_code == 200
        data = res.json()
        assert data["general"]["passcode_lock"]       is True
        assert data["inventory"]["wholesale_price"]   is True
        assert data["inventory"]["serial_tracking"]   is True
        assert data["labels"]["sale"]                 == "Tax Invoice"

    def test_put_unknown_section_key_ignored(self, client, auth_headers):
        """A payload with an unrecognised top-level key must not cause a 500."""
        logger.debug("[Settings Test] test_put_unknown_section_key_ignored")
        payload = {"nonexistent_section": {"foo": "bar"}}
        res = client.put("/settings", json=payload, headers=auth_headers)
        logger.debug("[Settings Test] Unknown section PUT /settings status=%s", res.status_code)
        # Should still return 200 (the unknown section is silently ignored)
        assert res.status_code == 200

    def test_put_label_rename_persists(self, client, auth_headers):
        """Renamed transaction label must persist and appear in subsequent GETs."""
        logger.debug("[Settings Test] test_put_label_rename_persists")
        client.put("/settings", json={"labels": {"purchase": "Supplier Bill"}}, headers=auth_headers)
        res = client.get("/settings", headers=auth_headers)
        logger.debug("[Settings Test] GET after label rename: purchase=%s", res.json()["labels"].get("purchase"))
        assert res.json()["labels"]["purchase"] == "Supplier Bill"

    def test_put_round_off_type_enum(self, client, auth_headers):
        """round_off_type must accept valid enum values: nearest, ceil, floor."""
        logger.debug("[Settings Test] test_put_round_off_type_enum")
        for val in ("nearest", "ceil", "floor"):
            payload = {"transactions": {"round_off_type": val}}
            res = client.put("/settings", json=payload, headers=auth_headers)
            assert res.status_code == 200, f"round_off_type '{val}' should be accepted"
            saved = res.json()["transactions"]["round_off_type"]
            logger.debug("[Settings Test] round_off_type=%s saved as %s", val, saved)
            assert saved == val
