"""Pure mocks: these tests cannot contact deployed APIs or write business data."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError


SPEC = importlib.util.spec_from_file_location("cloud_release_check", Path(__file__).resolve().parents[1] / "check_cloud_release.py")
check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check
SPEC.loader.exec_module(check)


def response(data, status=200, headers=None):
    return check.Response(status, headers or {"content-type": "application/json"}, json.dumps(data).encode())


class CloudReleaseCheckTests(unittest.TestCase):
    def test_url_rejects_credentials_queries_and_unsafe_transports(self):
        for value in ("https://user:secret@example.com", "https://example.com?token=secret",
                      "https://example.com/#secret", "https://example.com/api", "file:///tmp/x",
                      "http://example.com", "http://localhost:8001", "https://example.com:99999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check.origin(value)
        self.assertEqual(check.origin("https://EXAMPLE.com/"), "https://example.com")
        self.assertEqual(check.origin("http://127.0.0.1:8001", allow_local=True), "http://127.0.0.1:8001")

    def test_health_requires_connected_cloud_postgres(self):
        good = {"status": "ok", "db": "connected", "db_type": "postgresql", "mode": "cloud"}
        for change in ({}, {"db": "disconnected"}, {"db_type": "sqlite"}, {"mode": "local"}):
            with self.subTest(change=change), patch.object(check, "request", return_value=response({**good, **change})):
                result = check.health_check("billing_health", "https://api.example.com", timeout=1)
                self.assertEqual(result["passed"], not bool(change))

    def test_field_flags_are_optional_until_new_api_is_deployed(self):
        health = {"ok": True, "db": "postgresql"}
        with patch.object(check, "request", return_value=response(health)):
            self.assertTrue(check.health_check("field_health", "https://api.example.com", timeout=1)["passed"])
            self.assertFalse(check.health_check("field_health", "https://api.example.com", timeout=1,
                                               require_field_flags=True)["passed"])
        for change in ({}, {"pro_required": False}, {"billing_mirror": True}, {"cloud_only": False}):
            data = {**health, "pro_required": True, "billing_mirror": False, "cloud_only": True, **change}
            with self.subTest(change=change), patch.object(check, "request", return_value=response(data)):
                self.assertEqual(check.health_check("field_health", "https://api.example.com", timeout=1,
                                                    require_field_flags=True)["passed"], not bool(change))

    def test_failure_report_does_not_copy_arbitrary_bodies_or_exception_secrets(self):
        with patch.object(check, "request", return_value=response({"secret": "private", "ok": False, "db": "sqlite"})):
            result = check.health_check("field_health", "https://api.example.com", timeout=1)
            self.assertNotIn("private", json.dumps(result))
        with patch.object(check, "request", return_value=response({"ok": False, "db": "postgresql://secret:private@db"})):
            result = check.health_check("field_health", "https://api.example.com", timeout=1)
            self.assertNotIn("private", json.dumps(result))
        with patch.object(check, "request", side_effect=URLError("secret=private")):
            result = check.health_check("field_health", "https://api.example.com", timeout=1)
            self.assertNotIn("private", json.dumps(result))
            self.assertFalse(result["passed"])

    def test_cors_checks_origin_method_and_authorization_header(self):
        good = {"access-control-allow-origin": "https://web.example.com",
                "access-control-allow-methods": "GET, POST",
                "access-control-allow-headers": "Authorization, Content-Type"}
        for change in ({}, {"access-control-allow-origin": "https://wrong.example.com"},
                       {"access-control-allow-methods": "GET"}, {"access-control-allow-headers": "*"}):
            with self.subTest(change=change), patch.object(check, "request", return_value=response({}, headers={**good, **change})) as mock:
                result = check.cors_check("field_cors", "https://api.example.com", "https://web.example.com", timeout=1)
                self.assertEqual(result["passed"], not bool(change))
                self.assertEqual(mock.call_args.kwargs["method"], "OPTIONS")

    def test_frontend_requires_html_not_a_success_json_or_error_page(self):
        for status, body, content_type, expected in (
            (200, b"<!doctype html><html><div id='root'></div></html>", "text/html", True),
            (200, b"{}", "application/json", False),
            (503, b"<html>Unavailable</html>", "text/html", False),
        ):
            with self.subTest(status=status, body=body), patch.object(check, "request", return_value=check.Response(status, {"content-type": content_type}, body)):
                self.assertEqual(check.frontend_check("billing_frontend", "https://web.example.com", timeout=1)["passed"], expected)

    def test_full_run_uses_only_get_and_options_and_declares_limits(self):
        calls = []

        def fake_request(url, **kwargs):
            calls.append((url, kwargs.get("method", "GET")))
            if url.endswith("/api/health"):
                return response({"ok": True, "db": "postgresql"})
            if url.endswith("/health"):
                return response({"status": "ok", "db": "connected", "db_type": "postgresql", "mode": "cloud"})
            if kwargs.get("method") == "OPTIONS":
                return response({}, headers={"access-control-allow-origin": kwargs["headers"]["Origin"],
                                              "access-control-allow-methods": "POST",
                                              "access-control-allow-headers": "authorization, content-type"})
            return check.Response(200, {"content-type": "text/html"}, b"<!DOCTYPE html><html></html>")

        with patch.object(check, "request", side_effect=fake_request):
            result = check.run_checks(billing_api="https://billing-api.example.com", field_api="https://field-api.example.com",
                                      billing_web="https://billing.example.com", field_web="https://field.example.com")
        self.assertTrue(result["passed"])
        self.assertEqual(len(calls), 6)
        self.assertEqual({method for _, method in calls}, {"GET", "OPTIONS"})
        self.assertIn("same_cloud_database", result["not_verified"])
        self.assertIn("authenticated_handoff", result["not_verified"])

    def test_redirect_cannot_downgrade_or_inject_url_credentials(self):
        handler = check._SafeRedirects(False)
        for target in ("http://api.example.com/health", "https://user:secret@api.example.com/health",
                       "https://api.example.com/health?token=private"):
            with self.subTest(target=target), self.assertRaises((ValueError, URLError)):
                handler.redirect_request(None, None, 302, "Found", {}, target)


if __name__ == "__main__":
    unittest.main()
