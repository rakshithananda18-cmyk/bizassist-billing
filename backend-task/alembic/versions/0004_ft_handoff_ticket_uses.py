"""Persist consumed hand-off digests so restarts cannot permit ticket replay."""
import os
import re

from alembic import op
import sqlalchemy as sa

revision = "0004_ft_handoff_ticket_uses"
down_revision = "0003_ft_task_payment"
branch_labels = None
depends_on = None
TABLE = "ft_handoff_ticket_uses"


def upgrade():
    op.create_table(TABLE,
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("digest", name=op.f("pk_ft_handoff_ticket_uses")),
    )
    op.create_index("ix_ft_handoff_ticket_uses_business_id", TABLE, ["business_id"])
    op.create_index("ix_ft_handoff_ticket_uses_expires_at", TABLE, ["expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        bid = "nullif(current_setting('app.current_business_id', true), '')::integer"
        op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {TABLE}_tenant_isolation ON public.{TABLE} USING (business_id = {bid}) WITH CHECK (business_id = {bid})")
        role = os.environ.get("BIZASSIST_RUNTIME_DB_ROLE", "")
        if role:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", role):
                raise ValueError("Invalid BIZASSIST_RUNTIME_DB_ROLE")
            op.execute(f'GRANT SELECT, INSERT, DELETE ON TABLE public.{TABLE} TO "{role}"')


def downgrade():
    op.drop_index("ix_ft_handoff_ticket_uses_expires_at", table_name=TABLE)
    op.drop_index("ix_ft_handoff_ticket_uses_business_id", table_name=TABLE)
    op.drop_table(TABLE)
