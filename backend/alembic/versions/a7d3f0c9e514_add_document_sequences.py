"""add document_sequences (monotonic invoice / credit-note numbering, F-3)

Additive + backward-compatible: one NEW table, no change to any existing table.

WHY
---
Auto-generated document numbers used to be ``COUNT(rows in series) + 1``, so
deleting an invoice made the next sale reissue a number that had already been
used. Rule 46 of the CGST Rules requires a tax invoice's serial number to be
unique for the financial year, so that is a compliance breach as well as a
corrupted audit trail (two bills, one number). The counter now lives here, is
stored rather than derived, and only ever moves up — deletions cannot walk it
backwards. See core.models.DocumentSequence and core/billing/sequence.py.

BACKFILL
--------
The upgrade seeds one row per existing (business, series) at that series'
highest number already in use, so an install carrying INV-0001…INV-0123
continues at INV-0124 rather than restarting at INV-0001 and colliding with
every number it has ever issued. Series are discovered from the data — each
POS terminal has its own prefix (§9.3) and they are not enumerated anywhere.

Numbers that do not match ``<series>-<digits>`` are ignored by the seed. They
cannot advance a counter, and the runtime allocator's collision check still
refuses to reuse them.

IDEMPOTENT: `Base.metadata.create_all()` at import may already have created the
table (tests run on a fresh SQLite via create_all), so the create is guarded by
a has_table check and the backfill only inserts series it does not already have.

Revision ID: a7d3f0c9e514
Revises: f6a2d8c4b1e9
Create Date: 2026-07-26
"""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "a7d3f0c9e514"
down_revision = "f6a2d8c4b1e9"
branch_labels = None
depends_on = None


TABLE = "document_sequences"

# A document number is "<series>-<digits>" — series may itself contain dashes
# ("LCL-C1-0005" is series "LCL-C1", number 5), so the split is on the LAST dash.
_NUMBER_RE = re.compile(r"^(?P<series>.+)-(?P<n>\d+)$")


def _has_table(table: str) -> bool:
    insp = inspect(op.get_bind())
    try:
        return insp.has_table(table)
    except Exception:
        return False


def _create(bind) -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("business_id", sa.Integer(), nullable=False, index=True),
        sa.Column("series", sa.String(length=40), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("business_id", "series", name="uq_docseq_biz_series"),
    )
    op.create_index("ix_docseq_biz_series", TABLE, ["business_id", "series"])


def _seed(bind) -> None:
    """Set every existing (business, series) counter to its highest issued number."""
    if not _has_table("invoices"):
        return

    # Only series we don't already track — this migration must be re-runnable and
    # must never LOWER a counter that the running app has already advanced.
    known = {
        (int(b), s)
        for b, s in bind.execute(text(f"SELECT business_id, series FROM {TABLE}")).fetchall()
    }

    highest: dict = {}
    rows = bind.execute(text(
        "SELECT business_id, invoice_id FROM invoices "
        "WHERE business_id IS NOT NULL AND invoice_id IS NOT NULL"
    )).fetchall()
    for business_id, invoice_id in rows:
        m = _NUMBER_RE.match(str(invoice_id).strip())
        if not m:
            continue
        key = (int(business_id), m.group("series"))
        n = int(m.group("n"))
        if n > highest.get(key, 0):
            highest[key] = n

    for (business_id, series), last in sorted(highest.items()):
        if (business_id, series) in known or len(series) > 40:
            continue
        bind.execute(
            text(f"INSERT INTO {TABLE} (business_id, series, last_number) "
                 f"VALUES (:b, :s, :n)"),
            {"b": business_id, "s": series, "n": last},
        )


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(TABLE):
        _create(bind)
    _seed(bind)


def downgrade() -> None:
    if _has_table(TABLE):
        try:
            op.drop_index("ix_docseq_biz_series", table_name=TABLE)
        except Exception:
            pass
        op.drop_table(TABLE)
