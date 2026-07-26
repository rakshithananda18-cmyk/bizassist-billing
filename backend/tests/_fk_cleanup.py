"""
tests/_fk_cleanup.py — delete rows in foreign-key order, derived from metadata.
=============================================================================
WHY THIS EXISTS

N4 turned on SQLite foreign-key enforcement, which had always defaulted to OFF —
so every `ForeignKey` and `ondelete="CASCADE"` in the models was declared but
never enforced on a local install, while the Postgres cloud enforced them. It also
means the live database had accumulated 18 genuinely orphaned rows.

Enforcement surfaced a latent class of bug in the fixtures: teardowns that delete
a parent while rows still reference it. Most were fixed by putting the deletes in
the right order by hand. Three files could not be fixed that way, and the reason
is the interesting part:

    tests/test_import.py
    tests/test_import_preview_contacts.py
    tests/test_rag.py

They issue **unfiltered, global** deletes — `db.query(Product).delete()`,
`db.query(Customer).delete()`, even `db.query(User).delete()`. The whole suite
shares one SQLite file, so those statements collide with rows written by
*completely unrelated modules*: a product deleted here is still referenced by a
purchase line item from `test_purchases`, a customer by an invoice from
`test_billing`, a user by a register shift from `test_shifts`.

Which means the correct delete order for these fixtures is **not a property of
the module** — it is a property of the whole schema. Hand-maintaining that list
is how it goes stale: it has to be re-checked every time any model gains a
foreign key, in three files, by someone who is not thinking about foreign keys.

So the order is not written down here either. It is **derived from
`Base.metadata.sorted_tables`**, which SQLAlchemy topologically sorts
parents-before-children; reversed, that is exactly a safe deletion order, and it
updates itself when a model is added. Same instinct as extracting `MODEL_MAP` to
a shared module (R-7) and post-apply invariants to `core/sync/apply_hooks.py`
(rule 12): one derivation, no copies.

A NOTE ON WHY THIS WAS NOT CAUGHT EARLIER

The FK change was verified in chunked runs (the environment could not hold one
full session), and in a chunk these three files pass — the modules whose rows they
collide with simply were not present. A full serial run found them immediately.
Partial runs cannot see cross-module interaction, and that limitation is worth
stating rather than discovering twice.
"""
from __future__ import annotations

# Tables a fixture almost never wants to truncate, because module-scoped
# fixtures create them once and every test in the file depends on them.
DEFAULT_KEEP = frozenset({
    "alembic_version",
    "business_tombstones",   # deliberately append-only history
})


def _ordered_tables(keep):
    """Child-before-parent deletion order, straight from the mapper metadata."""
    from database.models import Base
    import database.models  # noqa: F401 — registers the main tables
    import core.models      # noqa: F401 — registers B2B / journal tables

    return [t for t in reversed(Base.metadata.sorted_tables) if t.name not in keep]


def wipe_all(db, *, keep_users: bool = True, keep: frozenset = DEFAULT_KEEP) -> None:
    """Truncate every table, children first. Commits.

    ``keep_users=True`` (the default) preserves the `users` rows, because almost
    every fixture signs up its businesses once at module scope and would break if
    the accounts vanished between tests. Pass False for the rare fixture that
    really does want the accounts gone too.

    Uses core-level ``table.delete()`` rather than ORM ``query(Model).delete()``:
    the point is a mechanical truncation in a known order, and going through the
    ORM would drag in relationship cascades that reorder the very thing being
    controlled here.
    """
    skip = set(keep) | ({"users"} if keep_users else set())
    for table in _ordered_tables(skip):
        db.execute(table.delete())
    db.commit()


def wipe_tables(db, *names: str, keep: frozenset = DEFAULT_KEEP) -> None:
    """Truncate the named tables AND everything that references them, in order.

    For a fixture that wants "clear the catalog and anything hanging off it"
    without naming the dozen child tables — which is what the three files above
    were trying to express and getting wrong.
    """
    from database.models import Base
    import database.models  # noqa: F401
    import core.models      # noqa: F401

    wanted = set(names)
    # Transitively pull in every table that FKs into a wanted table.
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.sorted_tables:
            if table.name in wanted:
                continue
            if any(fk.column.table.name in wanted for fk in table.foreign_keys):
                wanted.add(table.name)
                changed = True

    for table in _ordered_tables(set(keep)):
        if table.name in wanted:
            db.execute(table.delete())
    db.commit()
