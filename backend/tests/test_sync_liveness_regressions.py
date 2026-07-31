"""
tests/test_sync_liveness_regressions.py — three ways sync stopped without erroring
=================================================================================

Every defect pinned here shares one shape: **sync stops, and nothing reports it.**
No exception, no ERROR line, no failed status — just a device that quietly
converges on nothing. That is why each of them survived a full green suite, and
why each gets a gate rather than a comment.

────────────────────────────────────────────────────────────────────────────────
A. hosting_mode is authored by the LOCAL install; the cloud only replicates it
────────────────────────────────────────────────────────────────────────────────
`general.hosting_mode` describes how the owner's local install is hosted. It
lives on `users.settings`, and `users` is in `_SYNC_TABLES` — so it is an
ACCOUNT-scoped field that LWW-syncs to every device.

A web session cannot observe a local backend. It correctly derives 'cloud' for
itself, and the frontend then PUT that answer onto the shared account field:

    owner opens the web dashboard
      -> web derives 'cloud' (true of that tab)
      -> PUT writes 'cloud' to the cloud `users` row, now the newest copy
      -> desktop pulls it over its own 'hybrid'
      -> sync_worker.run_hybrid_sync: `if hosting_mode != "hybrid": continue`
      -> desktop stops syncing AND `models._queue_change` stops queueing rows
      -> desktop's next Settings load re-derives 'hybrid' and writes it back,
         so the two devices flip the field on every page load

That is the identical outage `test_hosting_mode_gate.py` documents (42 rows
written, 0 queued, 0 logged), re-entered through the web door. `shouldPersistMode`
stops a compliant client from sending it; the guard tested here is what holds
when the client is an old build, a different frontend, or a direct API call —
which is precisely the population still running the version that caused it.

Only the DOWNGRADE direction is refused. `_provisionCloudSyncToken` PUTs
'hybrid' to the cloud on purpose, from a local install that knows it is hybrid,
so the Admin Console reports the truth.

────────────────────────────────────────────────────────────────────────────────
B. The parity audit must not run on the push tick
────────────────────────────────────────────────────────────────────────────────
`_cloud_parity_check` issues a full `since=2020-01-01` pull of every synced table
with a 180 s read timeout. It was called inline from `run_hybrid_sync`, a job
registered at `seconds=15` with `max_instances=1`. One slow parity therefore
starved every following tick. Observed in production immediately after a restart:

    Execution of job "Hybrid Sync Engine" skipped:
    maximum number of running instances reached (1)

repeating every 15 s for minutes, during which NO business pushed or pulled
anything. The comment sitting at the call site claimed parity was "independent of
the normal push so a parity failure never stalls outbox delivery" — being a
blocking call on the same thread, it was the exact opposite.

────────────────────────────────────────────────────────────────────────────────
C. Instant Pull must not answer its own echo
────────────────────────────────────────────────────────────────────────────────
`routes/sync.py` broadcasts `sync.trigger` and `sync.pull_ping` to a business's
SSE subscribers on every accepted push — including the pushing device's own
listener. Nothing in the event says who caused it, so:

    local push -> cloud broadcasts -> our listener sees it
      -> trigger_sync_run(pull=True) -> which pushes -> cloud broadcasts -> ...

a self-sustaining cycle driven entirely by this device's own writes.
`_MIN_PULL_GAP_SEC` does not break it; it only sets the cycle's period.
"""
import importlib
import inspect
import json
import os
import sys
import threading
import time

os.environ.setdefault("JWT_SECRET",   "test-secret-for-sync-liveness-abcdef123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient

from app import app
from database.db import SessionLocal
from database.models import Base, User
from services.auth import hash_password, create_access_token

TEST_USER_ID  = 88931
TEST_USERNAME = "sync_liveness_user"


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


@pytest.fixture
def hybrid_user():
    """A user whose account already records hosting_mode='hybrid'."""
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == TEST_USERNAME).delete()
        db.commit()
        user = User(
            id=TEST_USER_ID,
            username=TEST_USERNAME,
            password=hash_password("TestPass1!"),
            business_name="Sync Liveness Biz",
            role="enterprise",
            settings=json.dumps({"general": {"hosting_mode": "hybrid"}}),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        yield user
    finally:
        db.query(User).filter(User.username == TEST_USERNAME).delete()
        db.commit()
        db.close()


@pytest.fixture
def auth_headers(hybrid_user):
    token = create_access_token({
        "id": hybrid_user.id,
        "username": hybrid_user.username,
        "business_name": hybrid_user.business_name,
        "role": hybrid_user.role,
    })
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def client():
    return TestClient(app)


def _stored_mode() -> str:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == TEST_USERNAME).first()
        return (json.loads(u.settings or "{}").get("general") or {}).get("hosting_mode")
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# A. hosting_mode downgrade guard
# ═════════════════════════════════════════════════════════════════════════════

class TestHostingModeIsAuthoredLocally:

    def test_cloud_instance_refuses_the_hybrid_to_cloud_downgrade(
        self, client, auth_headers, hybrid_user, monkeypatch
    ):
        """THE GATE. A cloud instance must keep 'hybrid' when told 'cloud'.

        This is the write a web dashboard sends. Accepting it syncs down to the
        desktop and switches that install's sync worker off.
        """
        import routes.auth as auth_routes
        monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud", raising=False)

        resp = client.put("/settings", headers=auth_headers,
                          json={"general": {"hosting_mode": "cloud"}})

        assert resp.status_code == 200, resp.text
        assert _stored_mode() == "hybrid", (
            "The cloud accepted a hosting_mode downgrade. On a real deployment "
            "this row syncs to the owner's desktop, where run_hybrid_sync does "
            "`if hosting_mode != 'hybrid': continue` — that install stops "
            "syncing and stops queueing rows, silently."
        )

    def test_cloud_instance_also_refuses_the_hybrid_to_local_downgrade(
        self, client, auth_headers, hybrid_user, monkeypatch
    ):
        """'local' is just as fatal as 'cloud' — the gate is `!= "hybrid"`."""
        import routes.auth as auth_routes
        monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud", raising=False)

        client.put("/settings", headers=auth_headers,
                   json={"general": {"hosting_mode": "local"}})
        assert _stored_mode() == "hybrid"

    def test_the_refusal_does_not_discard_the_rest_of_the_patch(
        self, client, auth_headers, hybrid_user, monkeypatch
    ):
        """Only hosting_mode is stripped. Rejecting the whole request would turn
        a targeted guard into silent data loss for every other key sent with it.
        """
        import routes.auth as auth_routes
        monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud", raising=False)

        resp = client.put("/settings", headers=auth_headers, json={
            "general": {"hosting_mode": "cloud", "sync_interval": 45}
        })
        assert resp.status_code == 200
        assert resp.json()["general"]["sync_interval"] == 45
        assert _stored_mode() == "hybrid"

    def test_cloud_instance_still_accepts_the_upgrade_to_hybrid(
        self, client, auth_headers, hybrid_user, monkeypatch
    ):
        """_provisionCloudSyncToken PUTs 'hybrid' from a local install on purpose,
        so the Admin Console shows Local + Cloud. Only the downgrade is gated.
        """
        import routes.auth as auth_routes
        monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud", raising=False)

        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == TEST_USERNAME).first()
            u.settings = json.dumps({"general": {"hosting_mode": "local"}})
            db.commit()
        finally:
            db.close()

        client.put("/settings", headers=auth_headers,
                   json={"general": {"hosting_mode": "hybrid"}})
        assert _stored_mode() == "hybrid"

    def test_local_instance_may_change_its_own_mode_freely(
        self, client, auth_headers, hybrid_user, monkeypatch
    ):
        """The guard is CLOUD-side only. A local install is the authority on how
        it is hosted — gating it here would make the mode unchangeable.
        """
        import routes.auth as auth_routes
        monkeypatch.setattr(auth_routes, "_DB_MODE", "local", raising=False)

        client.put("/settings", headers=auth_headers,
                   json={"general": {"hosting_mode": "local"}})
        assert _stored_mode() == "local"


# ═════════════════════════════════════════════════════════════════════════════
# B. parity is off the push tick
# ═════════════════════════════════════════════════════════════════════════════

class TestParityDoesNotStarveTheSyncTick:

    def test_run_hybrid_sync_does_not_call_the_parity_check(self):
        """THE GATE. A 180 s blocking call has no business on a 15 s job with
        max_instances=1.
        """
        from services import sync_worker
        src = inspect.getsource(sync_worker.run_hybrid_sync)
        offending = [
            ln.strip() for ln in src.splitlines()
            if "_cloud_parity_check(" in ln and not ln.strip().startswith("#")
        ]
        assert not offending, (
            "run_hybrid_sync calls _cloud_parity_check again: %s\n"
            "That call does a full since=2020 cloud pull with a 180s read "
            "timeout on the 15s tick, which produces minutes of\n"
            "  Execution of job \"Hybrid Sync Engine\" skipped: maximum number "
            "of running instances reached (1)\n"
            "with zero pushes or pulls in that window." % offending
        )

    def test_the_parity_sweep_exists_as_its_own_entry_point(self):
        from services import sync_worker
        assert callable(getattr(sync_worker, "run_cloud_parity_sweep", None))

    def test_the_sweep_is_registered_as_a_separate_scheduler_job(self):
        """Its own job means its own max_instances — a slow parity delays only
        the next parity, never a push.
        """
        from services import scheduler
        src = inspect.getsource(scheduler)
        assert "run_cloud_parity_sweep" in src
        assert 'id="cloud_parity_sweep"' in src, "parity must have its own job id"

    def test_the_sweep_still_honours_the_per_business_rate_limit(self, monkeypatch):
        """A restart clears _LAST_PARITY. If the sweep ignored the limit, every
        restart would re-run a full-table pull for every hybrid business.
        """
        from services import sync_worker
        assert sync_worker._PARITY_INTERVAL_HOURS >= 1

        calls = []
        monkeypatch.setitem(
            sync_worker._LAST_PARITY, TEST_USER_ID, sync_worker.utc_now()
        )
        monkeypatch.setattr(sync_worker.httpx, "get",
                            lambda *a, **k: calls.append(1))
        summary = sync_worker._cloud_parity_check(SessionLocal(), TEST_USER_ID)
        assert calls == [], "rate-limited parity still hit the network"
        assert summary["missing"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# C. Instant Pull echo suppression
# ═════════════════════════════════════════════════════════════════════════════

class TestInstantPullIgnoresItsOwnEcho:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from services import cloud_listener
        cloud_listener.stop_all()
        cloud_listener._last_local_push.clear()
        yield
        cloud_listener.stop_all()
        cloud_listener._last_local_push.clear()

    def _listener(self, bid=TEST_USER_ID):
        from services import cloud_listener
        return cloud_listener._Listener(bid)

    def test_an_event_right_after_our_own_push_does_not_trigger_a_pull(self, monkeypatch):
        """THE GATE. This is the loop: our push makes the cloud broadcast, the
        broadcast makes us sync, that sync pushes, and round it goes.
        """
        from services import cloud_listener
        pulls = []
        monkeypatch.setattr(cloud_listener, "_last_local_push", {})
        cloud_listener.note_local_push(TEST_USER_ID)

        import services.sync_worker as sw
        monkeypatch.setattr(sw, "trigger_sync_run",
                            lambda bid, **kw: pulls.append(bid))

        listener = self._listener()
        listener._maybe_pull({"type": "sync.trigger", "entity": "invoices"})

        assert pulls == [], (
            "Instant Pull acted on the echo of this device's own push. The cloud "
            "broadcasts sync.trigger + sync.pull_ping for every push it accepts, "
            "including ours, and the event carries no origin — so this pull "
            "pushes, which broadcasts, which pulls, indefinitely."
        )
        assert listener.echo_suppressed == 1

    def test_a_genuinely_remote_event_still_pulls_immediately(self, monkeypatch):
        """The whole point of the feature. Suppressing everything would be a
        cure worse than the disease.
        """
        from services import cloud_listener
        pulls = []
        monkeypatch.setattr(cloud_listener, "_last_local_push", {})

        import services.sync_worker as sw
        monkeypatch.setattr(sw, "trigger_sync_run",
                            lambda bid, **kw: pulls.append(bid))
        monkeypatch.setattr(cloud_listener, "realtime_manager", None, raising=False)

        listener = self._listener()
        listener._maybe_pull({"type": "sync.pull_ping", "entity": "pull_ping"})

        assert pulls == [TEST_USER_ID]
        assert listener.echo_suppressed == 0

    def test_the_window_expires_so_suppression_cannot_become_permanent(self, monkeypatch):
        """A stuck stamp would silently disable Instant Pull forever — the same
        class of failure as the bug it fixes.
        """
        from services import cloud_listener
        pulls = []
        monkeypatch.setattr(cloud_listener, "_last_local_push", {})
        cloud_listener._last_local_push[TEST_USER_ID] = (
            time.monotonic() - (cloud_listener._ECHO_WINDOW_SEC + 1.0)
        )

        import services.sync_worker as sw
        monkeypatch.setattr(sw, "trigger_sync_run",
                            lambda bid, **kw: pulls.append(bid))

        listener = self._listener()
        listener._maybe_pull({"type": "sync.pull_ping"})
        assert pulls == [TEST_USER_ID]

    def test_the_echo_window_is_shorter_than_the_pull_fallback(self):
        """Suppressed remote edits are covered by the periodic pull. That only
        holds while the window stays far below cloud_pull_interval (default 120s).
        """
        from services import cloud_listener
        assert 0 < cloud_listener._ECHO_WINDOW_SEC < 30

    def test_push_success_stamps_the_window(self):
        """The suppression is worthless if nothing records the push."""
        from services import sync_worker
        src = inspect.getsource(sync_worker)
        assert "note_local_push" in src, (
            "sync_worker never calls cloud_listener.note_local_push, so every "
            "push echo is treated as a remote edit."
        )

    def test_stop_then_start_cannot_produce_two_listeners(self):
        """`stop()` used to pop the registry entry immediately. A listener parked
        in iter_lines() on a read=None stream can outlive its stop signal
        indefinitely, so the next start() saw an empty slot and spawned a SECOND
        thread: two SSE connections, two pulls per event, first one unreachable.
        """
        from services import cloud_listener

        listener = cloud_listener._Listener(TEST_USER_ID)
        # A thread that will not observe the stop flag — the real stuck case.
        blocker = threading.Event()
        listener.thread = threading.Thread(target=blocker.wait, daemon=True)
        listener.thread.start()
        cloud_listener._listeners[TEST_USER_ID] = listener
        try:
            assert cloud_listener.stop(TEST_USER_ID) is True
            assert cloud_listener.start(TEST_USER_ID) is False, (
                "start() spawned a duplicate listener while the previous thread "
                "was still alive and streaming."
            )
        finally:
            blocker.set()
            listener.thread.join(timeout=2)

    def test_a_stopping_listener_does_not_report_itself_as_running(self):
        """The UI hides the pull countdown when Instant Pull claims to be up."""
        from services import cloud_listener

        listener = cloud_listener._Listener(TEST_USER_ID)
        blocker = threading.Event()
        listener.thread = threading.Thread(target=blocker.wait, daemon=True)
        listener.thread.start()
        listener.connected = True
        cloud_listener._listeners[TEST_USER_ID] = listener
        try:
            cloud_listener.stop(TEST_USER_ID)
            state = cloud_listener.get_state(TEST_USER_ID)
            assert state["running"] is False
            assert state["connected"] is False
        finally:
            blocker.set()
            listener.thread.join(timeout=2)

    def test_a_402_stops_the_listener_instead_of_reconnecting_forever(self):
        """402 is a verdict, not a transient failure. The old code raised it into
        the generic handler and reconnected on backoff indefinitely, despite the
        comment at the raise site saying "Stop trying".
        """
        from services import cloud_listener
        src = inspect.getsource(cloud_listener._Listener.run)
        assert "self.fatal" in src, "run() ignores the terminal-failure flag"
        assert "self.fatal = True" in inspect.getsource(cloud_listener._Listener._stream)
