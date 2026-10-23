"""The ft_* migration matches the models, and never claims billing's tables."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.billing_models import BillingBase
from app.db import Base, engine
from app.migration_scope import VERSION_TABLE, include_object
from tests.conftest import EXTERNAL_BILLING_SCHEMA


def test_migrated_schema_matches_models(client):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": include_object,
                                                     "version_table": VERSION_TABLE})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_own_version_table_and_billing_tables_untouched(client):
    tables = set(inspect(engine).get_table_names())
    assert VERSION_TABLE in tables
    if not EXTERNAL_BILLING_SCHEMA:
        assert "alembic_version" not in tables  # billing's chain is not ours to create
        mirrored = set(BillingBase.metadata.tables)  # billing tables a dev/test DB copies
        assert all(t.startswith("ft_") or t in mirrored for t in tables)


def test_include_object_ignores_billing_tables():
    assert include_object(None, "users", "table", True, None) is False
    assert include_object(None, "invoices", "table", True, None) is False
    assert include_object(None, "ft_tasks", "table", False, None) is True
