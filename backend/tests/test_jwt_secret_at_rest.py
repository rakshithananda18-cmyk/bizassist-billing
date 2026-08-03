"""C-1 §7 — the jwt-secret must not sit on disk in cleartext.

WHY THIS MATTERS MORE THAN IT LOOKS
-----------------------------------
`server_entry.py` used to write `<data_dir>/jwt-secret` in cleartext, right next
to `bizassist.db`. On a HYBRID install that secret signs tokens **the cloud
accepts** — so a copy of that one small file is a copy of the shop's cloud
identity. That is a worse leak than the price book the SQLCipher work (C-1) is
about, and it was the cheaper half to fix.

It is now wrapped with Windows DPAPI, which binds it to this Windows user on this
machine: a copied data directory, a pulled disk or a mailed support bundle yields
ciphertext. It defends against nothing running as that same user — see
`docs/DECISION_LOCAL_DB_ENCRYPTION_2026-08-03.md` §1 for the threat table.

WHY THE FLOW TESTS FAKE DPAPI
-----------------------------
DPAPI is a Windows API and CI runs on Linux. Testing the wrap/unwrap primitive
only on Windows would leave the part that actually deletes a secret file — the
migration — unexercised on the machine that runs the suite. So the primitive is
tested for real (Windows-only) and the FLOW is tested everywhere against a
reversible stand-in.
"""
import os
import sys

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import server_entry              # noqa: E402
from core import dpapi           # noqa: E402

_IS_WINDOWS = sys.platform == "win32"

_WRAP_PREFIX = b"FAKEWRAP:"


@pytest.fixture
def fake_dpapi(monkeypatch):
    """Reversible stand-in for DPAPI so the flow runs on any OS.

    Returns a dict whose `fail_unwrap` flag simulates the case that matters: a
    blob that cannot be unwrapped here, i.e. a different Windows profile or a
    data directory restored onto another machine."""
    state = {"fail_unwrap": False}

    def _protect(data: bytes):
        return _WRAP_PREFIX + data[::-1]

    def _unprotect(blob: bytes):
        if state["fail_unwrap"] or not blob.startswith(_WRAP_PREFIX):
            return None
        return blob[len(_WRAP_PREFIX):][::-1]

    monkeypatch.setattr(dpapi, "protect", _protect)
    monkeypatch.setattr(dpapi, "unprotect", _unprotect)
    monkeypatch.setattr(dpapi, "available", lambda: True)
    return state


def _resolve(tmp_path, monkeypatch) -> str:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    server_entry._ensure_jwt_secret(str(tmp_path))
    return os.environ["JWT_SECRET"]


# ── the primitive, for real ──────────────────────────────────────────────────

@pytest.mark.skipif(not _IS_WINDOWS, reason="DPAPI is a Windows API; the flow "
                                            "tests below cover the logic on CI")
def test_dpapi_actually_encrypts_and_round_trips():
    blob = dpapi.protect(b"top-secret-value")
    assert blob is not None
    assert b"top-secret-value" not in blob, "wrapped output still contains the secret"
    assert dpapi.unprotect(blob) == b"top-secret-value"
    # Garbage must be refused, not raise — callers branch on None.
    assert dpapi.unprotect(b"this is not a DPAPI blob") is None


# ── the flow, on every platform ──────────────────────────────────────────────

def test_a_fresh_install_writes_no_plaintext_secret(tmp_path, monkeypatch, fake_dpapi):
    """The whole point of C-1 §7."""
    secret = _resolve(tmp_path, monkeypatch)

    assert secret
    assert (tmp_path / "jwt-secret.dpapi").exists()
    assert not (tmp_path / "jwt-secret").exists()
    assert secret.encode() not in (tmp_path / "jwt-secret.dpapi").read_bytes()


def test_a_legacy_plaintext_secret_is_migrated_then_deleted(tmp_path, monkeypatch, fake_dpapi):
    """Existing installs already have the cleartext file. It must be adopted —
    changing the secret would sign every user out for no reason — and then the
    cleartext copy must actually go, or the migration achieved nothing."""
    (tmp_path / "jwt-secret").write_text("legacy-secret-value", encoding="utf-8")

    secret = _resolve(tmp_path, monkeypatch)

    assert secret == "legacy-secret-value", "migration must not change the secret"
    assert (tmp_path / "jwt-secret.dpapi").exists()
    assert not (tmp_path / "jwt-secret").exists(), "cleartext copy survived the migration"


def test_the_wrapped_secret_is_reused_across_restarts(tmp_path, monkeypatch, fake_dpapi):
    """Sessions survive a reboot — the reason the file exists at all."""
    first = _resolve(tmp_path, monkeypatch)
    second = _resolve(tmp_path, monkeypatch)
    assert first == second


def test_an_unwrappable_blob_mints_a_new_secret_and_keeps_a_readable_copy(
        tmp_path, monkeypatch, fake_dpapi):
    """A restored data dir on another machine cannot unwrap the blob.

    Two properties, and the second is the one that stops this being a footgun:
      1. it must not crash — the till has to boot;
      2. because the verification read-back also fails, the new secret must be
         left in a form this machine CAN read, rather than deleted on the way to
         an unopenable file.
    Losing this secret costs a re-login and nothing else, which is exactly why
    it is safe to wrap this way and a DATABASE key is not."""
    first = _resolve(tmp_path, monkeypatch)
    fake_dpapi["fail_unwrap"] = True

    second = _resolve(tmp_path, monkeypatch)

    assert second != first, "an unreadable secret must be replaced, not reused"
    assert (tmp_path / "jwt-secret").read_text(encoding="utf-8") == second


def test_without_dpapi_it_falls_back_to_plaintext(tmp_path, monkeypatch):
    """Linux/macOS dev and CI. Documented, not silent — a 'secret at rest' that
    is sometimes not is the kind of thing that gets believed."""
    monkeypatch.setattr(dpapi, "protect", lambda _d: None)
    monkeypatch.setattr(dpapi, "unprotect", lambda _b: None)
    monkeypatch.setattr(dpapi, "available", lambda: False)

    secret = _resolve(tmp_path, monkeypatch)

    assert (tmp_path / "jwt-secret").read_text(encoding="utf-8") == secret
    assert not (tmp_path / "jwt-secret.dpapi").exists()


def test_a_dotenv_secret_still_wins(tmp_path, monkeypatch, fake_dpapi):
    """Regression guard. Hybrid sync REQUIRES the cloud's shared secret from
    .env; if this ordering broke, every device would 401 against the cloud."""
    (tmp_path / ".env").write_text("JWT_SECRET=shared-with-cloud\n", encoding="utf-8")

    secret = _resolve(tmp_path, monkeypatch)

    assert secret == "shared-with-cloud"
    assert not (tmp_path / "jwt-secret.dpapi").exists(), (
        "the .env path must not mint or persist a local secret"
    )
