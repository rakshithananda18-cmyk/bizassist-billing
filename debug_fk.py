"""Debug: check what SQLAlchemy's FK introspection returns for invoice_line_items on SQLite."""
import sys
sys.path.insert(0, 'backend')
from database.db import engine
from sqlalchemy import inspect

insp = inspect(engine)
fks = insp.get_foreign_keys('invoice_line_items')
print("Foreign keys for invoice_line_items:")
for fk in fks:
    print(" ", fk)

# Also check what we actually get for fk_targets (the filter used in import)
fk_targets = [
    (fk["constrained_columns"][0], fk["referred_table"])
    for fk in fks
    if len(fk.get("constrained_columns", [])) == 1
    and fk.get("referred_columns") == ["id"]
]
print("\nfk_targets (used for remapping):", fk_targets)
