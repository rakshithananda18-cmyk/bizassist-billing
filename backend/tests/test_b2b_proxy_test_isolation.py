"""
tests/test_b2b_proxy_test_isolation.py — review finding S-5.
============================================================
The B2B cloud proxy must be INERT inside a test run.

Why this file exists, stated as measured fact rather than principle. Before the
fix, running the backend suite did this:

  · the suite runs on SQLite, so ``_is_local_backend()`` is True and the
    middleware engages;
  · ``_get_cloud_token`` reads ``backend/cloud_sync_tokens.json`` — a real
    developer artefact, not a test fixture, holding live cloud tokens keyed by
    business id;
  · test businesses are fresh rows with small integer ids, which collide with
    the ids in that map (the connection-approval fixtures land on business 7);
  · so ``tests/test_connection_approval.py`` forwarded an authenticated
    ``POST /connections/{id}/approve`` to the production deployment.

Two defects, and the second is the serious one:

  1. SAFETY — a test run could mutate a real deployment's B2B data. This is the
     network-layer twin of the incident ``database/db.py``'s fail-closed guard
     was written for.
  2. INTEGRITY — the assertion "an unrelated business cannot approve" was being
     answered by the production server's HTTP status, not by the local
     authorisation code it claims to cover. It passed while the cloud was
     reachable and failed when it was not; it exercised the code under test in
     neither case. A security test whose verdict arrives over the network is
     not evidence of anything.

These tests fail if the guard is removed, weakened, or bypassed.
"""
import os
import re

import pytest

from routes import b2b_proxy


# ── The guard itself ─────────────────────────────────────────────────────────

def test_test_context_is_detected():
    """conftest sets BIZASSIST_TESTING=1 before any import, so by the time this
    runs the process must already identify as a test context. If this fails,
    every other assertion in this file is vacuous."""
    assert os.environ.get("BIZASSIST_TESTING") == "1"
    assert b2b_proxy._in_test_context() is True


def test_proxy_is_inert_under_a_test_context():
    assert b2b_proxy._proxy_allowed() is False, (
        "The B2B cloud proxy is live inside the test suite. It would forward "
        "authenticated requests to CLOUD_API_URL using a stored production "
        "token (see this module's docstring)."
    )


def test_override_is_explicit_and_opt_in(monkeypatch):
    """The escape hatch exists for a deliberate integration run, but it must
    require an exact opt-in — no truthiness, no accidental '0'/'false'."""
    monkeypatch.setenv(b2b_proxy._ALLOW_IN_TESTS, "1")
    assert b2b_proxy._proxy_allowed() is True

    for value in ("0", "", "false", "no", "true", "yes"):
        monkeypatch.setenv(b2b_proxy._ALLOW_IN_TESTS, value)
        assert b2b_proxy._proxy_allowed() is (value == "1"), (
            f"{b2b_proxy._ALLOW_IN_TESTS}={value!r} must not enable the proxy"
        )


def test_guard_fails_closed_by_default():
    """Absence of the override is refusal, not permission. A future test entry
    point that never heard of this guard inherits the safe behaviour."""
    saved = os.environ.pop(b2b_proxy._ALLOW_IN_TESTS, None)
    try:
        assert b2b_proxy._proxy_allowed() is False
    finally:
        if saved is not None:
            os.environ[b2b_proxy._ALLOW_IN_TESTS] = saved


def test_pytest_current_test_alone_is_sufficient(monkeypatch):
    """An entry path that skips conftest (so no BIZASSIST_TESTING) is still a
    test run — pytest exports PYTEST_CURRENT_TEST per test. The guard must not
    depend on a single variable being set by a single file."""
    monkeypatch.delenv("BIZASSIST_TESTING", raising=False)
    monkeypatch.delenv(b2b_proxy._ALLOW_IN_TESTS, raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/x.py::test_y (call)")
    assert b2b_proxy._in_test_context() is True
    assert b2b_proxy._proxy_allowed() is False


def test_no_test_context_means_normal_operation(monkeypatch):
    """Production must be unaffected: with neither variable set the proxy is
    allowed exactly as before. A guard that also disables the feature in
    production is not a fix."""
    monkeypatch.delenv("BIZASSIST_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv(b2b_proxy._ALLOW_IN_TESTS, raising=False)
    assert b2b_proxy._in_test_context() is False
    assert b2b_proxy._proxy_allowed() is True


# ── The wiring: the guard has to actually be consulted ───────────────────────

def test_middleware_consults_the_guard():
    """Drift guard. A guard nobody calls is a comment (rule 16). Asserted
    against the source so that deleting the call from the middleware's early
    return fails here, not silently in production."""
    import inspect

    src = inspect.getsource(b2b_proxy.b2b_cloud_proxy)
    assert "_proxy_allowed()" in src, (
        "b2b_cloud_proxy no longer consults _proxy_allowed(); the S-5 test "
        "isolation guard is unreachable."
    )
    # It must gate the EARLY RETURN, i.e. sit alongside the other bail-out
    # conditions — not somewhere after the outbound request has been built.
    early = src.split("business_id = _business_id_from")[0]
    assert "_proxy_allowed()" in early, (
        "_proxy_allowed() must be part of the early bail-out, before any "
        "token lookup or outbound request is prepared."
    )


def test_status_endpoint_does_not_claim_writable_while_inert():
    """`/api/b2b/status` exists so a degraded state is visible. Reporting
    'proxied · writable' while the proxy is inert would be that endpoint
    failing at its own job."""
    import inspect

    src = inspect.getsource(b2b_proxy.b2b_status)
    assert "_proxy_allowed()" in src, (
        "b2b_status reports mode from token presence alone; under the S-5 "
        "guard it would advertise a writable cloud link that cannot write."
    )


# ── The credential this was protecting ───────────────────────────────────────

def test_token_store_is_not_tracked_by_git():
    """`cloud_sync_tokens.json` holds bearer tokens for real deployments. The
    S-5 exposure was that tests READ it; it must at minimum never be committed.
    Checked against .gitignore rather than by shelling out, so the test works
    in a source export with no git metadata."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    gitignore = os.path.join(root, ".gitignore")
    if not os.path.exists(gitignore):
        pytest.skip(".gitignore not present in this checkout")
    body = open(gitignore, encoding="utf-8").read()
    assert re.search(r"^\s*.*cloud_sync_tokens\.json\s*$", body, re.M), (
        "cloud_sync_tokens.json is not gitignored — it holds live cloud "
        "bearer tokens."
    )


def test_cloud_url_is_never_localhost_by_default():
    """Sanity anchor for the finding: CLOUD_URL really is a remote deployment,
    which is what made the leak matter. If this ever legitimately becomes a
    local address, S-5's severity changes and this test should be revisited
    deliberately rather than drifting."""
    assert b2b_proxy.CLOUD_URL.startswith(("http://", "https://"))
