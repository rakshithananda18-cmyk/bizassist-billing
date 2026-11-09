"""Tests for Field business data cleanup with ft_handoff_ticket_uses."""
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session

from services.field_business_cleanup import DELETE_ORDER, purge_field_business


def test_delete_order_contains_handoff_ticket_uses():
    assert "ft_handoff_ticket_uses" in DELETE_ORDER


def test_purge_field_business_cleans_handoff_ticket_uses():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    # Create tables
    ticket_table = Table(
        "ft_handoff_ticket_uses",
        metadata,
        Column("digest", String(64), primary_key=True),
        Column("business_id", Integer, nullable=False, index=True),
        Column("expires_at", Integer, nullable=False),
    )
    settings_table = Table(
        "ft_settings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("business_id", Integer, nullable=False),
    )
    metadata.create_all(engine)

    with Session(engine) as session:
        # Seed test data for business 10 and business 20
        session.execute(ticket_table.insert().values([
            {"digest": "hash10_a", "business_id": 10, "expires_at": 1800000000},
            {"digest": "hash10_b", "business_id": 10, "expires_at": 1800000000},
            {"digest": "hash20_a", "business_id": 20, "expires_at": 1800000000},
        ]))
        session.execute(settings_table.insert().values([
            {"id": 1, "business_id": 10},
            {"id": 2, "business_id": 20},
        ]))
        session.commit()

        # Purge business 10
        deleted = purge_field_business(session, 10)
        assert deleted.get("ft_handoff_ticket_uses") == 2
        assert deleted.get("ft_settings") == 1

        # Verify business 20 data was untouched
        remaining_tickets = session.execute(ticket_table.select()).fetchall()
        assert len(remaining_tickets) == 1
        assert remaining_tickets[0].digest == "hash20_a"
        assert remaining_tickets[0].business_id == 20

        remaining_settings = session.execute(settings_table.select()).fetchall()
        assert len(remaining_settings) == 1
        assert remaining_settings[0].business_id == 20
