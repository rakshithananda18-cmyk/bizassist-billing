"""b2b connection approval flow: pending status + requester tracking

Closes the Jul-2026 review finding F-1/F-2:

  F-1  ``create_direct_connection`` wrote ``status="accepted"`` immediately, so
       ANYONE holding a business's (deliberately public) BizID could open a
       connection and instantly read the whole catalog — including tiered
       pricing and exact on-hand stock — with no consent from the owner.

  F-2  Re-POSTing the same connect request flipped an existing ``revoked`` row
       back to ``accepted``, letting a revoked party restore its own access.

Schema changes (all additive, all reversible):

  1. ``requested_by_business_id``  — who initiated the link. Lets the API answer
     "is this mine to approve, or am I waiting on them?" without inferring
     direction from the buyer/seller roles (either side may initiate).
  2. ``request_message``          — optional note from the requester.
  3. ``responded_at``             — when the counterparty approved/rejected.
  4. index on ``status``          — the connections list now filters by status
     on every load (Approved / Pending / Sent tabs).

DATA POLICY — existing rows are NOT touched. Every connection created under the
old auto-accept behaviour keeps ``status='accepted'``; back-dating them to
'pending' would silently break live supplier relationships and strand in-flight
orders. The new consent rule applies to connections created from here on.
``requested_by_business_id`` is backfilled to NULL for those rows, which the API
renders as "legacy link" rather than guessing.

IDEMPOTENT: guarded by column-existence checks, because tests build the schema
via ``Base.metadata.create_all()`` (which already includes these columns) before
the migration chain runs.

Revision ID: e5c9a1d7b3f2
Revises: d1f4a2c8e6b0
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e5c9a1d7b3f2"
down_revision = "d1f4a2c8e6b0"
branch_labels = None
depends_on = None

_TABLE = "b2b_connections"
_INDEX = "ix_b2b_connections_status"


def _cols() -> set:
    insp = inspect(op.get_bind())
    try:
        return {c["name"] for c in insp.get_columns(_TABLE)}
    except Exception:
        return set()


def _has_table() -> bool:
    try:
        return inspect(op.get_bind()).has_table(_TABLE)
    except Exception:
        return False


def _index_names() -> set:
    try:
        return {i["name"] for i in inspect(op.get_bind()).get_indexes(_TABLE)}
    except Exception:
        return set()


def upgrade() -> None:
    if not _has_table():
        # Fresh DB where create_all hasn't run yet — the model DDL will create
        # the table with every column already present.
        return

    existing = _cols()

    if "requested_by_business_id" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("requested_by_business_id", sa.Integer(), nullable=True),
        )

    if "request_message" not in existing:
        op.add_column(_TABLE, sa.Column("request_message", sa.Text(), nullable=True))

    if "responded_at" not in existing:
        op.add_column(_TABLE, sa.Column("responded_at", sa.DateTime(), nullable=True))

    if _INDEX not in _index_names():
        op.create_index(_INDEX, _TABLE, ["status"])

    # Legacy rows: anything already linked stays linked and is treated as
    # already-responded, so the UI never shows a historical connection sitting
    # in an "awaiting approval" tab.
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} "
            "SET responded_at = COALESCE(responded_at, updated_at, created_at) "
            "WHERE status = 'accepted' AND responded_at IS NULL"
        )
    )


def downgrade() -> None:
    if not _has_table():
        return

    if _INDEX in _index_names():
        op.drop_index(_INDEX, table_name=_TABLE)

    existing = _cols()
    # Any connection still awaiting a decision has no representation in the old
    # schema; the old code would have treated it as live. Reject-on-downgrade is
    # the safe direction (deny rather than silently grant catalog access).
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE status IN ('pending', 'rejected')"))

    for col in ("responded_at", "request_message", "requested_by_business_id"):
        if col in existing:
            op.drop_column(_TABLE, col)
