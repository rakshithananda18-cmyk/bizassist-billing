"""Retain shared B2B transactions and immutable document parties.

Revision ID: c50f3b9e2a04
Revises: b40e2c8d1f03
"""
from alembic import op

revision = "c50f3b9e2a04"
down_revision = "b40e2c8d1f03"
branch_labels = None
depends_on = None


def upgrade():
    from core.party_archive_schema import install_party_archive_schema
    from database.change_feed import install_change_feed
    install_party_archive_schema(op.get_bind())
    install_change_feed(op.get_bind())


def downgrade():
    # Removing retained evidence or making archived product references required
    # again would corrupt historical documents. Reverting the app is supported;
    # these additive fields and snapshots intentionally remain.
    pass
