"""A quiet rotation must reconnect quickly without losing the catch-up pull."""
from contextlib import contextmanager
import httpx
import pytest


@pytest.fixture(autouse=True)
def hybrid_listener_consent(monkeypatch):
    # These stream protocol tests model an already-authorized hybrid business.
    # Local-only boundaries are exercised against real settings separately.
    from services import sync_policy
    monkeypatch.setattr(sync_policy, "cloud_egress_allowed", lambda *a, **k: True)


@pytest.mark.parametrize("replay", ["complete", "gap"])
def test_listener_reads_with_dead_socket_timeout_and_pulls_only_for_gap(monkeypatch, replay):
    from services import cloud_listener
    calls, kwargs = [], {}
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def iter_lines(self):
            yield from ('retry: 5000', '', 'event: hello', 'data: {"replay":"'+replay+'"}', '', 'event: rotate')
            raise AssertionError("rotation must close the old stream immediately")
    @contextmanager
    def stream(*args, **options):
        kwargs.update(options)
        yield Response()
    monkeypatch.setattr(cloud_listener.httpx,"stream",stream)
    listener = cloud_listener._Listener(123)
    listener.last_event_id = "epoch-7"
    monkeypatch.setattr(listener,"_maybe_pull",calls.append)
    listener._stream("https://cloud.example","token")
    assert kwargs["timeout"].read == 45.0
    assert kwargs["headers"]["Last-Event-ID"] == "epoch-7"
    assert calls == ([{"type":"sync.pull_ping","catch_up":True}] if replay == "gap" else [])
    assert listener._rotated


def test_clean_rotation_reconnects_after_one_second(monkeypatch):
    from services import cloud_listener, sync_worker
    delays = []
    class Stop:
        def is_set(self):
            return False
        def wait(self, seconds):
            delays.append(seconds)
            return True
    listener = cloud_listener._Listener(123)
    listener.stop_event = Stop()
    def stream(*args):
        listener._rotated = True
        listener._stream_had_line = True
    monkeypatch.setattr(listener,"_stream",stream)
    monkeypatch.setattr(sync_worker,"_get_cloud_token",lambda bid:"token")
    listener.run()
    assert delays == [1.0]


def test_headers_without_a_line_do_not_reset_failure_backoff(monkeypatch):
    from services import cloud_listener, sync_worker
    delays = []
    class Stop:
        def is_set(self):
            return False
        def wait(self, seconds):
            delays.append(seconds)
            return len(delays) == 2
    listener = cloud_listener._Listener(123)
    listener.stop_event = Stop()
    def stream(*args):
        listener.connected = True
        raise httpx.ReadTimeout("no keepalive arrived")
    monkeypatch.setattr(listener,"_stream",stream)
    monkeypatch.setattr(sync_worker,"_get_cloud_token",lambda bid:"token")
    listener.run()
    assert delays == [cloud_listener._RECONNECT_BASE_SEC, 2*cloud_listener._RECONNECT_BASE_SEC]
