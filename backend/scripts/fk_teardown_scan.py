"""
scripts/fk_teardown_scan.py — read-only analysis. Safe to run anywhere.

Finds test fixtures that delete a parent table before the rows that reference it.

WHY IT EXISTS. N4 turned on SQLite foreign-key enforcement, which had always
defaulted to OFF — so every ForeignKey and every ondelete="CASCADE" in the models
was declared but never enforced on a local install, while the Postgres cloud
enforced them. Turning it on surfaced a latent class of bug in the SUITE:
teardowns that delete `invoices` or `products` while line items, payments or
barcodes still point at them. Those deletes appeared to work and were silently
orphaning rows.

Six files were failing and are fixed. This scan reports the rest, which pass today
only because the child table happens to be empty in that test. Consolidating these
teardowns onto services/admin_service.purge_business_data (already
dependency-ordered, and the single source of truth the admin wipe and local
reclaim both use) is the follow-up.

Reads no credentials, writes nothing, opens no network connection.

    python3 scripts/fk_teardown_scan.py <backend-dir>
"""

import os, re, sys

B = sys.argv[1]
sys.path.insert(0, B)
os.environ.setdefault("BIZASSIST_TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_scan2.db")
os.environ.setdefault("JWT_SECRET", "x")

import database.models, core.models  # noqa
from database.models import Base

# table -> set of child tables that FK to it
children = {}
for t in Base.metadata.sorted_tables:
    for fk in t.foreign_keys:
        children.setdefault(fk.column.table.name, set()).add(t.name)

# model class name -> table
cls2tbl = {m.class_.__name__: m.local_table.name
           for m in Base.registry.mappers if m.local_table is not None}
tbl2cls = {}
for c, t in cls2tbl.items():
    tbl2cls.setdefault(t, set()).add(c)

tests = os.path.join(B, "tests")
findings = []
for fn in sorted(os.listdir(tests)):
    if not fn.startswith("test_") or not fn.endswith(".py"):
        continue
    src = open(os.path.join(tests, fn), encoding="utf-8", errors="ignore").read()
    # every `query(X).…delete(` occurrence, in source order
    deleted = re.findall(r"query\(\s*([A-Za-z_][\w]*)\s*\)[^\n]*?\.delete\(", src)
    deleted += re.findall(r"DELETE\s+FROM\s+(\w+)", src, re.I)
    order = []
    for name in deleted:
        t = cls2tbl.get(name, name if name in children or name in tbl2cls else None)
        if t:
            order.append(t)
    seen = set()
    for i, t in enumerate(order):
        seen.add(t)
        for child in children.get(t, set()):
            if child == t:
                continue
            # child must be deleted earlier in the same file
            if child not in order[:i + 1]:
                # only report if the child table is one the file otherwise touches
                # OR is a hard NOT NULL FK (an orphan is then impossible to keep)
                col = None
                for fk in Base.metadata.tables[child].foreign_keys:
                    if fk.column.table.name == t:
                        col = fk.parent
                        break
                hard = col is not None and not col.nullable
                findings.append((fn, t, child, "NOT NULL FK" if hard else "nullable FK"))

hard = [f for f in findings if f[3] == "NOT NULL FK"]
print(f"test files scanned: {len([f for f in os.listdir(tests) if f.startswith('test_')])}")
print(f"parent-before-child deletions found: {len(findings)} ({len(hard)} via NOT NULL FK)")
print()
print("=== NOT NULL FK (an orphan cannot exist, so the DELETE will now fail) ===")
byfile = {}
for fn, t, child, kind in hard:
    byfile.setdefault(fn, set()).add(f"{t} <- {child}")
for fn in sorted(byfile):
    print(f"  {fn}: {', '.join(sorted(byfile[fn]))}")
