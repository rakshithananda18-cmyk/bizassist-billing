"""
app/migration_scope.py — which tables this repo's Alembic chain may touch.

The database is shared with BizAssist Billing. Only `ft_*` tables are ours; an
autogenerate here must never see billing's tables (it would propose dropping
them), and billing's autogenerate must never see ours (see the matching filter
added to bizassist-billing/backend/alembic/env.py).
"""

VERSION_TABLE = "ft_alembic_version"


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return bool(name) and name.startswith("ft_")
    return True
