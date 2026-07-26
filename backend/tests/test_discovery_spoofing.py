"""
tests/test_discovery_spoofing.py
================================
Review finding S-2 — LAN discovery was a credential-harvesting surface.

THE BUG
-------
`routes/discovery.py` documented itself as safe because "the caller is always
the local backend itself (loopback or LAN, never an untrusted internet client)".
That was not true: `main_groq.py` mounts the router unconditionally, and the
local backend registers with the CLOUD every 30 minutes, so on the cloud
deployment the endpoint is internet-reachable and unauthenticated.

BizID is a *deliberately public* identifier — printed on invoices. So:

    attacker POSTs {biz_id: <victim's BizID>, ip: <attacker host>}
      → a cashier device calls GET /discover/<biz_id> BEFORE login
      → entries are returned newest-first, so the attacker is probed first
      → the cashier app sends the owner's credentials to the attacker

Structurally the same defect as F-1: a public identifier being treated as if it
conferred authority.

THE FIX: only addresses that are NOT globally routable may be registered, and
the number of entries per BizID is capped. A remote attacker cannot receive
traffic at an address that is unreachable from outside the victim's network, so
the remote attack is closed outright.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from routes import discovery

client = TestClient(app)

VICTIM_BIZID = "BIZ-VICTIM-S2"


@pytest.fixture(autouse=True)
def _clean_registry():
    discovery._REGISTRY.clear()
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    yield
    discovery._REGISTRY.clear()


# ── The predicate that carries the whole property ───────────────────────────

@pytest.mark.parametrize("addr", [
    "192.168.1.10", "10.0.0.5", "172.16.4.2", "172.31.255.254",
    "127.0.0.1", "localhost", "169.254.10.1", "100.64.0.1",
    "fd00::1", "[fd00::1]", "::1",
])
def test_lan_addresses_are_registrable(addr):
    assert discovery._is_private_address(addr) is True


@pytest.mark.parametrize("addr", [
    "8.8.8.8", "1.2.3.4", "51.15.99.4", "172.32.0.1",
    "2001:4860:4860::8888",
    # A hostname could resolve anywhere, so it cannot be verified — refuse.
    "evil.example.com", "attacker.com",
    # Junk must fail closed rather than fall through.
    "", "   ", "0x7f000001", "999.999.999.999", "192.168.1.1 8.8.8.8",
])
def test_publicly_routable_and_unverifiable_addresses_are_refused(addr):
    assert discovery._is_private_address(addr) is False


# ── The attack, end to end ──────────────────────────────────────────────────

def test_a_remote_host_cannot_advertise_itself_as_a_businesss_backend():
    """THE S-2 attack. Knowing a public BizID must not let anyone put their own
    address in front of that business's cashier devices."""
    resp = client.post("/discover/register", json={
        "biz_id": VICTIM_BIZID, "ip": "51.15.99.4", "port": 8001,
    })
    assert resp.status_code == 422, "a public IP was accepted for a public BizID"

    listed = client.get(f"/discover/{VICTIM_BIZID}").json()["backends"]
    assert all(b["ip"] != "51.15.99.4" for b in listed)


def test_a_hostname_cannot_be_registered():
    """A hostname is an indirection we cannot check — it may resolve anywhere."""
    resp = client.post("/discover/register", json={
        "biz_id": VICTIM_BIZID, "ip": "attacker.example.com", "port": 8001,
    })
    assert resp.status_code == 422


def test_a_genuine_lan_backend_still_registers_and_is_discoverable():
    """The fix must not break the feature it protects."""
    resp = client.post("/discover/register", json={
        "biz_id": VICTIM_BIZID, "ip": "192.168.1.50", "port": 8001,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "registered"

    backends = client.get(f"/discover/{VICTIM_BIZID}").json()["backends"]
    assert len(backends) == 1
    assert backends[0]["ip"] == "192.168.1.50"
    assert backends[0]["url"] == "http://192.168.1.50:8001"


def test_re_registration_renews_rather_than_duplicating():
    for _ in range(3):
        client.post("/discover/register", json={
            "biz_id": VICTIM_BIZID, "ip": "192.168.1.50", "port": 8001})
    assert len(client.get(f"/discover/{VICTIM_BIZID}").json()["backends"]) == 1


def test_the_entry_list_cannot_be_flooded_with_decoys():
    """Even from inside the LAN, an attacker must not be able to bury the real
    backend under decoys — the client probes the list newest-first."""
    accepted = 0
    for i in range(1, 40):
        r = client.post("/discover/register", json={
            "biz_id": VICTIM_BIZID, "ip": f"192.168.1.{i}", "port": 8001})
        if r.status_code == 200:
            accepted += 1
        else:
            assert r.status_code == 429
    assert accepted == discovery._MAX_ENTRIES_PER_BIZ
    assert len(client.get(f"/discover/{VICTIM_BIZID}").json()["backends"]) \
        == discovery._MAX_ENTRIES_PER_BIZ


def test_an_invalid_port_is_refused():
    for port in (0, -1, 70000):
        r = client.post("/discover/register", json={
            "biz_id": VICTIM_BIZID, "ip": "192.168.1.50", "port": port})
        assert r.status_code in (422, 429), f"port {port} accepted"


def test_discovery_lookup_stays_public():
    """Deliberately unauthenticated — a cashier device has no token before login.
    Safe now only because the payload can no longer point off-LAN."""
    assert client.get(f"/discover/{VICTIM_BIZID}").status_code == 200
