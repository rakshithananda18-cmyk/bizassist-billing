"""Relationship authorization and least-privilege B2B service sessions.

SQLite supplies the real rows and transactions. A pg_roles fixture and scalar
functions model the dedicated-role capability boundary; no external DB is used.
"""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import sessionmaker

from core.models import B2BConnection, B2BInviteCode, B2BOrder, BusinessSettings
from database import trade_service as trade
from database.db import Base
from database.models import Product, User
from services.dates import utc_now


@pytest.fixture
def network(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    locks, retired = [], set()

    def lock_actor(actor):
        locks.append(actor)
        return int(actor not in retired)

    @event.listens_for(engine, "connect")
    def capabilities(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function("bizassist_trade_lock_actor", 1, lock_actor)
        connection.create_function("bizassist_trade_policy", 1, lambda actor: json.dumps({"credit_limit": actor * 10}))

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE pg_roles (rolsuper BOOLEAN, rolbypassrls BOOLEAN, rolname TEXT, current_user TEXT)")
        connection.exec_driver_sql("INSERT INTO pg_roles VALUES (0,1,'trade_runtime','trade_runtime')")
    sessions = sessionmaker(bind=engine)
    ids = {}
    with sessions() as db:
        for name in ("buyer", "seller", "outsider"):
            owner = User(username=name, password="private-password", role="enterprise",
                         business_name=name, public_id=f"BA-TRADE-{name}", email=f"{name}@example.invalid",
                         gstin="private-tax-detail", settings='{"general":{"hosting_mode":"hybrid"}}')
            db.add(owner)
            db.flush()
            ids[name] = owner.id
        db.add(B2BConnection(buyer_business_id=ids["buyer"], seller_business_id=ids["seller"], status="accepted"))
        order = B2BOrder(buyer_business_id=ids["buyer"], seller_business_id=ids["seller"],
                         order_number="TRADE-ORDER", order_date="2026-11-01", total_amount=500)
        db.add(order)
        db.add(B2BInviteCode(seller_business_id=ids["seller"], code="INVITE-VALID",
                             expires_at=utc_now() + timedelta(days=1)))
        db.commit()
        ids["order"] = order.id
    monkeypatch.setenv("DATABASE_TRADE_SERVICE_URL", str(engine.url))
    monkeypatch.setattr(trade, "_ENGINES", {})
    # Each session uses the real relationship tables but the request's role is
    # constrained, so it must pass through the explicit service authorization.
    monkeypatch.setattr(trade, "_privileged", lambda db: False)
    # The dedicated-role adapter uses the same ephemeral relational fixture;
    # the production factory's cache and public-column projection remain real.
    def service_engine(*args, **kwargs):
        return engine

    monkeypatch.setattr(trade, "create_engine", service_engine)
    try:
        with sessions() as request:
            request.info["business_id"] = ids["buyer"]
            yield SimpleNamespace(engine=engine, sessions=sessions, request=request,
                                  ids=ids, locks=locks, retired=retired)
    finally:
        for cached in trade._ENGINES.values():
            cached.dispose()
        engine.dispose()


@pytest.mark.parametrize("operation", ["place_order", "catalog", "transition_order", "reconcile_order", "redeem_connection"])
def test_only_verified_partners_enter_scoped_trade_session(network, operation):
    ids = network.ids
    with trade.trade_session(network.request, actor_id=ids["buyer"], operation=operation,
                             seller_id=ids["seller"], order_id=ids["order"], code="INVITE-VALID") as service:
        assert service is not network.request
        scope = service.info["trade_authorized"]
        assert scope["buyer_id"] == ids["buyer"]
        assert scope["seller_id"] == ids["seller"]
        assert scope["actor_id"] == service.info["business_id"] == ids["buyer"]
        assert scope["operation"] == operation
        assert json.loads(trade.trade_policy(service, ids["seller"]))["credit_limit"] == ids["seller"] * 10
        with pytest.raises(HTTPException) as failure:
            trade.trade_policy(service, ids["outsider"])
        assert failure.value.status_code == 403
    assert network.locks == sorted([ids["buyer"], ids["seller"]]), "all commands must lock both parties in the same order"


@pytest.mark.parametrize("case", ["wrong_actor", "missing_actor", "unsupported", "unconnected", "retired", "staff"])
def test_invalid_actor_and_relationship_never_authorize_trade(network, case):
    ids = network.ids
    actor, seller, operation = ids["buyer"], ids["seller"], "catalog"
    if case == "wrong_actor":
        actor = ids["outsider"]
    elif case == "missing_actor":
        network.request.info.clear()
    elif case == "unsupported":
        operation = "delete_business"
    elif case == "unconnected":
        seller = ids["outsider"]
    elif case == "retired":
        with network.sessions() as db:
            db.get(User, actor).role = "retired"
            db.commit()
    elif case == "staff":
        with network.sessions() as db:
            db.get(User, actor).parent_business_id = ids["seller"]
            db.commit()
    from database.db import current_business_id_var
    guard = current_business_id_var.set(None)
    try:
        with pytest.raises(HTTPException) as failure:
            with trade.trade_session(network.request, actor_id=actor, operation=operation, seller_id=seller):
                pytest.fail("an unauthorized relationship entered the trade body")
        assert failure.value.status_code == (401 if case == "missing_actor" else 403)
    finally:
        current_business_id_var.reset(guard)


@pytest.mark.parametrize("operation,actor", [("transition_order", "outsider"), ("reconcile_order", "seller")])
def test_order_commands_cannot_read_another_business_or_reconcile_its_purchase(network, operation, actor):
    actor_id = network.ids[actor]
    network.request.info["business_id"] = actor_id
    with pytest.raises(HTTPException) as failure:
        with trade.trade_session(network.request, actor_id=actor_id, operation=operation,
                                 order_id=network.ids["order"]):
            pytest.fail("order command crossed its authenticated business")
    assert failure.value.status_code == 403


@pytest.mark.parametrize("invalid", ["missing", "expired", "used"])
def test_invitation_replay_and_expiry_are_rejected_before_authorization(network, invalid):
    with network.sessions() as db:
        invite = db.query(B2BInviteCode).one()
        if invalid == "expired":
            invite.expires_at = utc_now() - timedelta(seconds=1)
        elif invalid == "used":
            invite.is_used = True
        db.commit()
    with pytest.raises(HTTPException) as failure:
        with trade.trade_session(network.request, actor_id=network.ids["buyer"], operation="redeem_connection",
                                 code="UNKNOWN" if invalid == "missing" else "INVITE-VALID"):
            pytest.fail("unusable invitation entered the trade body")
    assert failure.value.status_code == 403
    assert not network.locks


def test_relationship_retired_during_lock_is_rejected_and_uncommitted_changes_rollback(network):
    network.retired.add(network.ids["seller"])
    with pytest.raises(HTTPException) as failure:
        with trade.trade_session(network.request, actor_id=network.ids["buyer"], operation="catalog", seller_id=network.ids["seller"]):
            pytest.fail("retired partner authorized after lock")
    assert failure.value.status_code == 403
    network.retired.clear()
    with pytest.raises(RuntimeError, match="synthetic posting failure"):
        with trade.trade_session(network.request, actor_id=network.ids["buyer"], operation="place_order", seller_id=network.ids["seller"]) as service:
            service.query(B2BOrder).filter_by(id=network.ids["order"]).update({"total_amount": 999})
            raise RuntimeError("synthetic posting failure")
    with network.sessions() as db:
        assert db.get(B2BOrder, network.ids["order"]).total_amount == 500


def test_service_projects_public_party_columns_and_reuses_only_configured_pool(network):
    with trade._open_service() as first:
        owner = first.query(User).filter_by(id=network.ids["seller"]).one()
        assert owner.business_name == "seller"
        assert owner.email == "seller@example.invalid"
        with pytest.raises(InvalidRequestError, match="raiseload"):
            _ = owner.password
        with pytest.raises(InvalidRequestError, match="raiseload"):
            _ = owner.settings
    with trade._open_service() as second:
        assert second.bind is first.bind
    assert len(trade._ENGINES) == 1


@pytest.mark.parametrize("superuser,bypass", [(True, True), (False, False)])
def test_service_refuses_misconfigured_privileged_or_non_trade_credentials(network, superuser, bypass):
    with network.engine.begin() as connection:
        connection.execute(text("UPDATE pg_roles SET rolsuper=:s,rolbypassrls=:b"), {"s": superuser, "b": bypass})
    with pytest.raises(HTTPException) as failure:
        trade._open_service()
    assert failure.value.status_code == 503


def test_missing_service_credentials_fail_closed(network, monkeypatch):
    monkeypatch.delenv("DATABASE_TRADE_SERVICE_URL")
    with pytest.raises(HTTPException) as failure:
        trade._open_service()
    assert failure.value.status_code == 503


def test_an_already_authorized_service_is_not_opened_again(network, monkeypatch):
    network.request.info["trade_authorized"] = {"actor_id": network.ids["buyer"]}
    monkeypatch.setattr(trade, "_open_service", lambda: pytest.fail("nested trade opened another privileged session"))
    with trade.trade_session(network.request, actor_id=network.ids["buyer"], operation="catalog") as service:
        assert service is network.request


def test_public_business_profile_does_not_expose_partner_contact_details_without_connection(network, monkeypatch):
    # The facade models the HTTP runtime's PostgreSQL metadata function. The
    # dedicated service still executes real ORM queries with a public projection.
    actor = network.ids["buyer"]
    request = SimpleNamespace(info={"business_id": actor},
                              bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
                              execute=lambda *a, **k: SimpleNamespace(scalar=lambda: {"hosting_mode": "hybrid", "business_type": "wholesale"}))
    outsider = trade.business_profile(request, id=network.ids["outsider"])
    assert outsider.public_id == "BA-TRADE-outsider"
    assert outsider.email is None and outsider.gstin is None and outsider.username is None
    partner = trade.business_profile(request, bizid="BA-TRADE-seller")
    assert partner.email == "seller@example.invalid"
    assert partner.gstin == "private-tax-detail"
    assert partner.hosting_mode == "hybrid" and partner.business_type == "wholesale"
    assert not hasattr(partner, "password") and not hasattr(partner, "settings")
    assert trade.business_profile(request, id=999999) is None


def test_authorized_catalog_applies_partner_pricing_without_exposing_another_seller(network):
    with network.sessions() as db:
        db.query(B2BConnection).one().price_tier = "wholesale"
        db.query(B2BConnection).one().discount_pct = 10
        db.add_all([Product(business_id=network.ids["seller"], name="Partner item", selling_price=100, wholesale_price=80),
                    Product(business_id=network.ids["outsider"], name="Unrelated seller item", selling_price=1)])
        db.commit()
    catalogue = trade.authorized_catalog(network.request, network.ids["seller"])
    assert [row["name"] for row in catalogue] == ["Partner item"]
    assert catalogue[0]["selling_price"] == 72
    assert catalogue[0]["original_selling_price"] == 100


def test_local_profile_reads_vertical_and_falls_back_safely_when_settings_are_corrupt(network, monkeypatch):
    monkeypatch.setattr(trade, "_privileged", lambda db: True)
    with network.sessions() as db:
        buyer = db.get(User, network.ids["buyer"])
        db.add(BusinessSettings(business_id=buyer.id, template_key="pharmacy"))
        db.commit()
        profile = trade.business_profile(db, id=buyer.id)
        assert profile.hosting_mode == "hybrid"
        assert profile.business_type == "pharmacy"
        buyer.settings = "not-json"
        db.commit()
        assert trade.business_profile(db, id=buyer.id).hosting_mode == "local"


def test_trade_role_grants_public_fields_and_never_login_credentials(network, monkeypatch):
    import sqlalchemy
    grants = []
    connection = SimpleNamespace(
        execute=lambda *a, **k: SimpleNamespace(first=lambda: (False, True)),
        exec_driver_sql=grants.append,
    )
    monkeypatch.setattr(sqlalchemy, "inspect", lambda target: inspect(network.engine))
    trade.install_trade_role(connection, "isolated_trade_role")
    user_grant = next(statement for statement in grants if statement.startswith("GRANT SELECT(") and " ON users " in statement)
    assert '"public_id"' in user_grant
    assert all(f'"{secret}"' not in user_grant for secret in ("password", "settings", "token_version", "google_id"))
    assert any('REVOKE ALL ON users' in statement for statement in grants)
    assert any('"b2b_orders"' in statement for statement in grants)
    assert all('GRANT SELECT,INSERT,UPDATE,DELETE ON "users"' not in statement for statement in grants)
    with pytest.raises(ValueError, match="Invalid trade role"):
        trade.install_trade_role(connection, 'role"; DROP TABLE users; --')
    unsafe = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(first=lambda: (True, True)))
    with pytest.raises(ValueError, match="NOSUPERUSER"):
        trade.install_trade_role(unsafe, "superuser_role")
