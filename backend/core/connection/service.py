"""
core/connection/service.py
==========================
Domain service logic for B2B Connections and Codes.

CONSENT INVARIANT (Jul-2026 hardening — review findings F-1 / F-2)
------------------------------------------------------------------
A connection is a pipe into a business's catalog, tiered pricing and live stock
counts. BizID is public by design, so knowing it must NEVER be enough to open
that pipe. Two rules are enforced here and nowhere else:

  R1  A link requested by BizID starts ``pending`` and only the COUNTERPARTY can
      move it to ``accepted``.
  R2  A ``revoked`` link cannot be un-revoked by the party that lost access.
      Re-requesting puts the row back to ``pending`` — the revoker decides.
  R3  ``requested_by_business_id`` is the ONLY evidence of who owes the
      decision. A pending row whose requester is UNKNOWN (NULL) is therefore
      not approvable by anybody, and cannot be auto-accepted. Fail closed.

The invite-code path is exempt from R1: handing someone a single-use, expiring
code IS the consent, so redemption accepts immediately.

Everything downstream (``core.order.service.get_supplier_catalog`` and
``create_order``) already filters on ``status == "accepted"``, so these two
rules are sufficient to close the exposure.

WHY R3 EXISTS (regression, Jul-2026)
------------------------------------
``requested_by_business_id`` is nullable — it has to be, because it was added by
ALTER TABLE to a table that already had rows, and because rows also arrive from
``core/connection/transfer.py`` imports and the cloud→local mirror, neither of
which is guaranteed to carry it.

Every comparison against it was written as ``==`` / ``!=``, and ``None`` loses
both. That reopened F-1 completely:

    request_connection(A)  → row is pending, requested_by = NULL
    request_connection(A)  → `NULL == A` is False, so it is not "my own
                             request"  → falls into the mutual-intent branch
                             → approve_connection(A)
                             → `NULL == A` is False, so the self-approval guard
                               does not fire
                             → status = "accepted"

i.e. **sending the same request twice self-approved it**, with no counterparty
involvement, which is exactly the exposure the hardening was written to close.
``is_awaiting`` had the mirror of the same bug: ``NULL != viewer`` is True for
BOTH parties, so the requester was shown an Approve button on their own request.

The fix is to make "unknown requester" an explicit, checked state rather than a
value that silently compares unequal to everyone. See :func:`has_known_requester`.
"""
from services.dates import utc_now
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from core.models import B2BConnection, B2BInviteCode
from core.connection.utils import generate_connection_code
from database.models import User

# ── Status vocabulary ────────────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_REVOKED = "revoked"

VALID_STATUSES = {STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_REVOKED}


def _load(db: Session, connection_id: int, *, business_id: int) -> B2BConnection:
    """Load a connection the caller is a party to. Scoped in SQL (rule R4).

    ``business_id`` is REQUIRED and keyword-only. It used to be absent — the
    function fetched by primary key alone and every caller was expected to follow
    up with :func:`is_party`. All four did, so this was not a live exposure; it
    was a convention, and a convention is one new call site away from a
    cross-tenant read (review finding S-3).

    Two reasons to push the scope into the query rather than leave it in Python:

    · **On a local install there is no RLS.** Postgres policies protect the cloud;
      SQLite has nothing behind the application filter. And the B2B mirror
      deliberately writes a COUNTERPARTY's connection rows into the local DB, so
      the "desktop installs are single-tenant anyway" assumption that made the
      gap tolerable no longer holds — the rows of a business that is not you are
      now present locally, by design.
    · **Not-found and not-yours should be indistinguishable.** Answering
      "Connection not found" for a row that exists but belongs to someone else
      leaks its existence to anyone who can enumerate integer ids.

    Callers keep their :func:`is_party` assertions. They are now unreachable by
    construction, which is the point: defence in depth where the outer layer is
    structural and the inner one is a belt.
    """
    conn = (
        db.query(B2BConnection)
        .filter(
            B2BConnection.id == connection_id,
            or_(
                B2BConnection.seller_business_id == business_id,
                B2BConnection.buyer_business_id == business_id,
            ),
        )
        .first()
    )
    if not conn:
        raise ValueError("Connection not found")
    return conn


def is_party(conn: B2BConnection, business_id: int) -> bool:
    """True when ``business_id`` is one of the two businesses on the link."""
    return business_id in (conn.seller_business_id, conn.buyer_business_id)


def counterparty_id(conn: B2BConnection, business_id: int) -> Optional[int]:
    """The *other* business on the link, or None if ``business_id`` isn't on it."""
    if business_id == conn.seller_business_id:
        return conn.buyer_business_id
    if business_id == conn.buyer_business_id:
        return conn.seller_business_id
    return None


def has_known_requester(conn: B2BConnection) -> bool:
    """True when we know which party raised this request.

    ``requested_by_business_id`` is nullable (added by ALTER TABLE to a
    populated table; also absent on imported and mirrored rows). NULL means
    "we do not know", and under R3 that is NOT the same as "somebody other
    than you" — treating it that way is what let a requester approve their own
    request. Every consent decision must gate on this first.
    """
    return getattr(conn, "requested_by_business_id", None) is not None


def is_requester(conn: B2BConnection, business_id: int) -> bool:
    """True when ``business_id`` is KNOWN to have raised this request.

    False for an unknown requester — deliberately. Callers use this to answer
    "may this business approve?", and an unknown requester must fail closed via
    :func:`has_known_requester`, not slip through as "not the requester".
    """
    return (
        has_known_requester(conn)
        and conn.requested_by_business_id == business_id
    )


def is_awaiting(conn: B2BConnection, business_id: int) -> bool:
    """True when this connection is pending AND it is ``business_id``'s turn to
    decide — i.e. they are a party to it, we KNOW who asked, and it wasn't them.

    The ``has_known_requester`` clause is load-bearing (R3): without it a row
    with a NULL requester was "awaiting" BOTH parties, so the requester saw an
    Approve button on their own request and could grant themselves access.
    """
    return (
        conn.status == STATUS_PENDING
        and is_party(conn, business_id)
        and has_known_requester(conn)
        and conn.requested_by_business_id != business_id
    )

def create_connection_code(db: Session, seller_business_id: int, expires_in_hours: int = 24) -> B2BInviteCode:
    """Generate a temporary single-use connection code for a seller."""
    code_str = generate_connection_code(db)
    expires_at = utc_now() + timedelta(hours=expires_in_hours)
    
    code_obj = B2BInviteCode(
        seller_business_id=seller_business_id,
        code=code_str,
        is_used=False,
        expires_at=expires_at
    )
    db.add(code_obj)
    db.commit()
    db.refresh(code_obj)
    return code_obj

def redeem_connection_code(db: Session, buyer_business_id: int, code: str) -> B2BConnection:
    """
    Redeem a connection code as a buyer to establish a B2B connection with the seller.
    Automatically accepts the connection link.
    """
    code_obj = db.query(B2BInviteCode).filter(B2BInviteCode.code == code).first()
    if not code_obj:
        raise ValueError("Invalid connection code")
    
    if code_obj.is_used:
        raise ValueError("This connection code has already been used")
        
    if code_obj.expires_at < utc_now():
        raise ValueError("This connection code has expired")
        
    seller_id = code_obj.seller_business_id
    if seller_id == buyer_business_id:
        raise ValueError("Cannot connect to your own business")
        
    # Check if a connection already exists
    conn = db.query(B2BConnection).filter(
        B2BConnection.seller_business_id == seller_id,
        B2BConnection.buyer_business_id == buyer_business_id
    ).first()
    
    # Exempt from rule R1: the seller generated a single-use, expiring code and
    # handed it over — that IS the consent, so this link goes live immediately.
    # ``requested_by`` is the seller because the seller initiated by issuing the
    # code; ``responded_at`` is stamped so the row never looks "awaiting reply".
    if conn:
        conn.status = STATUS_ACCEPTED
        conn.requested_by_business_id = seller_id
        conn.responded_at = utc_now()
        conn.updated_at = utc_now()
    else:
        conn = B2BConnection(
            seller_business_id=seller_id,
            buyer_business_id=buyer_business_id,
            price_tier="standard",
            discount_pct=0.0,
            credit_limit=0.0,
            outstanding_balance=0.0,
            stock_visibility="exact",
            status=STATUS_ACCEPTED,
            requested_by_business_id=seller_id,
            responded_at=utc_now(),
        )
        db.add(conn)

    code_obj.is_used = True
    db.commit()
    db.refresh(conn)
    return conn

def update_connection_policy(
    db: Session,
    seller_business_id: int,
    connection_id: int,
    price_tier: str,
    discount_pct: float,
    credit_limit: float,
    stock_visibility: str,
    catalog_category: str = None
) -> B2BConnection:
    """
    Update B2BConnection settings. Allowed only for the seller.
    """
    # Routed through _load so the tenant scope is applied in SQL exactly once,
    # rather than re-derived here (S-3). This function had its own unscoped
    # fetch-by-id — correct, because the seller check below is stricter than
    # is_party, but it was a second copy of the rule and copies drift.
    conn = _load(db, connection_id, business_id=seller_business_id)

    if conn.seller_business_id != seller_business_id:
        raise PermissionError("Only the seller can update connection settings")
        
    if price_tier not in ["standard", "wholesale", "distributor"]:
        raise ValueError("Invalid price tier")
        
    if stock_visibility not in ["exact", "band", "hidden"]:
        raise ValueError("Invalid stock visibility policy")
        
    conn.price_tier = price_tier
    conn.discount_pct = max(0.0, float(discount_pct))
    conn.credit_limit = max(0.0, float(credit_limit))
    conn.stock_visibility = stock_visibility
    conn.catalog_category = catalog_category
    conn.updated_at = utc_now()
    
    db.commit()
    db.refresh(conn)
    return conn

def revoke_connection(db: Session, business_id: int, connection_id: int) -> B2BConnection:
    """
    Revoke a connection partnership. Can be initiated by either party.

    Revocation is STICKY (rule R2): the revoked party cannot restore its own
    access by re-POSTing a connect request — ``request_connection`` will put the
    row back to ``pending`` and the revoker gets to decide again.
    """
    conn = _load(db, connection_id, business_id=business_id)

    if not is_party(conn, business_id):
        raise PermissionError("Not authorized to revoke this connection")

    conn.status = STATUS_REVOKED
    # Remember who revoked, so a later re-request is routed to them for approval
    # rather than to whichever side happens to be the seller.
    conn.requested_by_business_id = counterparty_id(conn, business_id)
    conn.responded_at = utc_now()
    conn.updated_at = utc_now()

    db.commit()
    db.refresh(conn)
    return conn


def request_connection(
    db: Session,
    initiator_id: int,
    target_bizid: str,
    connect_as: str,
    message: str = None,
) -> B2BConnection:
    """
    Ask another business (found by its public BizID) to connect.

    Creates the link in ``pending`` — NOT ``accepted``. The target business must
    call :func:`approve_connection` before any catalog or order traffic flows.

    Re-requesting is idempotent-ish and safe in every prior state:
      · already ``pending``  → returns the existing request untouched (no spam)
      · already ``accepted`` → returns it as-is (nothing to do)
      · ``rejected``/``revoked`` → re-opens as ``pending``, addressed to the party
        that rejected/revoked. The requester can never self-approve.
    """
    target = db.query(User).filter(User.public_id == target_bizid).first()
    if not target:
        raise ValueError("Business with this BizID not found")

    if target.id == initiator_id:
        raise ValueError("Cannot connect to your own business")

    if connect_as == "buyer":
        seller_id, buyer_id = target.id, initiator_id
    elif connect_as == "seller":
        seller_id, buyer_id = initiator_id, target.id
    else:
        raise ValueError("Invalid connection role")

    conn = db.query(B2BConnection).filter(
        B2BConnection.seller_business_id == seller_id,
        B2BConnection.buyer_business_id == buyer_id,
    ).first()

    if conn:
        if conn.status == STATUS_ACCEPTED:
            return conn                      # already linked — no-op
        if conn.status == STATUS_PENDING:
            if not has_known_requester(conn):
                # R3: we do not know who raised this row (legacy / imported /
                # mirrored). CLAIM it for the caller instead of guessing.
                #
                # Claiming is the only consent-SAFE move available: it names the
                # caller as the requester, which makes the OTHER party the
                # approver. Auto-accepting here is what reopened F-1 — with a
                # NULL requester the "is this my own request?" test below is
                # False for everyone, so a business could accept its own request
                # simply by sending it a second time.
                conn.requested_by_business_id = initiator_id
                conn.request_message = (message or "").strip() or conn.request_message
                conn.updated_at = utc_now()
                db.commit()
                db.refresh(conn)
                return conn
            if conn.requested_by_business_id == initiator_id:
                return conn                  # their own request, still waiting
            # The other side already asked us — treat this as mutual intent and
            # accept, since both parties have now explicitly opted in. Safe only
            # because we got here with a KNOWN requester who is not the caller.
            return approve_connection(db, business_id=initiator_id, connection_id=conn.id)
        # rejected / revoked → re-open for the counterparty to decide again
        conn.status = STATUS_PENDING
        conn.requested_by_business_id = initiator_id
        conn.request_message = (message or "").strip() or None
        conn.responded_at = None
        conn.updated_at = utc_now()
    else:
        conn = B2BConnection(
            seller_business_id=seller_id,
            buyer_business_id=buyer_id,
            price_tier="standard",
            discount_pct=0.0,
            credit_limit=0.0,
            outstanding_balance=0.0,
            stock_visibility="exact",
            status=STATUS_PENDING,
            requested_by_business_id=initiator_id,
            request_message=(message or "").strip() or None,
        )
        db.add(conn)

    db.commit()
    db.refresh(conn)
    return conn


def approve_connection(db: Session, business_id: int, connection_id: int) -> B2BConnection:
    """
    Approve a pending request. Only the COUNTERPARTY may approve — the business
    that raised the request cannot approve its own (rule R1).
    """
    conn = _load(db, connection_id, business_id=business_id)

    if not is_party(conn, business_id):
        raise PermissionError("Not authorized to act on this connection")

    if conn.status == STATUS_ACCEPTED:
        return conn                                   # idempotent

    if conn.status != STATUS_PENDING:
        raise ValueError(f"Connection is '{conn.status}' and cannot be approved")

    # R3 — fail closed. With an unknown requester we cannot prove the caller is
    # not approving their own request, and "cannot prove" must mean "refuse".
    # The row is not stranded: re-requesting claims it (see request_connection),
    # which names a requester and hands the decision to the other party.
    if not has_known_requester(conn):
        raise PermissionError(
            "This connection request has no recorded sender, so it cannot be "
            "approved. Ask the other business to send the request again."
        )

    if conn.requested_by_business_id == business_id:
        raise PermissionError("You cannot approve your own connection request")

    conn.status = STATUS_ACCEPTED
    conn.responded_at = utc_now()
    conn.updated_at = utc_now()

    db.commit()
    db.refresh(conn)
    return conn


def reject_connection(db: Session, business_id: int, connection_id: int) -> B2BConnection:
    """
    Decline a pending request. Only the counterparty may reject; the requester
    withdraws instead (:func:`cancel_request`).
    """
    conn = _load(db, connection_id, business_id=business_id)

    if not is_party(conn, business_id):
        raise PermissionError("Not authorized to act on this connection")

    if conn.status != STATUS_PENDING:
        raise ValueError(f"Connection is '{conn.status}' and cannot be rejected")

    # An UNKNOWN requester is permitted to reject (``is_requester`` is False for
    # NULL). Reject only ever DENIES access, so failing open in the deny
    # direction is the safe default — the worst case is a party declining a row
    # nobody can prove they raised, which leaves them exactly where they were.
    if is_requester(conn, business_id):
        raise PermissionError("You cannot reject your own request — cancel it instead")

    conn.status = STATUS_REJECTED
    conn.responded_at = utc_now()
    conn.updated_at = utc_now()

    db.commit()
    db.refresh(conn)
    return conn


def cancel_request(db: Session, business_id: int, connection_id: int) -> None:
    """
    Withdraw a request you raised that is still pending. The row is deleted so a
    withdrawn request leaves no trace in the counterparty's inbox.
    """
    conn = _load(db, connection_id, business_id=business_id)

    if not is_party(conn, business_id):
        raise PermissionError("Not authorized to act on this connection")

    if conn.status != STATUS_PENDING:
        raise ValueError(f"Connection is '{conn.status}' and cannot be cancelled")

    # Fails closed on an unknown requester (``is_requester`` is False for NULL):
    # cancel DELETES the row, so we must be certain it is the caller's to delete
    # or a stranger could wipe a request addressed to them. Such a row is not
    # stranded — re-requesting claims it, and the claimer can then cancel.
    if not is_requester(conn, business_id):
        raise PermissionError("Only the business that raised the request can cancel it")

    db.delete(conn)
    db.commit()


# ── Back-compat shim ─────────────────────────────────────────────────────────
def create_direct_connection(db: Session, initiator_id: int, target_bizid: str,
                             connect_as: str) -> B2BConnection:
    """DEPRECATED — kept so older callers/tests keep importing cleanly.

    Historically this created an immediately-``accepted`` link, which is exactly
    the consent hole described at the top of this module. It now delegates to
    :func:`request_connection`, so the returned connection is ``pending``.
    """
    return request_connection(db, initiator_id=initiator_id,
                              target_bizid=target_bizid, connect_as=connect_as)
