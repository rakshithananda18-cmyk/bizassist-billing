"""Bring Alembic-only installs to the same additive schema as desktop startup.

Revision ID: d60a4c1f3b05
Revises: c50f3b9e2a04
"""
from alembic import op
from sqlalchemy import inspect, text

revision = "d60a4c1f3b05"
down_revision = "c50f3b9e2a04"
branch_labels = None
depends_on = None


def upgrade():
    from database.db import Base
    import database.models
    from database.migration import _COLUMN_MIGRATIONS, _portable_ddl
    connection = op.get_bind()
    # Startup historically created operational tables that were absent from
    # the historical Alembic baseline. This creates only missing tables.
    Base.metadata.create_all(connection)
    # Use the existing portable declarations without the startup runner's
    # per-column commits or best-effort exception swallowing. Alembic owns one
    # transaction and any unexpected DDL failure aborts the migration visibly.
    for change in _COLUMN_MIGRATIONS:
        inspector = inspect(connection)
        table, column = change["table"], change["column"]
        if inspector.has_table(table) and column not in {c["name"] for c in inspector.get_columns(table)}:
            connection.execute(text(_portable_ddl(change["ddl"], connection.dialect.name)))
    from core.accounting.settlement_schema import install_financial_schema
    from core.party_archive_schema import install_party_archive_schema
    from database.change_feed import install_change_feed
    from database.security import install_security
    install_financial_schema(connection)
    install_party_archive_schema(connection)
    install_change_feed(connection)
    install_security(connection)


def downgrade():
    # These additive fields and tables can hold live financial and sync facts.
    # Reverting an application binary must never discard them automatically.
    pass
