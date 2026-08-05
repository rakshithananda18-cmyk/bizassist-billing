"""
tests/test_no_unresolved_local_ids.py
=====================================
RATCHET GUARD for one rule: an integer id is meaningful ONLY inside the database
that issued it.

`_serialize_orm_obj` copies every column verbatim and only translates a value to
a portable `uid` when the column is a DECLARED ForeignKey whose parent table has
a `uid`. So a plain `Column(Integer)` named `*_id` is pushed as a raw local
integer. Both databases number their rows independently, so such a value does
not merely go stale upstream — it lands on a REAL, UNRELATED row.

That is not hypothetical: `file_id` was doing exactly this, and
`DELETE /upload/{file_id}` purges by that column, so deleting an upload on the
cloud could purge inventory from a different device's import (fixed by
LOCAL_ONLY_COLUMNS — see database/sync_map.py).

This test does NOT claim the codebase is clean. It pins the CURRENT set so a new
one cannot be added silently, and it names every entry with the reason it is
either safe or still open. Shrinking KNOWN_UNRESOLVED is the point; growing it
requires writing down why.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from sqlalchemy import Integer                                      # noqa: E402
from database.sync_map import (                                     # noqa: E402
    MODEL_MAP, PULL_ONLY_TABLES, LOCAL_ONLY_COLUMNS,
    _USER_FK_REPOINT_ENTITIES,
)

# Columns that carry an integer id across the boundary without uid resolution.
#
# ── STILL OPEN (real, unfixed) ───────────────────────────────────────────────
#   reference_id — polymorphic (points at an invoice, a purchase, a transfer …
#     depending on a sibling type column), so no single ForeignKey can express
#     it. Needs a type-aware resolver, or to be dropped from the payload the way
#     `file_id` was.
#
# ── SAFE, with the mechanism that makes them safe ────────────────────────────
#   *_business_id  → re-pinned to the receiving database's own id by the four
#                    BizID gates (routes/sync.py, services/sync_worker.py).
#   user_id        → covered by _USER_FK_REPOINT_ENTITIES.
#   anything on a  → PULL_ONLY table is never pushed from local at all.
#
# `godown_id` was here across five tables and is now FIXED: declaring
# ForeignKey("godowns.id") wires it into the existing uid path on both sides.
KNOWN_UNRESOLVED = {
    ("stock_ledger", "reference_id"),
}


def _unresolved_columns():
    """Every synced, pushable column holding an unresolvable foreign integer."""
    found = set()
    for table, model in MODEL_MAP.items():
        # Never pushed from local, so a local integer cannot escape this way.
        if table in PULL_ONLY_TABLES:
            continue
        for col in model.__table__.columns:
            if not isinstance(col.type, Integer) or not col.name.endswith("_id"):
                continue
            # Own PK, the tenant column, and columns stripped before push.
            if col.name in ("id", "business_id") or col.name in LOCAL_ONLY_COLUMNS:
                continue
            # Explicitly re-pointed against the receiving database's users table.
            if col.name == "user_id" and table in _USER_FK_REPOINT_ENTITIES:
                continue

            fks = list(col.foreign_keys)
            if not fks:
                found.add((table, col.name))
            elif any(fk.column.table.name == "users" for fk in fks):
                # A business/user reference: re-pinned by the BizID gates.
                continue
            elif not all(fk.column.table.name in MODEL_MAP for fk in fks):
                found.add((table, col.name))
    return found


def test_no_new_unresolved_local_ids():
    found = _unresolved_columns()

    new = found - KNOWN_UNRESOLVED
    assert not new, (
        "New column(s) push a LOCAL integer id across the sync boundary, where "
        "that number belongs to a different row: "
        + ", ".join(f"{t}.{c}" for t, c in sorted(new))
        + ". Declare a ForeignKey to a synced, uid-bearing parent so "
          "_serialize_orm_obj can translate it, or add the column to "
          "LOCAL_ONLY_COLUMNS so it is stripped before push."
    )


def test_known_unresolved_list_is_not_stale():
    """If one gets fixed, this fails until the entry is removed — so the list
    cannot quietly rot into a set of names nobody has checked in a year."""
    found = _unresolved_columns()
    fixed = KNOWN_UNRESOLVED - found
    assert not fixed, (
        "These are no longer unresolved — delete them from KNOWN_UNRESOLVED: "
        + ", ".join(f"{t}.{c}" for t, c in sorted(fixed))
    )
