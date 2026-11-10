"""Refresh unique owner/Google lookup and tenant-scoped phone authentication."""
from alembic import op

revision = "h5_account_identity_bootstrap"
down_revision = "h4_auth_admin_runtime_state"
branch_labels = None
depends_on = None


def upgrade():
    from database.security import install_security
    install_security(op.get_bind())


def downgrade():
    # Additive, private lookup helpers are safe to retain for older app revisions.
    pass
