"""Pure mocks: these tests cannot contact deployed APIs or write business data."""
import importlib.util
import json
import ssl
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request
import pytest


SPEC = importlib.util.spec_from_file_location("cloud_release_check", Path(__file__).resolve().parents[2] / "dev" / "check_cloud_release.py")
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

    def test_field_flags_are_required_by_default(self):
        health = {"ok": True, "db": "postgresql"}
        with patch.object(check, "request", return_value=response(health)):
            self.assertFalse(check.health_check("field_health", "https://api.example.com", timeout=1)["passed"])
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
                return response({"ok": True, "db": "postgresql", "pro_required": True, "billing_mirror": False, "cloud_only": True})
            if url.endswith("/health"):
                return response({"status": "ok", "db": "connected", "db_type": "postgresql", "mode": "cloud"})
            if kwargs.get("method") == "OPTIONS":
                return response({}, headers={"access-control-allow-origin": kwargs["headers"]["Origin"],
                                              "access-control-allow-methods": "POST",
                                              "access-control-allow-headers": "authorization, content-type"})
            if url.endswith('/build-info.json'):
                return response({"app": "frontend-billing", "urls": {"VITE_API_URL": None}})
            if url.endswith('/__forwarder'):
                return response({"forwarder": True})
            if url.startswith(check.DEFAULT_WWW_WEB):
                return check.Response(200, {"content-type": "text/html"}, b"<!DOCTYPE html><html></html>",
                                      check.DEFAULT_APEX_WEB + "/", (check.DEFAULT_APEX_WEB + "/",))
            return check.Response(200, {"content-type": "text/html"}, b"<!DOCTYPE html><html></html>")

        with patch.object(check, "request", side_effect=fake_request):
            result = check.run_checks(billing_api="https://billing-api.example.com", field_api="https://field-api.example.com",
                                      billing_web="https://billing.example.com", field_web="https://field.example.com")
        self.assertTrue(result["passed"])
        self.assertEqual(len(calls), 15)
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


def healthy_request(url, **kwargs):
    if url.endswith('/api/health'):
        return response({'ok': True, 'db': 'postgresql', 'pro_required': True,
                         'billing_mirror': False, 'cloud_only': True})
    if url.endswith('/health'):
        return response({'status': 'ok', 'db': 'connected', 'db_type': 'postgresql', 'mode': 'cloud'})
    if kwargs.get('method') == 'OPTIONS':
        return response({}, headers={'access-control-allow-origin': kwargs['headers']['Origin'],
                                     'access-control-allow-methods': 'POST',
                                     'access-control-allow-headers': 'authorization,content-type'})
    if url.endswith('/build-info.json'):
        return response({'app': 'frontend-billing', 'urls': {'VITE_API_URL': None}})
    if url.endswith('/__forwarder'):
        return response({'forwarder': True})
    if url.startswith(check.DEFAULT_WWW_WEB):
        return check.Response(200, {'content-type': 'text/html'}, b'<!doctype html>',
                              check.DEFAULT_APEX_WEB + '/', (check.DEFAULT_APEX_WEB + '/',))
    return check.Response(200, {'content-type': 'text/html'}, b'<!doctype html>')


def run_default(**kwargs):
    return check.run_checks(billing_api=check.DEFAULT_BILLING_API, field_api=check.DEFAULT_FIELD_API,
                            billing_web=check.DEFAULT_BILLING_WEB, field_web=check.DEFAULT_FIELD_WEB, **kwargs)


def test_production_defaults_keep_only_the_forwarder_on_hugging_face():
    assert check.DEFAULT_BILLING_API == 'https://staterbill-api-1076771386585.asia-south1.run.app'
    assert check.DEFAULT_BILLING_WEB == 'https://app.staterbill.com'
    assert check.DEFAULT_FIELD_WEB == 'https://task.staterbill.com'
    assert check.DEFAULT_APEX_WEB == 'https://staterbill.com'
    for name in ('DEFAULT_BILLING_API', 'DEFAULT_FIELD_API', 'DEFAULT_BILLING_WEB',
                 'DEFAULT_FIELD_WEB', 'DEFAULT_APEX_WEB', 'DEFAULT_WWW_WEB', 'DEFAULT_AI_WEB', 'DEFAULT_ADMIN_WEB'):
        assert 'hf.space' not in getattr(check, name)
        assert 'bizassist-billing.vercel.app' not in getattr(check, name)


def test_each_api_wakes_before_its_other_probes(monkeypatch):
    calls = []
    def capture(url, **kwargs):
        calls.append((url, kwargs['timeout']))
        return healthy_request(url, **kwargs)
    monkeypatch.setattr(check, 'request', capture)
    report = run_default(timeout=9, cold_start_timeout=75)
    assert report['passed']
    for base, path in ((check.DEFAULT_BILLING_API, '/health'), (check.DEFAULT_FIELD_API, '/api/health'),
                       (check.DEFAULT_FORWARDER, '/health')):
        api_calls = [call for call in calls if call[0].startswith(base)]
        assert api_calls[0] == (base + path, 75)
        assert all(timeout == 9 for _, timeout in api_calls[1:])


@pytest.mark.parametrize('path', ['/login', '/sso-api', '/sso-api?next=private'])
def test_vercel_signin_redirect_is_reported_without_following(path, monkeypatch):
    handler = check._SafeRedirects(False)
    with pytest.raises(URLError, match='vercel_sign_in'):
        handler.redirect_request(Request('https://app.test/'), None, 302, 'Found', {}, 'https://vercel.com' + path)
    monkeypatch.setattr(check, 'request', lambda *args, **kwargs: (_ for _ in ()).throw(URLError('vercel_sign_in')))
    assert check.frontend_check('ai_frontend', check.DEFAULT_AI_WEB, timeout=1)['reason'] == 'vercel_sign_in'


@pytest.mark.parametrize('exc', [ssl.SSLCertVerificationError('private'), URLError(ssl.SSLError('private'))])
def test_tls_failures_have_a_safe_specific_reason(exc, monkeypatch):
    def fail(*args, **kwargs):
        raise exc
    monkeypatch.setattr(check, 'request', fail)
    result = check.frontend_check('billing_frontend', check.DEFAULT_BILLING_WEB, timeout=1)
    assert result['reason'] == 'tls_invalid'
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('redirects,final,passed', [
    [(), 'https://www.staterbill.com/', False],
    [('https://staterbill.com/',), 'https://staterbill.com/', True],
    [('https://unrelated.test/',), 'https://unrelated.test/', False],
])
def test_www_requires_a_redirect_to_the_apex(redirects, final, passed, monkeypatch):
    monkeypatch.setattr(check, 'request', lambda *args, **kwargs: check.Response(200, {}, b'', final, redirects))
    assert check.www_check(check.DEFAULT_WWW_WEB, check.DEFAULT_APEX_WEB, timeout=1)['passed'] is passed


@pytest.mark.parametrize('status,body,passed', [
    (404, b'{}', False), (200, b'not json', False),
    (200, json.dumps({'app': 'frontend-billing', 'urls': {'VITE_API_URL': 'https://retired.hf.space'}}).encode(), False),
    (200, json.dumps({'app': 'frontend-billing', 'urls': {'VITE_API_URL': check.DEFAULT_BILLING_API}}).encode(), True),
    (200, json.dumps({'app': 'frontend-billing', 'urls': {'VITE_API_URL': None}}).encode(), True),
])
def test_build_info_validation(status, body, passed, monkeypatch):
    monkeypatch.setattr(check, 'request', lambda *args, **kwargs: check.Response(status, {}, body))
    result = check.build_info_check('billing_build_info', check.DEFAULT_BILLING_WEB,
                                     {'VITE_API_URL': check.DEFAULT_BILLING_API}, timeout=1)
    assert result['passed'] is passed
    assert 'retired.hf.space' not in json.dumps(result)


@pytest.mark.parametrize('left,right,expected', [('a' * 64, 'A' * 64, 'match'),
                                                 ('a' * 64, 'b' * 64, 'mismatch'),
                                                 (None, None, 'not_checked'), ('a' * 64, None, 'not_checked')])
def test_fingerprints_only_return_the_pair_result(left, right, expected):
    assert check.digest_pair(left, right) == expected


def test_no_fingerprint_or_auth_material_reaches_report_or_stdout(monkeypatch, tmp_path, capsys):
    owner_token, ticket = 'private-owner-token', 'private-handoff-ticket'
    def fake(url, **kwargs):
        if url.endswith('/handoff-ticket') and kwargs.get('method') == 'POST':
            assert kwargs['headers']['Authorization'] == f'Bearer {owner_token}'
            assert json.loads(kwargs['data']) == {'purpose': 'field_team'}
            return response({'ticket': ticket, 'JWT_SECRET': 'test-secret-do-not-print'})
        if url.endswith('/api/auth/exchange') and kwargs.get('method') == 'POST':
            assert json.loads(kwargs['data']) == {'ticket': ticket}
            return response({'token': 'private-field-token'})
        return healthy_request(url, **kwargs)
    monkeypatch.setattr(check, 'request', fake)
    target = tmp_path / 'report.json'
    assert check.main(['--report', str(target), '--owner-token', owner_token,
                       '--jwt-sha256-billing', 'a' * 64, '--jwt-sha256-field', 'a' * 64,
                       '--db-sha256-billing', 'b' * 64, '--db-sha256-field', 'b' * 64]) == 0
    output = capsys.readouterr().out + target.read_text()
    for secret in (owner_token, ticket, 'private-field-token', 'test-secret-do-not-print', 'a' * 64, 'b' * 64):
        assert secret not in output
    report = json.loads(target.read_text())
    assert report['fingerprints'] == {'jwt': 'match', 'database': 'match'}
    assert 'authenticated_handoff' not in report['not_verified']


@pytest.mark.parametrize('value', ['short', 'g' * 64, 'secret=private'])
def test_malformed_fingerprint_is_a_safe_usage_error(value, capsys):
    with pytest.raises(SystemExit) as exc:
        check.main(['--jwt-sha256-billing', value])
    assert exc.value.code == 2
    assert value not in capsys.readouterr().err
