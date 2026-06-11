"""backfill: normalize existing dates to ISO and statuses to canonical case (H3)

Data-only migration. Rewrites already-stored rows so old data matches what new
uploads now produce:
  - invoices.invoice_date / invoices.due_date  -> ISO YYYY-MM-DD
  - invoices.status                            -> canonical case (Paid/Pending/...)
  - inventory.expiry_date                      -> ISO
  - payments.due_date                          -> ISO

Unparseable values are left exactly as-is (nothing is dropped). Only rows that
actually change are written. Reuses services.normalize so the logic matches the
ingest path (and is unit-tested in tests/test_normalize.py).

Revision ID: a7c4e9f02b13
Revises: c0017902b685
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c4e9f02b13"
down_revision = "c0017902b685"
branch_labels = None
depends_on = None


def _backfill(bind, table, updates):
    """
    updates: dict of column -> normalizer(value). Reads id + those columns,
    applies the normalizers, and UPDATEs only the rows that changed.
    """
    cols = ", ".join(["id", *updates.keys()])
    rows = bind.execute(sa.text(f"SELECT {cols} FROM {table}")).mappings().all()
    for row in rows:
        changes = {}
        for col, fn in updates.items():
            new_val = fn(row[col])
            if new_val != row[col]:
                changes[col] = new_val
        if changes:
            set_clause = ", ".join(f"{c} = :{c}" for c in changes)
            params = {**changes, "id": row["id"]}
            bind.execute(sa.text(f"UPDATE {table} SET {set_clause} WHERE id = :id"), params)


def upgrade() -> None:
    # Import here so the migration uses the same normalizers as the app ingest.
    from services.normalize import to_iso, normalize_status

    bind = op.get_bind()
    _backfill(bind, "invoices", {
        "invoice_date": to_iso,
        "due_date":     to_iso,
        "status":       normalize_status,
    })
    _backfill(bind, "inventory", {
        "expiry_date": to_iso,
    })
    _backfill(bind, "payments", {
        "due_date": to_iso,
    })


def downgrade() -> None:
    # Irreversible: the original (mixed-format) values are not retained.
    pass
