"""Provision the separately configured platform administration service grants.

Revision ID: e70b5d2a4c06
Revises: d60a4c1f3b05
"""
from alembic import op

revision = "e70b5d2a4c06"
down_revision = "d60a4c1f3b05"
branch_labels = None
depends_on = None


def upgrade():
    from database.security import install_security
    install_security(op.get_bind())


def downgrade():
    # Credential revocation is a deliberate operator action. No financial or
    # synchronization evidence is removed by rolling back an application.
    pass
