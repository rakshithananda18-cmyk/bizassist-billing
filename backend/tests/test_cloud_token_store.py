"""C-13 items 2 and 3 — the cloud token store had one location per invocation.

`_TOKEN_FILE` was a bare relative path, so it resolved against whatever CWD the
process started in. The running app was fine by accident (packaged: server_entry
chdirs to BIZASSIST_DATA_DIR; dev: uvicorn starts in backend/), but
`_get_cloud_token` is also reached from `core/identity.py`, `core/api/staff.py`,
`routes/b2b_proxy.py` and two repair scripts — and a script imported from the
repo root created a SECOND, empty store at the root. Two consequences, both real:

  1. the root copy was not matched by .gitignore until item 1 was fixed, putting
     live cloud bearer JWTs one `git add -A` from a commit;
  2. quieter and worse for the repair runbook — reading an empty store made a
     provisioned device look unprovisioned, so a script run from the wrong
     directory said "no cloud token" instead of "wrong directory".

Item 3 is the same mistake one level down: ABSENT and UNREADABLE both returned
`{}` in silence, so a corrupt or permission-denied file was indistinguishable
from a device nobody had signed into. Rule 33 — "unreadable is not empty" — in
the file that holds the credential.
"""
import logging
import os
import sys

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-token-store-abc123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import sync_worker as SW      # noqa: E402


@pytest.fixture
def fresh_state(monkeypatch):
    """The 'log on change' latch is module state; reset it per test."""
    monkeypatch.setattr(SW, "_TOKEN_STORE_LAST_STATE", None)


# ── item 2: one location per install ─────────────────────────────────────────

def test_the_store_does_not_follow_the_working_directory(tmp_path, monkeypatch):
    """THE regression. Running from anywhere must not invent a new store."""
    monkeypatch.delenv("BIZASSIST_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    resolved = SW._resolve_token_file()

    assert tmp_path not in resolved.parents, (
        f"the token store followed CWD to {resolved} — this is the bug that put "
        "live bearer tokens in an unignored file at the repo root"
    )
    assert resolved.parent.name == "backend"
    assert resolved.is_absolute()


def test_the_packaged_data_dir_wins(tmp_path, monkeypatch):
    """Packaged installs keep the store beside the database, not beside the exe."""
    monkeypatch.setenv("BIZASSIST_DATA_DIR", str(tmp_path))
    assert SW._resolve_token_file() == tmp_path / "cloud_sync_tokens.json"


def test_the_path_is_stable_across_working_directories(tmp_path, monkeypatch):
    monkeypatch.delenv("BIZASSIST_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    first = SW._resolve_token_file()
    sub = tmp_path / "nested"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert SW._resolve_token_file() == first


# ── item 3: absent is not unreadable ─────────────────────────────────────────

def test_an_absent_store_says_absent(tmp_path, monkeypatch, caplog, fresh_state):
    monkeypatch.setattr(SW, "_TOKEN_FILE", tmp_path / "cloud_sync_tokens.json")
    caplog.set_level(logging.INFO, logger=SW.logger.name)

    assert SW._load_token_map() == {}

    assert "No cloud token store" in caplog.text
    assert str(tmp_path) in caplog.text, "the message must name the file it looked for"


def test_an_unreadable_store_says_unreadable_not_empty(tmp_path, monkeypatch, caplog, fresh_state):
    """The one that matters: a corrupt store must not read as 'never signed in'."""
    bad = tmp_path / "cloud_sync_tokens.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(SW, "_TOKEN_FILE", bad)
    caplog.set_level(logging.INFO, logger=SW.logger.name)

    assert SW._load_token_map() == {}, "still fails safe — no token is returned"

    assert "UNREADABLE" in caplog.text
    assert "No cloud token store" not in caplog.text, (
        "an unreadable store was reported as an absent one — the exact "
        "conflation this change exists to remove"
    )


def test_a_readable_store_reports_how_many_it_found(tmp_path, monkeypatch, caplog, fresh_state):
    good = tmp_path / "cloud_sync_tokens.json"
    good.write_text('{"7": "tok-a", "42": "tok-b"}', encoding="utf-8")
    monkeypatch.setattr(SW, "_TOKEN_FILE", good)
    caplog.set_level(logging.INFO, logger=SW.logger.name)

    assert SW._load_token_map() == {"7": "tok-a", "42": "tok-b"}
    assert "2 business(es) provisioned" in caplog.text


def test_the_state_is_logged_on_change_not_on_every_read(tmp_path, monkeypatch, caplog, fresh_state):
    """`_load_token_map` runs every sync tick (15 s). Logging unconditionally is
    four lines a minute for ever, which is how a real signal gets buried — the
    same failure the pull-auth backoff was added for."""
    monkeypatch.setattr(SW, "_TOKEN_FILE", tmp_path / "cloud_sync_tokens.json")
    caplog.set_level(logging.INFO, logger=SW.logger.name)

    SW._load_token_map()
    assert caplog.text, "the first read must say something"

    caplog.clear()
    SW._load_token_map()
    SW._load_token_map()
    assert caplog.text == "", "an unchanged state must stay quiet"


def test_token_store_path_is_what_load_actually_reads(tmp_path, monkeypatch):
    """Scripts print this to tell 'not provisioned' from 'looked in the wrong
    place'. It is worthless if it can disagree with the real read."""
    monkeypatch.setattr(SW, "_TOKEN_FILE", tmp_path / "cloud_sync_tokens.json")
    assert SW.token_store_path() == SW._TOKEN_FILE
