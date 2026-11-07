"""Boundary and concurrent-consumption tests use real signatures without network calls."""
import base64
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import config, security


def ticket(exp, claims, key=None):
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    signature = hmac.new((key or config.JWT_SECRET).encode(), f"sse|{encoded}|{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{encoded}.{signature}"


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    security._USED_TICKETS.clear()
    monkeypatch.setattr(security.time, "time", lambda: 1000)
    yield
    security._USED_TICKETS.clear()


@pytest.mark.parametrize("exp,iat,aud,reason", [
    (985, 895, "field_team", None),  # exact end of leeway
    (984, 894, "field_team", "expired"),
    (1090, 1000, "field_team", None),
    (1120, 1000, "field_team", None),
    (1121, 1000, "field_team", "lifetime"),
    (1090, 1000, "ai_dashboard", "audience"),
    (1090, "1000", "field_team", "malformed"),
    (1090, 1000, None, None),  # transition ticket
])
def test_ticket_boundaries(exp, iat, aud, reason):
    claims = {"iat": iat}
    if aud is not None:
        claims["aud"] = aud
    value = ticket(exp, claims)
    if reason:
        with pytest.raises(security.TicketRefused) as refused:
            security.redeem_billing_ticket(value)
        assert refused.value.reason == reason
    else:
        assert security.redeem_billing_ticket(value) == claims


def test_bad_signature_is_not_reported_as_expiry():
    with pytest.raises(security.TicketRefused) as refused:
        security.redeem_billing_ticket(ticket(100, {}, key="other-secret"))
    assert refused.value.reason == "bad_signature"


def test_concurrent_exchange_consumes_ticket_once():
    value = ticket(1090, {"iat": 1000, "aud": "field_team"})
    def consume(_):
        try:
            security.redeem_billing_ticket(value)
            return "accepted"
        except security.TicketRefused as refused:
            return refused.reason
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(consume, range(16)))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("already_used") == 15
