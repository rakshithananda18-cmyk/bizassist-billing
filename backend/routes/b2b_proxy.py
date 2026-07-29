"""
routes/b2b_proxy.py
===================
Makes the LOCAL backend the B2B client of the cloud, instead of the browser.

── The problem ──────────────────────────────────────────────────────────────
B2B is the one domain whose rows have TWO owners. A connection or an order is
shared between a buyer and a seller who normally live in two different
databases, so it has exactly one authoritative home: the cloud. Everything else
in the product is single-tenant and works fine against whichever backend the
device happens to be talking to.

The tempting shortcut — have the browser call the cloud directly for B2B — is
WRONG, and we shipped it once and had to revert it. A session token is issued
by, and only valid on, the backend the user logged into. A desktop install logs
into the local backend, so its token carries a LOCAL user id; handing that to
the cloud makes the cloud resolve `current_user["id"]` against ITS OWN users
table, where the same integer belongs to a DIFFERENT business. One tenant sees
another's data. Tokens are not portable across backends. Full stop.

── The fix ──────────────────────────────────────────────────────────────────
The local backend already holds a CLOUD-ISSUED token for its own business — the
sync worker uses it every cycle (provisioned at login via
`POST /api/sync/cloud-token`). So the local backend is the one party that can
legitimately speak to the cloud on this business's behalf.

This middleware therefore:
  1. accepts the browser's LOCAL token exactly as any other route does,
  2. re-authenticates upstream with the business's own CLOUD token,
  3. streams the cloud's response straight back.

The browser keeps talking to one backend with one token; the cloud only ever
sees a token it issued. No identity crosses a trust boundary.

── Fail-safe ────────────────────────────────────────────────────────────────
If the cloud is unreachable, or this business has no cloud token yet, the
request FALLS THROUGH to the local handler, which serves the read-only B2B
mirror (`database/sync_map.py::PULL_ONLY_TABLES`). Reads keep working offline;
writes fail loudly rather than being written somewhere they can never sync from.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from database.db import engine, get_db
from services.auth import restrict_cashier

logger = logging.getLogger("bizassist.b2b_proxy")

router = APIRouter(tags=["b2b"])

CLOUD_URL = (
    os.environ.get("CLOUD_API_URL")
    or os.environ.get("VITE_API_URL")
    or "https://rakshit-dev-bizassist.hf.space"
).rstrip("/")

# Paths whose truth lives in the cloud.
#
# `/connections/**` — connections, orders, and supplier catalogues. All of these
# describe or read ANOTHER business, which by definition is not in this DB.
#
# `/bizid/{code}` — looking UP another business. Also cloud-only.
#
# `/bizid` (no code) is deliberately EXCLUDED. That is the caller's OWN identity
# and it is answered correctly by the local DB. Proxying it is what made the
# workspace hang on "Loading…" when the cloud didn't know the local user id —
# there is no reason to leave the machine to learn your own BizID.
_PROXIED_PREFIXES = ("/connections",)


def _is_bizid_lookup(path: str) -> bool:
    """True for `/bizid/<code>`, false for the bare `/bizid`."""
    return path.startswith("/bizid/") and len(path) > len("/bizid/")

# Reads may safely fall back to the local mirror when the cloud is unreachable.
# Writes may NOT: a B2B write that lands only in the local DB is invisible to the
# counterparty forever, and pull-only sync will never carry it up.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Response headers we must not copy verbatim — httpx already decoded the body,
# so the upstream framing headers would misdescribe what we send on.
_SKIP_RESPONSE_HEADERS = {
    "content-length", "content-encoding", "transfer-encoding", "connection",
    "keep-alive", "server", "date",
}

_TIMEOUT = httpx.Timeout(12.0, connect=5.0)


def _is_local_backend() -> bool:
    """Only a LOCAL (SQLite) install proxies. On the cloud this middleware must
    be inert — otherwise the cloud would forward requests to itself forever."""
    try:
        return engine.dialect.name == "sqlite"
    except Exception:
        return False


# ── Fail-closed test-isolation guard (review finding S-5) ────────────────────
# `database/db.py` fails closed on the DATABASE_URL so fixtures cannot write into
# real data. Nothing fails closed on the NETWORK, and this middleware is the one
# place the backend speaks outward with a stored production credential — so the
# same incident reproduced one layer up.
#
# Measured, not hypothesised: the suite runs on SQLite, so `_is_local_backend()`
# is True; `_get_cloud_token` reads `backend/cloud_sync_tokens.json`, which is a
# real developer artefact and is NOT test-scoped; and the test businesses are
# freshly-created rows whose small integer ids collide with the ids in that map
# (the connection-approval fixtures land on business 7, which held a live token).
# The result was `tests/test_connection_approval.py` forwarding an authenticated
# `POST /connections/{id}/approve` to the production deployment.
#
# Two distinct defects, both closed here:
#   1. SAFETY — a test run could mutate another environment's B2B data.
#   2. INTEGRITY — worse, and the reason this is not merely hygiene. The
#      assertion "an unrelated business cannot approve" was being answered by
#      the production server's reply, not by the code under test. It passed
#      while the cloud was reachable and failed when it was not, and in neither
#      case did it exercise the local authorisation path it claims to cover. A
#      security test whose verdict comes from the network is not evidence.
#
# Opt-in escape hatch for a deliberate integration run against a throwaway
# cloud; it must be set explicitly and is never set by the suite.
_TEST_ENV_VARS = ("BIZASSIST_TESTING", "PYTEST_CURRENT_TEST")
_ALLOW_IN_TESTS = "BIZASSIST_ALLOW_TEST_CLOUD_PROXY"
_warned_inert = False


def _in_test_context() -> bool:
    """True when this process is a test run. `BIZASSIST_TESTING` is set by
    `tests/conftest.py` before any import; `PYTEST_CURRENT_TEST` is set by
    pytest itself per test, so an odd entry path that skips conftest is still
    covered."""
    return any(os.environ.get(v) for v in _TEST_ENV_VARS)


def _proxy_allowed() -> bool:
    """Refuse to leave the machine from inside a test run.

    Fail CLOSED: the default is "do not proxy", so a future test entry point
    inherits the safe behaviour without having to know this guard exists."""
    global _warned_inert
    if not _in_test_context():
        return True
    if os.environ.get(_ALLOW_IN_TESTS) == "1":
        return True
    if not _warned_inert:
        _warned_inert = True
        logger.warning(
            "[B2B_PROXY] test context detected — cloud proxy is INERT. B2B "
            "requests are served by the local handlers so the suite cannot "
            "reach, authenticate against, or mutate a real deployment. Set "
            "%s=1 to override for a deliberate integration run.",
            _ALLOW_IN_TESTS,
        )
    return False


def _should_proxy(path: str) -> bool:
    if _is_bizid_lookup(path):
        return True
    return any(path == p or path.startswith(p + "/") for p in _PROXIED_PREFIXES)


def _should_pull_after_b2b_write(method: str, status_code: int) -> bool:
    """Only a successful cloud B2B mutation needs an immediate local refresh."""
    return method.upper() not in _READ_METHODS and 200 <= int(status_code) < 300


def _pull_after_b2b_write(business_id: int) -> None:
    """Bring cloud-authored buyer documents into the local database promptly."""
    try:
        from services.sync_worker import trigger_sync_run
        trigger_sync_run(business_id, pull=True)
    except Exception as exc:
        # The cloud operation already succeeded.  Preserve that success and let
        # the normal scheduled pull retry the local projection if this task fails.
        logger.warning("[B2B_PROXY] post-write local pull failed for business %s: %s", business_id, exc)


def _business_id_from(request: Request) -> Optional[int]:
    """Resolve the calling business from the LOCAL bearer token.

    Deliberately tolerant: this is only used to look up which cloud token to
    use. Real authorisation still happens upstream, against the cloud token.
    """
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    try:
        from services.auth import decode_access_token
        payload = decode_access_token(auth.split(" ", 1)[1].strip())
    except Exception:
        return None
    # Staff logins carry the owner's id in parent_business_id; B2B is always
    # scoped to the OWNER business, never the individual cashier.
    bid = payload.get("parent_business_id") or payload.get("id") or payload.get("user_id")
    try:
        return int(bid) if bid is not None else None
    except (TypeError, ValueError):
        return None


async def b2b_cloud_proxy(request: Request, call_next):
    """HTTP middleware. Registered in main_groq before the routers matter —
    middleware runs ahead of routing, so ordering against include_router() is
    irrelevant."""
    path = request.url.path

    if not _should_proxy(path) or not _is_local_backend() or not _proxy_allowed():
        return await call_next(request)

    business_id = _business_id_from(request)
    if business_id is None:
        return await call_next(request)

    # Lazy import: sync_worker pulls in a lot, and this module is imported at
    # app start on the cloud too (where the proxy is inert).
    try:
        from services.sync_worker import _get_cloud_token
        cloud_token = _get_cloud_token(business_id)
    except Exception:
        cloud_token = None

    if not cloud_token:
        # No cloud identity for this business yet (never logged in online). Reads
        # serve the local mirror; writes will fail in the local handler, which is
        # the honest outcome — better than silently writing an orphan row.
        logger.debug("[B2B_PROXY] no cloud token for business %s — serving locally", business_id)
        return await call_next(request)

    body = await request.body()
    headers = {
        "Authorization": f"Bearer {cloud_token}",
        "Accept": request.headers.get("accept", "application/json"),
    }
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    # Preserve the caller's idempotency key so a retry upstream is still a no-op.
    if request.headers.get("x-client-request-id"):
        headers["X-Client-Request-Id"] = request.headers["x-client-request-id"]

    url = f"{CLOUD_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            upstream = await client.request(
                request.method,
                url,
                params=dict(request.query_params),
                content=body or None,
                headers=headers,
            )
    except Exception as exc:
        if request.method in _READ_METHODS:
            logger.info("[B2B_PROXY] cloud unreachable (%s) — falling back to the local mirror", exc)
            return await call_next(request)
        logger.warning("[B2B_PROXY] cloud unreachable for %s %s: %s", request.method, path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "B2B is offline. Connections and orders are shared with "
                          "another business, so they can only be changed while you're "
                          "online. Your existing B2B data is still visible."
            },
        )

    # A cloud-issued token that the cloud itself rejects means it has aged out.
    # Drop it so the next login re-provisions, and serve reads from the mirror
    # rather than bouncing the user out of a working local session.
    if upstream.status_code == 401:
        try:
            from services.sync_worker import _invalidate_cloud_token
            _invalidate_cloud_token(business_id)
        except Exception:
            pass
        if request.method in _READ_METHODS:
            logger.info("[B2B_PROXY] cloud token stale for business %s — serving the local mirror", business_id)
            return await call_next(request)

    passthrough = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _SKIP_RESPONSE_HEADERS
    }
    background = (
        BackgroundTask(_pull_after_b2b_write, business_id)
        if _should_pull_after_b2b_write(request.method, upstream.status_code)
        else None
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=passthrough,
        media_type=upstream.headers.get("content-type"),
        background=background,
    )


# ── Status ───────────────────────────────────────────────────────────────────

@router.get("/api/b2b/status")
def b2b_status(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Tell the UI which mode B2B is operating in, so it can say so.

    Without this the degraded state is INVISIBLE: a desktop install with no
    cloud token shows empty connection and order tabs, which reads as "I have no
    B2B relationships" rather than "I'm showing you a local copy and can't reach
    the network". Those are very different messages to an owner.

    `mode`:
      cloud    — this IS the cloud backend; everything is live and writable.
      proxied  — local install with a working cloud link; live and writable.
      mirror   — local install with no usable cloud token. Reads come from the
                 read-only cloud→local mirror and may be stale; writes will be
                 refused with 503 rather than written somewhere they can never
                 sync from.
    """
    if not _is_local_backend():
        return {
            "mode": "cloud",
            "cloud_linked": True,
            "writable": True,
            "reason": None,
        }

    business_id = None
    try:
        business_id = int(current_user.get("parent_business_id") or current_user.get("id"))
    except (TypeError, ValueError):
        pass

    token = None
    if business_id is not None:
        try:
            from services.sync_worker import _get_cloud_token
            token = _get_cloud_token(business_id)
        except Exception:
            token = None

    # `_proxy_allowed()` is part of the condition deliberately: holding a token is
    # not the same as being able to use it. Under the S-5 test guard the token
    # exists but the middleware is inert, and reporting "proxied · writable" then
    # would be this endpoint's own docstring failure mode — an invisible degraded
    # state described as healthy.
    if token and _proxy_allowed():
        return {
            "mode": "proxied",
            "cloud_linked": True,
            "writable": True,
            "reason": None,
        }

    return {
        "mode": "mirror",
        "cloud_linked": False,
        "writable": False,
        # Phrased for the owner, not the developer — this string is rendered.
        "reason": (
            "This device hasn't signed in to the network yet, so it's showing a "
            "saved copy of your B2B data. Sign in once while you're online to "
            "send requests, place orders or change anything here."
        ),
    }
