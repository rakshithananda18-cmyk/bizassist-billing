"""Read-only public release checks; no sign-in or business-data writes.

Run from the repository root:
    python dev/check_cloud_release.py --report scratch/cloud-release-check.json

Use --require-field-flags after deploying the current Field Team API. A pass
establishes public availability/CORS only, not matching databases, signing
secrets, tenant isolation, entitlement, or the authenticated collection cycle.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_BILLING_API = "https://rakshit-dev-bizassist.hf.space"
DEFAULT_FIELD_API = "https://bizassist-task-qyfsbxu27a-el.a.run.app"
DEFAULT_BILLING_WEB = "https://bizassist-billing.vercel.app"
DEFAULT_FIELD_WEB = "https://bizassist-task.vercel.app"
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

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        # Redirects may have paths, but must retain safe transports and cannot
        # introduce credentials or query payloads. No TLS validation bypass.
        clean_origin = f"{target.scheme}://{target.netloc}"
        origin(clean_origin, allow_local=self.allow_local)
        if target.query or target.fragment:
            raise URLError("unsafe_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


def request(url: str, *, timeout: float, method: str = "GET", headers=None,
            allow_local: bool = False) -> Response:
    req = Request(url, method=method, headers={"User-Agent": "BizAssist-Release-Check/1", **(headers or {})})
    opener = build_opener(_SafeRedirects(allow_local))
    try:
        response = opener.open(req, timeout=timeout)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("response_too_large")
        return Response(response.status, {k.lower(): v for k, v in response.headers.items()}, body)


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


def health_check(name: str, base: str, *, timeout: float, require_field_flags: bool = False,
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
    except (OSError, ValueError, URLError):
        return _result(name, url, False, "health_unavailable_or_invalid")


def frontend_check(name: str, base: str, *, timeout: float, allow_local: bool = False):
    url = base + "/"
    try:
        response = request(url, timeout=timeout, allow_local=allow_local)
        sample = response.body.lstrip().lower()
        passed = response.status == 200 and "text/html" in response.headers.get("content-type", "").lower() \
            and (b"<!doctype html" in sample[:512] or b"<html" in sample[:512])
        return _result(name, url, passed, "available" if passed else "frontend_unavailable_or_not_html",
                       status=response.status)
    except (OSError, ValueError, URLError):
        return _result(name, url, False, "frontend_request_failed")


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
    except (OSError, ValueError, URLError):
        return _result(name, url, False, "cors_request_failed")


def run_checks(*, billing_api: str, field_api: str, billing_web: str, field_web: str,
               timeout: float = 15, require_field_flags: bool = False, allow_local: bool = False):
    bases = [origin(value, allow_local=allow_local) for value in (billing_api, field_api, billing_web, field_web)]
    billing_api, field_api, billing_web, field_web = bases
    common = {"timeout": timeout, "allow_local": allow_local}
    jobs = [
        (health_check, ("billing_health", billing_api), common),
        (health_check, ("field_health", field_api), {**common, "require_field_flags": require_field_flags}),
        (frontend_check, ("billing_frontend", billing_web), common),
        (frontend_check, ("field_frontend", field_web), common),
        (cors_check, ("billing_cors", billing_api, billing_web), common),
        (cors_check, ("field_cors", field_api, field_web), common),
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fn, *args, **kwargs) for fn, args, kwargs in jobs]
        results = [future.result() for future in futures]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(item["passed"] for item in results),
        "scope": "public_availability_and_cors",
        "not_verified": ["same_cloud_database", "matching_signing_secrets", "authenticated_handoff",
                         "pro_entitlement", "tenant_isolation", "collection_and_payment_cycle", "physical_printing"],
        "require_field_flags": require_field_flags,
        "checks": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--billing-api", default=DEFAULT_BILLING_API)
    parser.add_argument("--field-api", default=DEFAULT_FIELD_API)
    parser.add_argument("--billing-web", default=DEFAULT_BILLING_WEB)
    parser.add_argument("--field-web", default=DEFAULT_FIELD_WEB)
    parser.add_argument("--timeout", type=float, default=15, help="Per-request timeout, 1–45 seconds")
    parser.add_argument("--require-field-flags", action="store_true", help="Require current Field API cloud/Pro/mirror flags")
    parser.add_argument("--allow-local", action="store_true", help="Allow HTTP loopback origins for an explicit local fixture")
    parser.add_argument("--report", type=Path, help="Optional local JSON output file (contains no credentials or business data)")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 45:
        parser.error("--timeout must be between 1 and 45 seconds")
    try:
        report = run_checks(billing_api=args.billing_api, field_api=args.field_api,
                            billing_web=args.billing_web, field_web=args.field_web, timeout=args.timeout,
                            require_field_flags=args.require_field_flags, allow_local=args.allow_local)
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
