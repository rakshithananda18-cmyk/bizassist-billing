"""Persistent per-business operation retry budgets, shared by every caller."""
import json
import math
import random
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime

from services.process_lock import data_path, file_lock

_lock = threading.RLock()


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Unreadable retry budget")
    for operations in value.values():
        if not isinstance(operations, dict):
            raise ValueError("Unreadable operation retry budget")
        for entry in operations.values():
            if not isinstance(entry, dict) or not isinstance(entry.get("failures"), int) \
                    or not isinstance(entry.get("next_attempt_at"), (int, float)) \
                    or not math.isfinite(entry["next_attempt_at"]):
                raise ValueError("Invalid operation retry deadline")
    return value


def _change(callback):
    path = data_path("sync_retry.json")
    with _lock, file_lock(path.with_suffix(".lock")):
        state = _read(path)
        result, changed = callback(state)
        if changed:
            import os
            import tempfile
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=".sync-retry-", delete=False) as stream:
                    temporary = stream.name
                    json.dump(state, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                temporary = None
            finally:
                if temporary:
                    os.unlink(temporary)
        return result


def snapshot(business_id):
    try:
        return _change(lambda state: (state.get(str(business_id), {}).copy(), False))
    except (OSError, ValueError, TypeError, AttributeError):
        return {"storage": {"blocked": True, "reason": "Retry budget cannot be read"}}


def ready(business_id, operation):
    state = snapshot(business_id)
    return "storage" not in state and state.get(operation, {}).get("next_attempt_at", 0) <= time.time()


def defer(business_id, operation, response=None, *, reason=None):
    def apply(state):
        operations = state.setdefault(str(business_id), {})
        failures = int(operations.get(operation, {}).get("failures", 0)) + 1
        delay = min(900, 15 * 2 ** min(failures - 1, 6))
        retry_after = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
        if retry_after is not None:
            try:
                requested = float(retry_after)
            except (TypeError, ValueError):
                try:
                    target = parsedate_to_datetime(retry_after)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    requested = target.timestamp() - time.time()
                except (TypeError, ValueError, OverflowError):
                    requested = 0
            if math.isfinite(requested):
                delay = max(delay, max(0, requested))
        delay += random.uniform(0, min(30, delay * .2))
        operations[operation] = {"failures": failures, "next_attempt_at": time.time() + delay,
                                 "reason": str(reason or getattr(response, "status_code", "request failed"))[:200]}
        return operations[operation].copy(), True
    return _change(apply)


def success(business_id, operation):
    def apply(state):
        operations = state.get(str(business_id), {})
        changed = operation in operations
        operations.pop(operation, None)
        return None, changed
    return _change(apply)
