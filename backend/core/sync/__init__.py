"""
core/sync — offline-first sync layer (R7b).

Slice 1: HTTP-level exactly-once replay guard (`idempotency`). The client sends
a stable `X-Client-Request-Id` per user-intent mutation; the server replays the
stored response on retry instead of double-posting. See `idempotency.py`.
"""
