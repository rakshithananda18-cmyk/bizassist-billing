"""
services/cloud_listener.py — Instant Pull: cloud → local push notification.

WHY THIS EXISTS
---------------
Hybrid devices converge on a *timer*. `sync_worker` polls the cloud every
`cloud_pull_interval` seconds (default 120, floor 30) — so an edit made on
another device, or on the web dashboard, can sit invisible on this machine for
up to two minutes.

The cloud already announces those edits. `routes/sync.py` broadcasts
`sync.pull_ping` to a business's SSE subscribers the moment a push commits.
Cloud-connected browsers act on it immediately (`useRealtimeLeader.js` treats
`pull_ping` as a pull trigger). A *hybrid* device never saw it, because its
frontend subscribes to the LOCAL backend's `/realtime/events`, not the cloud's.

This module closes that gap: one background thread per hybrid business holds an
SSE connection to the CLOUD's `/realtime/events` and, on a relevant event, runs
an immediate local pull. That is the whole feature — "Instant Pull" is this
thread being connected.

DESIGN NOTES
------------
* The periodic pull in `sync_worker` is deliberately left running. It is the
  fallback: if this thread is down, disconnected, or the plan is not Pro, the
  timer still converges the device. Instant Pull is an accelerator, never the
  only path — which is also why the UI must show the countdown whenever this
  listener is not actually connected.
* Connection state is published through `get_state()` so the UI can report the
  truth instead of echoing a local preference flag.
* Threads are used (not asyncio) because the sync worker and APScheduler are
  already threaded, and `realtime_manager.broadcast_threadsafe` exists precisely
  to hand events back to the main loop from these threads.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Events that mean "the cloud has data this device does not". `sync.progress`
# and the pos.* chatter are deliberately excluded — they fire constantly during
# normal counter use and would turn Instant Pull into a pull storm.
_PULL_EVENTS = {"sync.pull_ping", "sync.trigger"}

# Never pull more often than this, no matter how many pings arrive. A busy
# multi-counter business can emit a ping per line item; without this floor a
# single cart could trigger dozens of full pull cycles.
_MIN_PULL_GAP_SEC = 3.0

# ── ECHO SUPPRESSION ─────────────────────────────────────────────────────────
# `routes/sync.py` broadcasts `sync.trigger` (per entity) and `sync.pull_ping`
# to a business's SSE subscribers on EVERY accepted push — including this
# device's own. Nothing in the event identifies who caused it, so without this
# window the listener does:
#
#   local push -> cloud broadcasts sync.trigger -> this listener sees it
#     -> trigger_sync_run(pull=True) -> that run pushes -> cloud broadcasts
#     -> this listener sees it -> ... forever
#
# a self-sustaining pull/push cycle driven entirely by the device's own writes.
# `_MIN_PULL_GAP_SEC` does not break it — it only sets the cycle's period.
#
# The fix without a protocol change: the sync worker stamps `note_local_push()`
# whenever this device pushes, and events arriving within this window are read
# as our own echo and ignored. Genuine concurrent edits from ANOTHER device that
# land inside the window are not lost — the periodic `cloud_pull_interval` pull
# (default 120 s) is still running and remains the guaranteed convergence path.
# Instant Pull is an accelerator, never the only route.
#
# Sized above the push round-trip (broadcast is dispatched via
# `background_tasks` after the push commits) and well under the pull interval.
_ECHO_WINDOW_SEC = 8.0

# business_id -> monotonic timestamp of this device's last outbound push.
_last_local_push: Dict[int, float] = {}

_RECONNECT_BASE_SEC = 5.0
_RECONNECT_MAX_SEC = 120.0

# business_id -> _Listener
_listeners: Dict[int, "_Listener"] = {}
_lock = threading.Lock()


def note_local_push(business_id: int) -> None:
    """Record that THIS device just pushed to the cloud for `business_id`.

    Called by `sync_worker` after a push. See `_ECHO_WINDOW_SEC`: the cloud will
    now broadcast that push straight back at us, and acting on it would start a
    self-feeding pull loop.
    """
    _last_local_push[business_id] = time.monotonic()


class _Listener:
    """Owns one SSE connection to the cloud for one business."""

    def __init__(self, business_id: int):
        self.business_id = business_id
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.connected = False
        self.connected_since: Optional[float] = None
        self.last_event_at: Optional[float] = None
        self.last_pull_at: float = 0.0
        self.last_error: Optional[str] = None
        self.pull_count = 0
        self.echo_suppressed = 0
        # Set when the cloud says this business may not hold the stream at all
        # (402 = Pro lapsed). Reconnecting on that is pure noise: the answer
        # cannot change until the plan does, and the scheduler re-evaluates
        # eligibility and calls start() again when it has.
        self.fatal = False

    # ── state ────────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "connected_since": self.connected_since,
            "last_event_at": self.last_event_at,
            "last_pull_at": self.last_pull_at or None,
            "pull_count": self.pull_count,
            "echo_suppressed": self.echo_suppressed,
            "last_error": self.last_error,
        }

    # ── main loop ────────────────────────────────────────────────────────────
    def run(self):
        from services.sync_worker import CLOUD_URL, _get_cloud_token

        backoff = _RECONNECT_BASE_SEC
        while not self.stop_event.is_set():
            token = _get_cloud_token(self.business_id)
            if not token:
                # No cloud token yet (provisioned at owner login). Not an error —
                # the timer fallback is still converging the device.
                self.last_error = "no cloud token"
                self._mark_disconnected()
                if self.stop_event.wait(30):
                    break
                continue

            try:
                self._stream(CLOUD_URL, token)
                backoff = _RECONNECT_BASE_SEC   # clean disconnect — reset backoff
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.debug(
                    "[INSTANT_PULL] biz=%s stream ended: %s", self.business_id, self.last_error
                )
            finally:
                self._mark_disconnected()

            # A 402 is a verdict, not a transient failure. The old code raised it
            # into this same handler and then reconnected on backoff forever,
            # despite the comment at the raise site saying "Stop trying".
            if self.fatal:
                logger.info(
                    "[INSTANT_PULL] biz=%s listener exiting: %s (the scheduler restarts "
                    "it if eligibility changes; the periodic pull is unaffected)",
                    self.business_id, self.last_error,
                )
                return

            if self.stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, _RECONNECT_MAX_SEC)

    def _stream(self, cloud_url: str, token: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        # read timeout None: an SSE stream is idle by nature between events.
        timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)

        with httpx.stream(
            "GET", f"{cloud_url}/realtime/events", headers=headers, timeout=timeout
        ) as resp:
            if resp.status_code == 401:
                from services.sync_worker import _invalidate_cloud_token
                _invalidate_cloud_token(self.business_id)
                raise RuntimeError("cloud rejected the sync token (401)")
            if resp.status_code == 402:
                # Pro plan lapsed cloud-side. Terminal for this listener — see the
                # `self.fatal` check in run(). Reconnecting cannot change the
                # answer; only a plan change can, and the scheduler sweep calls
                # start() again when it sees one.
                self.fatal = True
                raise RuntimeError("cloud requires the Pro plan (402)")
            resp.raise_for_status()

            self.connected = True
            self.connected_since = time.time()
            self.last_error = None
            logger.info("[INSTANT_PULL] biz=%s connected to cloud event stream", self.business_id)

            for raw in resp.iter_lines():
                if self.stop_event.is_set():
                    return
                if not raw or not raw.startswith("data:"):
                    continue
                payload = raw[5:].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except (ValueError, TypeError):
                    continue

                self.last_event_at = time.time()
                if event.get("type") in _PULL_EVENTS:
                    self._maybe_pull(event)

    def _maybe_pull(self, event: Dict[str, Any]):
        now = time.time()

        # Our own push, reflected back at us. Acting on it starts the loop
        # documented at _ECHO_WINDOW_SEC.
        last_push = _last_local_push.get(self.business_id)
        if last_push is not None and (time.monotonic() - last_push) < _ECHO_WINDOW_SEC:
            self.echo_suppressed += 1
            logger.debug(
                "[INSTANT_PULL] biz=%s ignoring %s — echo of this device's own push "
                "%.1fs ago (periodic pull still covers any concurrent remote edit)",
                self.business_id, event.get("type"), time.monotonic() - last_push,
            )
            return

        if now - self.last_pull_at < _MIN_PULL_GAP_SEC:
            logger.debug(
                "[INSTANT_PULL] biz=%s coalescing %s (last pull %.1fs ago)",
                self.business_id, event.get("type"), now - self.last_pull_at,
            )
            return
        self.last_pull_at = now
        self.pull_count += 1

        logger.info(
            "[INSTANT_PULL] biz=%s cloud announced %s (entity=%s) — pulling now",
            self.business_id, event.get("type"), event.get("entity"),
        )
        try:
            from services.sync_worker import trigger_sync_run
            trigger_sync_run(self.business_id, pull=True)
        except Exception as e:
            logger.warning("[INSTANT_PULL] biz=%s pull failed: %s", self.business_id, e)
            return

        # Tell this device's own UI that fresh rows landed, so open pages refresh
        # without waiting for their next poll.
        try:
            from services.realtime import realtime_manager
            realtime_manager.broadcast_threadsafe(
                self.business_id, {"type": "sync.trigger", "entity": event.get("entity") or "pull_ping"}
            )
        except Exception:
            pass

    def _mark_disconnected(self):
        if self.connected:
            logger.info("[INSTANT_PULL] biz=%s disconnected from cloud event stream", self.business_id)
        self.connected = False
        self.connected_since = None


# ── public API ───────────────────────────────────────────────────────────────

def start(business_id: int) -> bool:
    """Ensure a listener thread is running for this business. Idempotent."""
    with _lock:
        existing = _listeners.get(business_id)
        if existing and existing.thread and existing.thread.is_alive():
            if existing.stop_event.is_set():
                # Stopping but not yet dead. It is parked in `resp.iter_lines()`
                # on a stream opened with `read=None`, so it will not observe the
                # stop flag until the cloud sends something — which may be never.
                #
                # `stop()` pops the listener from `_listeners`, so the is_alive
                # check above could not see it and this call would have started a
                # SECOND thread on the same business: two SSE connections, two
                # pull triggers per event, and no way to reach the first one
                # again. Refuse instead, and let the next sweep (15 s later)
                # start cleanly once it has actually exited.
                logger.debug(
                    "[INSTANT_PULL] biz=%s previous listener still winding down — "
                    "not starting a second one", business_id,
                )
            return False
        listener = _Listener(business_id)
        thread = threading.Thread(
            target=listener.run,
            name=f"instant-pull-{business_id}",
            daemon=True,
        )
        listener.thread = thread
        _listeners[business_id] = listener
        thread.start()
        logger.info("[INSTANT_PULL] biz=%s listener started", business_id)
        return True


def stop(business_id: int) -> bool:
    """Signal a listener to shut down. Returns True if one was signalled.

    The registry entry is deliberately KEPT until the thread is actually dead.
    Popping it immediately (the previous behaviour) hid a still-live thread from
    `start()`, which would then spawn a duplicate listener for the same business
    — the first one still streaming, still pulling, and now unreachable. A
    listener blocked in `iter_lines()` on a `read=None` stream can outlive its
    stop signal indefinitely, so this window was wide, not theoretical.

    Entries are reaped here on a later call once `is_alive()` is False.
    """
    with _lock:
        # Reap any listener that has finished shutting down.
        for bid, l in list(_listeners.items()):
            if l.stop_event.is_set() and not (l.thread and l.thread.is_alive()):
                _listeners.pop(bid, None)

        listener = _listeners.get(business_id)
        if not listener:
            return False
        already = listener.stop_event.is_set()
        listener.stop_event.set()
        if listener.thread and not listener.thread.is_alive():
            _listeners.pop(business_id, None)

    if not already:
        logger.info("[INSTANT_PULL] biz=%s listener stopped", business_id)
    return True


def get_state(business_id: int) -> Dict[str, Any]:
    """Connection state for the UI. Absent listener reads as not connected."""
    with _lock:
        listener = _listeners.get(business_id)
    if not listener:
        return {"running": False, "connected": False}
    alive = bool(listener.thread and listener.thread.is_alive())
    # A listener that has been told to stop must not report as running even
    # while its thread is winding down — the UI would hide the pull countdown
    # for a channel that is on its way out.
    if listener.stop_event.is_set():
        return {"running": False, "connected": False, "stopping": alive}
    return {"running": alive, **listener.snapshot()}


def stop_all():
    with _lock:
        listeners = list(_listeners.values())
        _listeners.clear()
    for listener in listeners:
        listener.stop_event.set()
