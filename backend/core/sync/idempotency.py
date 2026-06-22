"""
core/sync/idempotency.py — HTTP-level exactly-once replay guard (R7b, Slice 1).
==============================================================================
The offline-first client keeps an outbox of mutations it made while offline. On
reconnect it flushes them; the network may also retry a request that actually
succeeded but whose response was lost. Either way the SAME user intent can hit a
mutating endpoint more than once.

This module makes that safe at the HTTP edge. The client tags each user-intent
mutation with a stable UUID sent as the `X-Client-Request-Id` header. The route:

    guard = Depends(replay_guard)          # cheap: reads the header + caller's biz
    hit = guard.replay()                   # already processed?
    if hit is not None:
        return hit                         # → replay the stored response verbatim
    ... do the real work (commits) ...
    return guard.store(response)           # persist response under the key

When the header is absent the guard is inert: `replay()` returns None and
`store()` returns the response unchanged without writing a row — so legacy
clients behave exactly as before (fully backward-compatible).

TWO WALLS. This is the OUTER wall (per-request response cache). The per-command
idempotency that already exists (sale `invoice_no`, payment `idempotency_key`,
`post_entry` source-key, the B2B order-sync guard) is the INNER wall. The inner
wall guarantees no double-post even for two *concurrent* identical requests; the
outer wall guarantees the client gets a consistent reply on replay.

The store is race-safe: two requests with the same key that both miss the table
will both try to INSERT; the UNIQUE(business_id, client_request_id) constraint
lets exactly one win, and the loser rolls back its own (uncommitted) row and
returns the winner's stored response. The already-committed mutation is NOT
affected by that rollback — by the time `store()` runs, the command has already
owned and finished its own commit.
"""
import json
import logging
from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.db import get_db
from services.auth import get_active_user
from core.models import IdempotencyKey

logger = logging.getLogger("bizassist.sync")

HEADER = "X-Client-Request-Id"


class ReplayGuard:
    """Per-request handle: look up / store a response under the client's key."""

    def __init__(self, db: Session, business_id: int, key: Optional[str],
                 method: Optional[str] = None, path: Optional[str] = None):
        self.db = db
        self.business_id = business_id
        self.key = (key or "").strip() or None
        self.method = method
        self.path = path

    @property
    def active(self) -> bool:
        return self.key is not None

    def _fetch(self) -> Optional[IdempotencyKey]:
        return (
            self.db.query(IdempotencyKey)
            .filter(
                IdempotencyKey.business_id == self.business_id,
                IdempotencyKey.client_request_id == self.key,
            )
            .first()
        )

    def replay(self) -> Optional[dict]:
        """Return the stored response dict if this key was already processed for
        this business, else None. Tenant-scoped: a key from another business is
        invisible here."""
        if not self.active:
            return None
        row = self._fetch()
        if row is None:
            return None
        logger.info(
            "[SYNC] replay hit biz=%s key=%s %s %s",
            self.business_id, self.key, self.method, self.path,
        )
        return json.loads(row.response_json)

    def store(self, response: dict, status_code: int = 200) -> dict:
        """Persist `response` under this key in its own commit and return it. If a
        concurrent request already stored the same key (IntegrityError on the
        UNIQUE constraint), roll back our row and return the stored response so
        both callers see the same body."""
        if not self.active:
            return response
        row = IdempotencyKey(
            business_id=self.business_id,
            client_request_id=self.key,
            method=self.method,
            path=self.path,
            status_code=status_code,
            response_json=json.dumps(response, default=str),
        )
        self.db.add(row)
        try:
            self.db.commit()
            logger.info(
                "[SYNC] stored biz=%s key=%s %s %s",
                self.business_id, self.key, self.method, self.path,
            )
        except IntegrityError:
            self.db.rollback()
            existing = self._fetch()
            if existing is not None:
                logger.info(
                    "[SYNC] store race resolved biz=%s key=%s — returning stored response",
                    self.business_id, self.key,
                )
                return json.loads(existing.response_json)
            # Unexpected: constraint fired but no row found. Don't mask the work
            # that already committed; just return the live response.
            logger.warning(
                "[SYNC] store IntegrityError without a stored row biz=%s key=%s",
                self.business_id, self.key,
            )
        return response


def replay_guard(
    request: Request,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
) -> ReplayGuard:
    """FastAPI dependency. `get_active_user` and `get_db` are resolved once per
    request and cached, so this reuses the same session/user as the route."""
    return ReplayGuard(
        db=db,
        business_id=current_user["id"],
        key=request.headers.get(HEADER),
        method=request.method,
        path=request.url.path,
    )
