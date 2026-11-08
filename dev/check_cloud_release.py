"""Read-only public release checks; no sign-in or business-data writes.

Run from the repository root:
    python dev/check_cloud_release.py --report scratch/cloud-release-check.json

Public checks include cold-start readiness, CORS, TLS, redirects and build URLs.
Optional SHA-256 pairs verify operator-supplied configuration fingerprints;
--owner-token additionally verifies the Billing-to-Field-Team handoff.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import ssl
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_BILLING_API = "https://staterbill-api-1076771386585.asia-south1.run.app"
DEFAULT_FIELD_API = "https://bizassist-task-qyfsbxu27a-el.a.run.app"
DEFAULT_BILLING_WEB = "https://staterbill.com"
DEFAULT_FIELD_WEB = "https://task.staterbill.com"
DEFAULT_WWW_WEB = "https://www.staterbill.com"
DEFAULT_AI_WEB = "https://bizassist-dev-workspace-ai.vercel.app"
DEFAULT_ADMIN_WEB = "https://admin.staterbill.com"
DEFAULT_FORWARDER = "https://rakshit-dev-bizassist.hf.space"
MAX_BODY = 256 * 1024


def origin(value: str, *, allow_local: bool = False) -> str:
    """Accept explicit HTTP(S) origins only, never credentials or URL payloads."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port  # Validate malformed/out-of-range ports as well.
    except ValueError as exc:
        raise ValueError("URL must be a valid public HTTPS origin") from exc
    local_http = allow_local and parsed.scheme == "http" and parsed.hostname in {
        "localhost", "127.0.0.1", "::1",
    }
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or (parsed.scheme != "https" and not local_http)):
        raise ValueError("URL must be an HTTPS origin without credentials, path, query or fragment")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}" + (f":{port}" if port is not None else "")


class _SafeRedirects(HTTPRedirectHandler):
    def __init__(self, allow_local: bool):
        self.allow_local = allow_local
        self.redirects = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.hostname == "vercel.com" and (target.path.startswith("/login") or target.path.startswith("/sso-api")):
            raise URLError("vercel_sign_in")
        # Redirects may have paths, but must retain safe transports and cannot
        # introduce credentials or query payloads. No TLS validation bypass.
        clean_origin = f"{target.scheme}://{target.netloc}"
        origin(clean_origin, allow_local=self.allow_local)
        if target.query or target.fragment:
            raise URLError("unsafe_redirect")
        # Authenticated probes must never forward a bearer token to a redirect.
        if req is not None and req.get_header("Authorization"):
            raise URLError("unsafe_redirect")
        self.redirects.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str = ""
    redirects: tuple = ()


def request(url: str, *, timeout: float, method: str = "GET", headers=None,
            allow_local: bool = False, data=None) -> Response:
    req = Request(url, method=method, data=data, headers={"User-Agent": "BizAssist-Release-Check/2", **(headers or {})})
    redirects = _SafeRedirects(allow_local)
    opener = build_opener(redirects)
    try:
        response = opener.open(req, timeout=timeout)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("response_too_large")
        return Response(response.status, {k.lower(): v for k, v in response.headers.items()}, body,
                        response.geturl(), tuple(redirects.redirects))


def _failure_reason(exc, fallback):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError):
        return "tls_invalid"
    if str(reason) == "vercel_sign_in":
        return "vercel_sign_in"
    return fallback


def _result(name: str, url: str, passed: bool, reason: str, *, status=None, details=None):
    out = {"check": name, "url": url, "passed": passed, "reason": reason}
    if status is not None:
        out["http_status"] = status
    if details:
        out["details"] = details
    return out


def _health_details(data: dict, *, field: bool) -> dict:
    allowed = {"ok": (True, False), "db": ("postgresql", "sqlite"),
               "pro_required": (True, False), "billing_mirror": (True, False), "cloud_only": (True, False)} if field else {
        "status": ("ok", "error", "degraded"), "db": ("connected", "disconnected", "error"),
        "db_type": ("postgresql", "sqlite"), "mode": ("cloud", "local"),
    }
    # Even an expected key could contain an accidental connection string in
    # a broken deployment. Reports retain only recognized enum/bool values.
    return {key: value for key, values in allowed.items()
            if key in data and (value := data[key]) in values
            and type(value) is type(values[0])}


def health_check(name: str, base: str, *, timeout: float, require_field_flags: bool = True,
                 allow_local: bool = False):
    field = name == "field_health"
    url = base + ("/api/health" if field else "/health")
    try:
        response = request(url, timeout=timeout, allow_local=allow_local)
        if response.status != 200:
            return _result(name, url, False, "health_http_failure", status=response.status)
        data = json.loads(response.body)
        if not isinstance(data, dict):
            raise ValueError("invalid_health")
        details = _health_details(data, field=field)
        if field:
            passed = data.get("ok") is True and data.get("db") == "postgresql"
            if require_field_flags:
                passed = passed and data.get("pro_required") is True and data.get("billing_mirror") is False \
                    and data.get("cloud_only") is True
        else:
            passed = data.get("status") == "ok" and data.get("db") == "connected" \
                and data.get("db_type") == "postgresql" and data.get("mode") == "cloud"
        return _result(name, url, bool(passed), "ready" if passed else "health_contract_mismatch",
                       status=response.status, details=details)
    except (OSError, ValueError, URLError) as exc:
        return _result(name, url, False, _failure_reason(exc, "health_unavailable_or_invalid"))


def frontend_check(name: str, base: str, *, timeout: float, allow_local: bool = False):
    url = base + "/"
    try:
        response = request(url, timeout=timeout, allow_local=allow_local)
        sample = response.body.lstrip().lower()
        passed = response.status == 200 and "text/html" in response.headers.get("content-type", "").lower() \
            and (b"<!doctype html" in sample[:512] or b"<html" in sample[:512])
        return _result(name, url, passed, "available" if passed else "frontend_unavailable_or_not_html",
                       status=response.status)
    except (OSError, ValueError, URLError) as exc:
        return _result(name, url, False, _failure_reason(exc, "frontend_request_failed"))


def cors_check(name: str, base: str, web_origin: str, *, timeout: float, allow_local: bool = False):
    url = base + ("/api/auth/exchange" if name == "field_cors" else "/handoff-ticket")
    try:
        response = request(url, timeout=timeout, method="OPTIONS", headers={
            "Origin": web_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }, allow_local=allow_local)
        allowed_origin = response.headers.get("access-control-allow-origin", "")
        methods = {v.strip().upper() for v in response.headers.get("access-control-allow-methods", "").split(",")}
        allowed_headers = {v.strip().lower() for v in response.headers.get("access-control-allow-headers", "").split(",")}
        # Authorization is a CORS non-wildcard header: '*' alone is insufficient.
        header_ok = "authorization" in allowed_headers and ("content-type" in allowed_headers or "*" in allowed_headers)
        passed = 200 <= response.status < 300 and allowed_origin in {web_origin, "*"} \
            and ("POST" in methods or "*" in methods) and header_ok
        return _result(name, url, passed, "allowed" if passed else "cors_contract_mismatch",
                       status=response.status, details={"frontend_origin": web_origin,
                                                        "wildcard_origin": allowed_origin == "*"})
    except (OSError, ValueError, URLError) as exc:
        return _result(name, url, False, _failure_reason(exc, "cors_request_failed"))


def www_check(base: str, apex: str, *, timeout: float, allow_local: bool = False):
    url = base + "/"
    try:
        response = request(url, timeout=timeout, allow_local=allow_local)
        final = urlsplit(response.final_url)
        passed = bool(response.redirects) and response.status == 200 \
            and f"{final.scheme}://{final.netloc}" == apex and final.path in {"", "/"}
        return _result("www_redirect", url, passed, "redirected_to_apex" if passed else "www_redirect_missing",
                       status=response.status)
    except (OSError, ValueError, URLError) as exc:
        return _result("www_redirect", url, False, _failure_reason(exc, "www_request_failed"))


def build_info_check(name: str, base: str, expected: dict, *, timeout: float, allow_local: bool = False):
    url = base + "/build-info.json"
    try:
        response = request(url, timeout=timeout, allow_local=allow_local)
        if response.status != 200:
            return _result(name, url, False, "build_info_missing", status=response.status)
        data = json.loads(response.body)
        if not isinstance(data, dict) or not isinstance(data.get("urls"), dict) \
                or not isinstance(data.get("app"), str):
            raise ValueError("invalid_build_info")
        # Compare only the documented public URL keys. Never copy arbitrary
        # response values (or commits/environment contents) into the report.
        mismatches, unset = [], []
        for key, value in data["urls"].items():
            if key not in expected:
                mismatches.append("unexpected_url_key")
            elif value is None:
                unset.append(key)
            elif not isinstance(value, str) or value.rstrip("/") != expected[key]:
                mismatches.append(key)
        passed = not mismatches
        return _result(name, url, passed, "build_urls_match" if passed else "build_urls_mismatch",
                       status=response.status, details={"unset_using_defaults": unset, "mismatched_keys": mismatches})
    except (OSError, ValueError, URLError) as exc:
        return _result(name, url, False, _failure_reason(exc, "build_info_invalid"))


def forwarder_check(base: str, *, timeout: float, allow_local: bool = False):
    url = base + "/__forwarder"
    try:
        response = request(url, timeout=timeout, allow_local=allow_local)
        passed = response.status == 200
        return _result("forwarder_marker", url, passed, "forwarder_available" if passed else "forwarder_marker_missing",
                       status=response.status)
    except (OSError, ValueError, URLError) as exc:
        return _result("forwarder_marker", url, False, _failure_reason(exc, "forwarder_request_failed"))


def digest_pair(left, right):
    for value in (left, right):
        if value is not None and not re.fullmatch(r"[a-fA-F0-9]{64}", value):
            raise ValueError("SHA-256 fingerprints must contain exactly 64 hexadecimal characters")
    if left is None or right is None:
        return "not_checked"
    return "match" if left.lower() == right.lower() else "mismatch"


def handoff_check(billing_api, field_api, owner_token, *, timeout, allow_local=False):
    url = billing_api + "/handoff-ticket"
    try:
        minted = request(url, timeout=timeout, method="POST", allow_local=allow_local,
                         headers={"Authorization": f"Bearer {owner_token}", "Content-Type": "application/json"},
                         data=json.dumps({"purpose": "field_team"}).encode())
        if minted.status != 200:
            return _result("authenticated_handoff", url, False, "ticket_mint_failed", status=minted.status)
        ticket = json.loads(minted.body).get("ticket")
        if not isinstance(ticket, str) or not ticket:
            raise ValueError("invalid_ticket")
        exchange = request(field_api + "/api/auth/exchange", timeout=timeout, method="POST", allow_local=allow_local,
                           headers={"Content-Type": "application/json"}, data=json.dumps({"ticket": ticket}).encode())
        exchanged = json.loads(exchange.body) if exchange.status == 200 else {}
        passed = exchange.status == 200 and bool(exchanged.get("token") or exchanged.get("access_token"))
        return _result("authenticated_handoff", field_api + "/api/auth/exchange", passed,
                       "handoff_verified" if passed else "ticket_exchange_failed", status=exchange.status)
    except (OSError, ValueError, URLError, AttributeError) as exc:
        return _result("authenticated_handoff", url, False, _failure_reason(exc, "handoff_request_failed"))


def run_checks(*, billing_api: str, field_api: str, billing_web: str, field_web: str,
               timeout: float = 15, cold_start_timeout: float = 75, require_field_flags: bool = True,
               allow_local: bool = False, www_web=DEFAULT_WWW_WEB, ai_web=DEFAULT_AI_WEB,
               admin_web=DEFAULT_ADMIN_WEB, forwarder=DEFAULT_FORWARDER, owner_token=None,
               jwt_sha256_billing=None, jwt_sha256_field=None, db_sha256_billing=None, db_sha256_field=None):
    targets = [origin(value, allow_local=allow_local) for value in (
        billing_api, field_api, billing_web, field_web, www_web, ai_web, admin_web, forwarder)]
    billing_api, field_api, billing_web, field_web, www_web, ai_web, admin_web, forwarder = targets
    fingerprints = {"jwt": digest_pair(jwt_sha256_billing, jwt_sha256_field),
                    "database": digest_pair(db_sha256_billing, db_sha256_field)}
    common = {"timeout": timeout, "allow_local": allow_local}
    cold = {"timeout": cold_start_timeout, "allow_local": allow_local}
    expected = {"VITE_API_URL": billing_api, "VITE_FIELD_TEAM_URL": field_web,
                "VITE_AI_DASHBOARD_URL": ai_web, "VITE_BILLING_URL": billing_web,
                "VITE_PUBLIC_WEB_URL": billing_web}

    def billing_checks():
        first = health_check("billing_health", billing_api, **cold)
        return [first, cors_check("billing_cors", billing_api, billing_web, **common)]

    def field_checks():
        first = health_check("field_health", field_api, require_field_flags=True, **cold)
        return [first, cors_check("field_cors", field_api, field_web, **common)]

    def forwarder_checks():
        first = health_check("forwarder_health", forwarder, **cold)
        return [first, forwarder_check(forwarder, **common)]

    def frontend_checks(name, base, api):
        return [frontend_check(f"{name}_frontend", base, **common),
                build_info_check(f"{name}_build_info", base, {**expected, "VITE_API_URL": api}, **common)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fn) for fn in (billing_checks, field_checks, forwarder_checks)]
        futures += [executor.submit(frontend_checks, name, base, api) for name, base, api in (
            ("billing", billing_web, billing_api), ("field", field_web, field_api),
            ("ai", ai_web, billing_api), ("admin", admin_web, billing_api))]
        results = [item for future in futures for item in future.result()]
        results.append(executor.submit(www_check, www_web, billing_web, **common).result())
    not_verified = ["same_cloud_database", "matching_signing_secrets", "authenticated_handoff",
                    "pro_entitlement", "tenant_isolation", "collection_and_payment_cycle", "physical_printing"]
    if fingerprints["jwt"] != "not_checked":
        not_verified.remove("matching_signing_secrets")
    if fingerprints["database"] != "not_checked":
        not_verified.remove("same_cloud_database")
    if owner_token:
        results.append(handoff_check(billing_api, field_api, owner_token, **common))
        not_verified.remove("authenticated_handoff")
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(item["passed"] for item in results) and "mismatch" not in fingerprints.values(),
            "scope": "public_release_and_optional_authenticated_handoff", "not_verified": not_verified,
            "fingerprints": fingerprints, "require_field_flags": True, "checks": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--billing-api", default=DEFAULT_BILLING_API)
    parser.add_argument("--field-api", default=DEFAULT_FIELD_API)
    parser.add_argument("--billing-web", default=DEFAULT_BILLING_WEB)
    parser.add_argument("--field-web", default=DEFAULT_FIELD_WEB)
    parser.add_argument("--www-web", default=DEFAULT_WWW_WEB)
    parser.add_argument("--ai-web", default=DEFAULT_AI_WEB)
    parser.add_argument("--admin-web", default=DEFAULT_ADMIN_WEB)
    parser.add_argument("--forwarder", default=DEFAULT_FORWARDER)
    parser.add_argument("--timeout", type=float, default=15, help="Per-request timeout, 1–45 seconds")
    parser.add_argument("--cold-start-timeout", type=float, default=75, help="API readiness timeout in seconds (default: 75)")
    parser.add_argument("--require-field-flags", action="store_true", default=True,
                        help="Compatibility option: Field API cloud/Pro/mirror flags are always required")
    parser.add_argument("--owner-token", help="Optional owner bearer token for the authenticated Field Team handoff")
    for name in ("jwt-sha256-billing", "jwt-sha256-field", "db-sha256-billing", "db-sha256-field"):
        parser.add_argument("--" + name, help="Operator-computed SHA-256 fingerprint (never included in output)")
    parser.add_argument("--allow-local", action="store_true", help="Allow HTTP loopback origins for an explicit local fixture")
    parser.add_argument("--report", type=Path, help="Optional local JSON output file (contains no credentials or business data)")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 45:
        parser.error("--timeout must be between 1 and 45 seconds")
    if not 1 <= args.cold_start_timeout <= 300:
        parser.error("--cold-start-timeout must be between 1 and 300 seconds")
    try:
        report = run_checks(billing_api=args.billing_api, field_api=args.field_api,
                            billing_web=args.billing_web, field_web=args.field_web, timeout=args.timeout,
                            require_field_flags=args.require_field_flags, allow_local=args.allow_local,
                            cold_start_timeout=args.cold_start_timeout, www_web=args.www_web,
                            ai_web=args.ai_web, admin_web=args.admin_web, forwarder=args.forwarder,
                            owner_token=args.owner_token, jwt_sha256_billing=args.jwt_sha256_billing,
                            jwt_sha256_field=args.jwt_sha256_field, db_sha256_billing=args.db_sha256_billing,
                            db_sha256_field=args.db_sha256_field)
    except ValueError as exc:
        parser.error(str(exc))
    output = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
