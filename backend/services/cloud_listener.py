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

_RECONNECT_BASE_SEC = 5.0
_RECONNECT_MAX_SEC = 120.0

# business_id -> _Listener
_listeners: Dict[int, "_Listener"] = {}
_lock = threading.Lock()


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

    # ── state ────────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "connected_since": self.connected_since,
            "last_event_at": self.last_event_at,
            "last_pull_at": self.last_pull_at or None,
            "pull_count": self.pull_count,
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
                # Pro plan lapsed cloud-side. Stop trying; the caller re-evaluates
                # eligibility on the next scheduler sweep.
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
    """Signal a listener to shut down. Returns True if one was running."""
    with _lock:
        listener = _listeners.pop(business_id, None)
    if not listener:
        return False
    listener.stop_event.set()
    logger.info("[INSTANT_PULL] biz=%s listener stopped", business_id)
    return True


def get_state(business_id: int) -> Dict[str, Any]:
    """Connection state for the UI. Absent listener reads as not connected."""
    with _lock:
        listener = _listeners.get(business_id)
    if not listener:
        return {"running": False, "connected": False}
    alive = bool(listener.thread and listener.thread.is_alive())
    return {"running": alive, **listener.snapshot()}


def stop_all():
    with _lock:
        listeners = list(_listeners.values())
        _listeners.clear()
    for listener in listeners:
        listener.stop_event.set()
