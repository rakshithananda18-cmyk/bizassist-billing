"""Shared-cloud Field data cleanup, within Billing's existing purge transaction.

Field owns its schema/migrations; Billing must not import that separate service.
Only these known tables are reflected. Local Billing databases normally have none.
"""
import logging

from fastapi import HTTPException
from sqlalchemy import MetaData, Table, delete, inspect, or_, select, text

logger = logging.getLogger("bizassist.field_cleanup")

DELETE_ORDER = (
    "ft_task_invoices", "ft_points_ledger", "ft_activity", "ft_location_pings",
    "ft_attendance", "ft_item_requests", "ft_tasks", "ft_run_stops", "ft_runs",
    "ft_route_stops", "ft_routes", "ft_staff", "ft_shops", "ft_settings",
)
REFERENCES = {
    "ft_task_invoices": {"task_id": "ft_tasks"},
    "ft_points_ledger": {"staff_id": "ft_staff", "task_id": "ft_tasks", "attendance_id": "ft_attendance"},
    "ft_activity": {"staff_id": "ft_staff"},
    "ft_location_pings": {"staff_id": "ft_staff"},
    "ft_attendance": {"staff_id": "ft_staff"},
    "ft_item_requests": {"staff_id": "ft_staff", "shop_id": "ft_shops", "run_stop_id": "ft_run_stops"},
    "ft_tasks": {"staff_id": "ft_staff", "shop_id": "ft_shops", "run_id": "ft_runs", "run_stop_id": "ft_run_stops"},
    "ft_run_stops": {"run_id": "ft_runs", "shop_id": "ft_shops"},
    "ft_runs": {"staff_id": "ft_staff", "route_id": "ft_routes"},
    "ft_route_stops": {"route_id": "ft_routes", "shop_id": "ft_shops"},
    "ft_routes": {"default_staff_id": "ft_staff"},
}


def purge_field_business(db, business_id: int) -> dict:
    """Delete one verified business's Field tree; never commit independently.

    A cross-business child reference could trigger ON DELETE CASCADE/SET NULL
    into someone else's records. Refuse before any delete, even for nullable
    references. Unknown future tables/schema require an explicit cleanup update.
    """
    connection = db.connection()
    inspector = inspect(connection)
    present = {name for name in inspector.get_table_names()
               if name.startswith("ft_") and name != "ft_alembic_version"}
    if not present:
        return {}
    if present - set(DELETE_ORDER):
        raise HTTPException(409, "Business deletion stopped: the Field schema has unsupported tables. Update the cleanup service before retrying.")

    # Preflights must see ALL referencing tenants. Do not infer safety from an
    # RLS-filtered empty result. This check does not disable or change any policy.
    if connection.dialect.name == "postgresql":
        restricted = connection.execute(text("""
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_roles r ON r.rolname = current_user
            WHERE n.nspname = current_schema() AND c.relname = ANY(:tables)
              AND c.relrowsecurity AND NOT (r.rolsuper OR r.rolbypassrls)
              AND (c.relforcerowsecurity OR c.relowner <> r.oid) LIMIT 1
        """), {"tables": list(present)}).first()
        if restricted:
            raise HTTPException(409, "Business deletion stopped: Field reference validation requires a maintenance role with full table visibility.")

    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=connection, resolve_fks=False)
              for name in DELETE_ORDER if name in present}
    for name, table in tables.items():
        required = {"id", "business_id", *REFERENCES.get(name, {})}
        if not required.issubset(table.c.keys()):
            raise HTTPException(409, "Business deletion stopped: an unsupported Field table layout needs review.")
        for column, parent_name in REFERENCES.get(name, {}).items():
            if parent_name not in tables:
                raise HTTPException(409, "Business deletion stopped: a Field parent table is missing. Complete its migrations before retrying.")
            parent = tables[parent_name]
            foreign_child = connection.execute(select(table.c.id).where(
                or_(table.c.business_id != business_id, table.c.business_id.is_(None)),
                table.c[column].in_(select(parent.c.id).where(parent.c.business_id == business_id)),
            ).limit(1)).first()
            if foreign_child:
                raise HTTPException(409, "Business deletion stopped: another business has a Field reference to this account's records. Repair that reference before retrying; nothing was deleted.")

    # Also reject schema drift that introduces an unmodelled Field FK edge.
    # Otherwise our documented delete order might activate a foreign cascade.
    for name in tables:
        for foreign_key in inspector.get_foreign_keys(name):
            parent = foreign_key.get("referred_table")
            if not parent or not parent.startswith("ft_"):
                continue
            columns = foreign_key.get("constrained_columns", [])
            if (len(columns) != 1 or foreign_key.get("referred_columns") != ["id"]
                    or REFERENCES.get(name, {}).get(columns[0]) != parent):
                raise HTTPException(409, "Business deletion stopped: unsupported Field relationships need a cleanup service update.")

    deleted = {}
    for name in DELETE_ORDER:
        if name in tables:
            table = tables[name]
            result = connection.execute(delete(table).where(table.c.business_id == business_id))
            deleted[name] = result.rowcount
    logger.info("[FIELD_PURGE] business=%s deleted=%s", business_id, deleted)
    return deleted
