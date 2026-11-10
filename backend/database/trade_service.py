"""Internal B2B authority; never exposed as a general request dependency.

The HTTP role cannot SET ROLE into this identity. Its separate credential is
used only after a command names its authenticated actor and exact relationship.
The service session revalidates and locks that relationship before any posting.
"""
from contextlib import contextmanager
import os
from types import SimpleNamespace
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import Session, load_only
from fastapi import HTTPException

_ENGINES = {}
PUBLIC_COLUMNS = ("id", "public_id", "business_name", "role", "parent_business_id", "username",
                  "gstin", "address", "state_code", "phone", "email", "pan", "upi_vpa", "logo")


def _privileged(db):
    return db.bind.dialect.name != "postgresql" or bool(db.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar())


def _actor_id(db):
    from database.db import current_business_id_var
    value = db.info.get("business_id") or current_business_id_var.get()
    if value is None:
        raise HTTPException(401, "A verified business identity is required")
    return int(value)


def _open_service():
    url = os.environ.get("DATABASE_TRADE_SERVICE_URL", "")
    if not url:
        raise HTTPException(503, "Trade service credentials must be configured before enabling B2B on a constrained runtime")
    if url not in _ENGINES:
        _ENGINES[url] = create_engine(url, pool_size=2, max_overflow=1, pool_pre_ping=True, hide_parameters=True)
    session = Session(_ENGINES[url])
    role = session.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).first()
    if role is None or role[0] or not role[1]:
        session.close()
        raise HTTPException(503, "Trade service must use its dedicated non-superuser trade role")
    from database.models import User
    # ORM identities loaded for trading contain public party fields only. The
    # role is not granted password/settings/token-version columns at all.
    @event.listens_for(session, "do_orm_execute")
    def safe_user_projection(state):
        if state.is_select and any(d.get("expr") is User for d in getattr(state.statement, "column_descriptions", [])):
            state.statement = state.statement.options(load_only(*(getattr(User, c) for c in PUBLIC_COLUMNS), raiseload=True))
    return session


@contextmanager
def trade_session(db, *, actor_id, operation, seller_id=None, order_id=None, code=None):
    if _privileged(db) or db.info.get("trade_authorized"):
        yield db
        return
    if _actor_id(db) != int(actor_id):
        raise HTTPException(403, "Trade actor does not match the authenticated business")
    from database.models import User
    from core.models import B2BConnection, B2BOrder, B2BInviteCode
    service = _open_service()
    try:
        actor = service.query(User).filter(User.id == actor_id, User.parent_business_id.is_(None)).first()
        if actor is None or (actor.role or "").lower() in {"deleted", "retired", "cashier", "supply adder"}:
            raise HTTPException(403, "Active business-owner authentication required for trading")
        buyer_id = actor_id
        invite = None
        if operation == "redeem_connection":
            from services.dates import utc_now
            invite = service.query(B2BInviteCode).filter(B2BInviteCode.code == code).with_for_update().first()
            if invite is None or invite.is_used or invite.expires_at < utc_now():
                raise HTTPException(403, "The invitation is invalid, expired or already used")
            seller_id = invite.seller_business_id
        if operation in {"transition_order", "reconcile_order"}:
            order = service.query(B2BOrder).filter(B2BOrder.id == order_id).with_for_update().first()
            if order is None or actor_id not in {order.buyer_business_id, order.seller_business_id}:
                raise HTTPException(403, "Order does not belong to this business")
            if operation == "reconcile_order" and actor_id != order.buyer_business_id:
                raise HTTPException(403, "Only the buyer can reconcile its purchase")
            buyer_id, seller_id = order.buyer_business_id, order.seller_business_id
        elif operation not in {"place_order", "catalog", "redeem_connection"}:
            raise HTTPException(403, "Unsupported trade service operation")
        conn = service.query(B2BConnection).filter(B2BConnection.buyer_business_id == buyer_id,
            B2BConnection.seller_business_id == seller_id, B2BConnection.status == "accepted").with_for_update().first()
        seller = service.get(User, seller_id)
        buyer = service.get(User, buyer_id)
        if (conn is None and invite is None) or any(p is None or (p.role or "").lower() in {"deleted", "retired"} for p in (seller, buyer)):
            raise HTTPException(403, "An accepted connection between active businesses is required")
        for party in sorted({buyer_id, seller_id}):
            if not service.execute(text("SELECT bizassist_trade_lock_actor(:p)"), {"p": party}).scalar():
                raise HTTPException(403, "A trading business was retired")
        from database.security import bind_tenant
        bind_tenant(service, actor_id)
        service.info.update(business_id=actor_id, trade_authorized={"actor_id": actor_id, "operation": operation, "order_id": order_id, "seller_id": seller_id, "buyer_id": buyer_id})
        yield service
    except Exception:
        service.rollback()
        raise
    finally:
        service.close()


def authorized_catalog(db, seller_id):
    actor = _actor_id(db)
    with trade_session(db, actor_id=actor, operation="catalog", seller_id=seller_id) as service:
        from core.order.service import get_supplier_catalog
        return get_supplier_catalog(service, actor, seller_id)


def trade_policy(db, seller_id):
    scope = db.info.get("trade_authorized") or {}
    if seller_id not in {scope.get("seller_id"), scope.get("buyer_id")}:
        raise HTTPException(403, "Business policy is outside this authorized trade")
    return db.execute(text("SELECT bizassist_trade_policy(:p)"), {"p": seller_id}).scalar()


def business_profile(db, id=None, bizid=None):
    """Public identity, with contact/legal details only for accepted partners.

    This is a value object, never a User credential/settings-bearing ORM row.
    """
    from database.models import User
    from core.models import B2BConnection
    from sqlalchemy import or_, and_
    same = _privileged(db) or bool(db.info.get("trade_authorized"))
    service = db if same else _open_service()
    try:
        actor = db.info.get("business_id")
        if not same:
            actor = _actor_id(db)
        query = service.query(User)
        query = query.filter(User.id == id) if id is not None else query.filter(User.public_id == bizid)
        party = query.filter(User.parent_business_id.is_(None)).first()
        if party is None:
            return None
        shared = same or actor == party.id
        if not shared:
            shared = service.query(B2BConnection.id).filter(B2BConnection.status == "accepted", or_(
                and_(B2BConnection.buyer_business_id == actor, B2BConnection.seller_business_id == party.id),
                and_(B2BConnection.seller_business_id == actor, B2BConnection.buyer_business_id == party.id))).first() is not None
        basic = {"id", "public_id", "business_name", "role", "state_code", "parent_business_id"}
        values = {key: getattr(party, key) if shared or key in basic else None for key in PUBLIC_COLUMNS}
        if db.bind.dialect.name == "postgresql":
            state = db.execute(text("SELECT bizassist_network_state(:p)"), {"p": party.id}).scalar() or {}
            values["hosting_mode"] = state.get("hosting_mode", "local")
            values["business_type"] = state.get("business_type", "general")
        else:
            import json
            try:
                values["hosting_mode"] = (json.loads(party.settings or "{}") or {}).get("general", {}).get("hosting_mode", "local")
            except (ValueError, AttributeError):
                values["hosting_mode"] = "local"
            from core.models import BusinessSettings
            settings = db.query(BusinessSettings).filter(BusinessSettings.business_id == party.id).first()
            values["business_type"] = settings.template_key if settings else "general"
        return SimpleNamespace(**values)
    finally:
        if service is not db:
            service.close()


def install_trade_role(connection, role):
    """Migration-only least table/column grants; never grant membership to API."""
    import re
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", role):
        raise ValueError("Invalid trade role")
    facts = connection.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:r"), {"r": role}).first()
    if facts is None or facts[0] or not facts[1]:
        raise ValueError("Trade role must exist as NOSUPERUSER BYPASSRLS with a separately managed credential")
    from sqlalchemy import inspect
    connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO "{role}"')
    connection.exec_driver_sql(f'REVOKE ALL ON users FROM "{role}"')
    columns = ",".join('"' + c + '"' for c in PUBLIC_COLUMNS)
    connection.exec_driver_sql(f'GRANT SELECT({columns}) ON users TO "{role}"')
    tables = {"customers", "vendors", "products", "product_barcodes", "inventory", "stock_ledger", "invoices", "invoice_line_items", "invoice_payments",
        "purchase_invoices", "purchase_invoice_line_items", "journal_entries", "journal_lines", "business_settings", "period_locks", "idempotency_keys", "document_sequences",
        "b2b_connections", "b2b_invite_codes", "b2b_orders", "b2b_order_line_items", "b2b_ledgers", "document_party_snapshots", "table_alterations"}
    present = set(inspect(connection).get_table_names())
    for name in sorted(tables & present):
        connection.exec_driver_sql(f'GRANT SELECT,INSERT,UPDATE,DELETE ON "{name}" TO "{role}"')
    connection.exec_driver_sql(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
    for table in ("supplier_payments", "customer_refunds", "customer_credit_allocations", "register_shifts", "godowns"):
        if table in present:
            connection.exec_driver_sql(f'GRANT SELECT ON "{table}" TO "{role}"')
    for signature in ("bizassist_trade_policy(integer)", "bizassist_trade_lock_actor(integer)", "bizassist_network_state(integer)", "bizassist_public_id_taken(text)"):
        connection.exec_driver_sql(f'GRANT EXECUTE ON FUNCTION {signature} TO "{role}"')
