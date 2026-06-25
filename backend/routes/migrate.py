"""
routes/migrate.py
=================
Phase 1 – Hosting-mode data migration endpoints.

Provides three authenticated endpoints:
  GET  /api/migrate/export   – dump all tenant tables to JSON
  POST /api/migrate/import   – restore from that JSON (upsert)
  GET  /api/migrate/count    – per-table record counts for the tenant

Business-ID scoping
-------------------
  business_id = user["parent_business_id"] or user["id"]

This resolves correctly for both owner accounts (parent_business_id is None,
so we use their own id) and staff sub-accounts (parent_business_id points to
the owner, which is the real business scope).

Dependency order used for export AND import
-------------------------------------------
  businesses → users → parties → products → invoices → invoice_items
  → settings → payments → purchases → purchase_items → stock → staff

The term "parties" maps to the real tables that exist (customers / vendors);
"purchases" maps to purchase_invoices / purchase_orders; etc.  We only touch
tables that are actually present in the live DB schema.

Missing-table safety
--------------------
All table accesses are guarded with `if table_name in _existing_tables(db)`.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

from database.db import get_db, engine, DATABASE_URL
from services.auth import get_active_user

router = APIRouter()
logger = logging.getLogger("bizassist.routes.migrate")


# ---------------------------------------------------------------------------
# TABLE ORDER  (dependency-safe; children always after parents)
# ---------------------------------------------------------------------------
# Canonical table names as they actually exist in the schema.
# Only tables that exist in the live DB are processed (see _filter_existing).

_EXPORT_ORDER: list[str] = [
    # Tier 0 – business identity
    "businesses",           # may not exist in all schema versions
    # Tier 1 – users / staff
    "users",
    # Tier 2 – master data (parties)
    "customers",            # buyer-side parties
    "vendors",              # supplier-side parties
    "products",
    # Tier 3 – transactional documents (parents before children)
    "invoices",
    "purchase_invoices",    # received bills / purchases
    "purchase_orders",
    # Tier 4 – line items (children of documents)
    "invoice_line_items",
    "purchase_invoice_line_items",
    "purchase_order_line_items",
    # Tier 5 – configuration / settings
    "alert_configs",
    "rate_limit_configs",
    "business_settings",
    # Tier 6 – financial auxiliaries
    "payments",
    "invoice_payments",
    # Tier 7 – stock / inventory
    "inventory",            # legacy cached projection
    "stock_ledger",         # append-only truth
    # Tier 8 – additional master data
    "product_barcodes",
    "godowns",
    "expenses",
    "stock_transfers",
    "stock_transfer_line_items",
    "shared_ledger",
]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _business_id_for(user: dict) -> int:
    """
    Resolve the scoped business_id for the authenticated user.
    Staff accounts carry parent_business_id; owners do not.
    """
    return int(user.get("parent_business_id") or user.get("id"))


def _resolve_owner_id_by_username(user: dict, db: Session) -> int:
    """
    Look up the ACTUAL owner id in this DB by username.

    This is critical for cross-DB migrations where local and cloud auto-assigned
    different integer IDs to the same user account (e.g., local id=122, cloud id=7).
    Falls back to the JWT id if the username lookup fails.
    """
    username = user.get("username") or user.get("sub") or ""
    if username:
        try:
            row = db.execute(
                text("SELECT id FROM \"users\" WHERE username = :u AND parent_business_id IS NULL"),
                {"u": username},
            ).first()
            if row:
                return int(row[0])
        except Exception as exc:
            logger.debug("_resolve_owner_id_by_username: lookup failed — %s", exc)
    # Fallback: use JWT id (same-DB case)
    return int(user.get("parent_business_id") or user.get("id"))


def _existing_tables(db: Session) -> set[str]:
    """Return the set of table names that actually exist in the live DB."""
    return set(inspect(db.bind).get_table_names())


def _row_to_dict(row) -> dict:
    """
    Serialize a SQLAlchemy result row (Row or ORM instance) to a plain dict.
    Strips the internal `_sa_instance_state` key if present.
    Converts datetime objects to ISO-8601 strings for JSON compatibility.
    """
    if hasattr(row, "__dict__"):
        d = {k: v for k, v in row.__dict__.items() if k != "_sa_instance_state"}
    else:
        # Core result Row (named-tuple style)
        d = dict(row._mapping)

    # Normalise non-JSON-serialisable types
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _fetch_table(db: Session, table_name: str, business_id: int) -> list[dict]:
    """
    Fetch all rows belonging to `business_id` from `table_name`.

    Strategy (in order):
      1. Table is `users` → id = business_id OR parent_business_id = business_id.
      2. Table has a `business_id` column → filter by it.
      3. No usable filter → return empty list (system/global table).
    """
    try:
        insp = inspect(db.bind)
        cols = {c["name"] for c in insp.get_columns(table_name)}

        if table_name == "users":
            result = db.execute(
                text(
                    'SELECT * FROM "users" '
                    "WHERE id = :bid OR parent_business_id = :bid"
                ),
                {"bid": business_id},
            )
            return [_row_to_dict(r) for r in result]

        if "business_id" in cols:
            result = db.execute(
                text(f'SELECT * FROM "{table_name}" WHERE business_id = :bid'),
                {"bid": business_id},
            )
            return [_row_to_dict(r) for r in result]

        # No business_id column – skip
        return []

    except Exception as exc:
        logger.warning("migrate/export: could not read table %s — %s", table_name, exc)
        return []


def _detect_local_owner_id(tables: dict) -> int | None:
    """
    Read the owner's id from the exported users table payload.
    The owner row has parent_business_id = None / null.
    Returns None if the users table is not in the payload.
    """
    for row in tables.get("users", []):
        if not row.get("parent_business_id"):
            return int(row["id"])
    return None


def _remap_rows(rows: list[dict], local_id: int, cloud_id: int) -> list[dict]:
    """
    Replace local_id → cloud_id in every field that carries a business/owner id.
    Handles: business_id, parent_business_id, user_id (only when == local_id).
    Does NOT touch unrelated integer fields.
    """
    if local_id == cloud_id:
        return rows  # already aligned — no remapping needed

    remapped = []
    for row in rows:
        r = dict(row)
        for field in ("business_id", "parent_business_id", "user_id"):
            if r.get(field) == local_id:
                r[field] = cloud_id
        remapped.append(r)
    return remapped


def _upsert_users(db: Session, rows: list[dict], cloud_owner_id: int, existing_tables: set) -> int:
    """
    Upsert the users table carefully:
    - Owner row (parent_business_id IS NULL): UPDATE the existing cloud owner row
      by username — never insert a duplicate. Only updates non-identity fields
      (business_name, gstin, phone, email, address, logo, settings, etc.).
    - Staff rows (parent_business_id IS NOT NULL): upsert by username, remapping
      parent_business_id → cloud_owner_id.
    """
    if "users" not in existing_tables:
        return 0

    dialect = db.bind.dialect.name
    count = 0

    for row in rows:
        r = dict(row)
        is_owner = not r.get("parent_business_id")

        if is_owner:
            # Update only non-identity columns on the existing owner row
            update_fields = [
                "business_name", "gstin", "phone", "email",
                "address", "state_code", "pan", "logo", "settings",
                "public_id",
            ]
            set_parts = ", ".join(
                f'"{f}" = :{f}' for f in update_fields if f in r
            )
            if not set_parts:
                continue
            params = {f: r[f] for f in update_fields if f in r}
            params["username"] = r["username"]
            try:
                db.execute(
                    text(f'UPDATE "users" SET {set_parts} WHERE username = :username'),
                    params,
                )
                db.flush()
                count += 1
            except Exception as exc:
                logger.debug("migrate/import: owner user update failed for %s — %s", r.get("username"), exc)
                db.rollback()
        else:
            # Staff: remap parent → cloud owner
            r["parent_business_id"] = cloud_owner_id
            # Upsert by username
            if dialect == "postgresql":
                cols = [k for k in r if k != "id"]  # let PG assign id for new staff
                col_str = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(f":{c}" for c in cols)
                update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "username")
                sql = text(
                    f'INSERT INTO "users" ({col_str}) VALUES ({placeholders}) '
                    f'ON CONFLICT (username) DO UPDATE SET {update_set}'
                )
            else:
                col_list = list(r.keys())
                col_str = ", ".join(f'"{c}"' for c in col_list)
                placeholders = ", ".join(f":{c}" for c in col_list)
                sql = text(f'INSERT OR REPLACE INTO "users" ({col_str}) VALUES ({placeholders})')
            try:
                db.execute(sql, r)
                db.flush()
                count += 1
            except Exception as exc:
                logger.debug("migrate/import: staff user upsert failed for %s — %s", r.get("username"), exc)
                db.rollback()

    return count


# ---------------------------------------------------------------------------
# UPSERT HELPER
# ---------------------------------------------------------------------------

def _upsert_rows(
    db: Session,
    table_name: str,
    rows: list[dict],
    existing_tables: set[str],
) -> int:
    """
    Insert (or update on PK conflict) rows into `table_name`.
    Preserves original IDs.  Per-row errors do not abort the batch.

    Returns the number of rows successfully inserted/updated.
    """
    if not rows or table_name not in existing_tables:
        return 0

    try:
        insp = inspect(db.bind)
        col_info = insp.get_columns(table_name)
        pk_constraint = insp.get_pk_constraint(table_name)
        pk_cols: set[str] = set(pk_constraint.get("constrained_columns", []))
    except Exception as exc:
        logger.warning("migrate/import: cannot inspect %s — %s", table_name, exc)
        return 0

    col_names = {c["name"] for c in col_info}
    count = 0
    dialect = db.bind.dialect.name  # "sqlite" | "postgresql"

    for row in rows:
        # Only keep columns that exist in the current schema
        filtered = {k: v for k, v in row.items() if k in col_names}
        if not filtered:
            continue

        col_list = list(filtered.keys())
        placeholders = ", ".join(f":{c}" for c in col_list)
        col_str = ", ".join(f'"{c}"' for c in col_list)

        try:
            if dialect == "postgresql":
                update_cols = [c for c in col_list if c not in pk_cols]
                pk_str = ", ".join(f'"{c}"' for c in sorted(pk_cols))

                if update_cols:
                    update_set = ", ".join(
                        f'"{c}" = EXCLUDED."{c}"' for c in update_cols
                    )
                    sql = text(
                        f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) '
                        f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_set}"
                    )
                else:
                    sql = text(
                        f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) '
                        f"ON CONFLICT ({pk_str}) DO NOTHING"
                    )

            else:
                # SQLite – INSERT OR REPLACE handles PK conflicts atomically
                sql = text(
                    f'INSERT OR REPLACE INTO "{table_name}" ({col_str}) VALUES ({placeholders})'
                )

            db.execute(sql, filtered)
            db.flush()
            count += 1

        except Exception as exc:
            logger.debug(
                "migrate/import: row skip in %s (pk=%s): %s",
                table_name,
                {k: filtered.get(k) for k in pk_cols},
                exc,
            )
            db.rollback()

    return count


# ---------------------------------------------------------------------------
# PYDANTIC SCHEMAS
# ---------------------------------------------------------------------------

class ImportBody(BaseModel):
    tables: dict[str, list[dict[str, Any]]]


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@router.get("/api/migrate/export")
def export_data(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Export all tenant data as structured JSON.

    Uses username-based ID resolution so the export is correct even if the
    JWT was issued by a different DB (e.g., cloud JWT used against local DB).

    Response shape:
      {
        "exported_at": "2026-06-25T13:00:00+00:00",
        "business_id": 1,
        "tables": {
          "invoices": [ {...}, ... ],
          "parties":  [ {...}, ... ],
          ...
        }
      }
    """
    # Always look up by username in THIS DB — handles cross-DB JWT tokens
    business_id = _resolve_owner_id_by_username(current_user, db)
    logger.info(
        "migrate/export: resolved business_id=%s for username=%s (JWT id=%s)",
        business_id, current_user.get("username"), current_user.get("id")
    )
    existing = _existing_tables(db)

    tables_data: dict[str, list[dict]] = {}
    for table_name in _EXPORT_ORDER:
        if table_name not in existing:
            continue
        rows = _fetch_table(db, table_name, business_id)
        if rows:
            tables_data[table_name] = rows

    logger.info(
        "migrate/export: business_id=%s tables=%s total_rows=%s",
        business_id,
        list(tables_data.keys()),
        sum(len(v) for v in tables_data.values()),
    )

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "business_id": business_id,
        "tables": tables_data,
    }


@router.post("/api/migrate/import")
def import_data(
    body: ImportBody,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Restore tenant data from an export payload.

    ID Remapping (cross-DB migration)
    ----------------------------------
    The exporting DB and the importing DB may have assigned different integer
    IDs to the same user (e.g., local id=122, cloud id=7 for 'Rakshith').

    This endpoint:
      1. Resolves the importing user by USERNAME in the destination DB
         (ignoring the JWT id which may point to a non-existent row here).
      2. Detects the local owner id from the payload's users table.
      3. Remaps every business_id / parent_business_id reference from the
         local id → cloud id before upserting.
      4. Handles the users table specially (upsert by username, never
         duplicate the owner).

    Response shape:
      {
        "imported": {"invoices": 342, "parties": 55, ...},
        "total": 397,
        "id_remap": {"from": 122, "to": 7}   # present when remapping occurred
      }
    """
    # Step 1 — resolve the ACTUAL owner id in THIS (destination) DB by username
    cloud_owner_id = _resolve_owner_id_by_username(current_user, db)
    existing = _existing_tables(db)
    imported: dict[str, int] = {}

    # Step 2 — detect the local owner id from the exported payload
    local_owner_id = _detect_local_owner_id(body.tables)
    if local_owner_id is None:
        local_owner_id = cloud_owner_id  # same-DB migration, no remap needed

    logger.info(
        "migrate/import: username=%s local_owner_id=%s cloud_owner_id=%s",
        current_user.get("username"), local_owner_id, cloud_owner_id,
    )

    # Process in canonical dependency order first, then any extras from payload
    ordered = [t for t in _EXPORT_ORDER if t in body.tables]
    extras = [t for t in body.tables if t not in _EXPORT_ORDER]
    process_order = ordered + extras

    try:
        for table_name in process_order:
            rows = body.tables.get(table_name, [])
            if not rows:
                continue

            if table_name == "users":
                # Special handling: upsert by username, remap staff parent ids
                n = _upsert_users(db, rows, cloud_owner_id, existing)
            else:
                # Remap business_id references before upsert
                remapped = _remap_rows(rows, local_owner_id, cloud_owner_id)
                n = _upsert_rows(db, table_name, remapped, existing)

            if n > 0:
                imported[table_name] = n

        db.commit()

    except Exception as exc:
        db.rollback()
        logger.error("migrate/import: fatal error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    total = sum(imported.values())
    remap_info = {"from": local_owner_id, "to": cloud_owner_id} if local_owner_id != cloud_owner_id else None
    logger.info(
        "migrate/import: cloud_owner_id=%s imported=%s total=%s remap=%s",
        cloud_owner_id, imported, total, remap_info,
    )
    result = {"imported": imported, "total": total}
    if remap_info:
        result["id_remap"] = remap_info
    return result


@router.get("/api/migrate/count")
def count_records(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Return per-table record counts for the authenticated tenant.

    Used for pre-migration estimation and post-migration validation.
    Tables that exist in the schema but have 0 records are included with
    count=0, so the caller can distinguish "empty table" from "missing table".

    Response shape:
      {
        "invoices": 342,
        "parties":  55,
        ...
      }
    """
    business_id = _business_id_for(current_user)
    existing = _existing_tables(db)

    try:
        insp = inspect(db.bind)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB inspect failed: {exc}")

    counts: dict[str, int] = {}

    for table_name in _EXPORT_ORDER:
        if table_name not in existing:
            continue
        try:
            col_names = {c["name"] for c in insp.get_columns(table_name)}

            if table_name == "users":
                result = db.execute(
                    text(
                        "SELECT COUNT(*) FROM users "
                        "WHERE id = :bid OR parent_business_id = :bid"
                    ),
                    {"bid": business_id},
                )
                counts[table_name] = result.scalar() or 0

            elif "business_id" in col_names:
                result = db.execute(
                    text(
                        f'SELECT COUNT(*) FROM "{table_name}" WHERE business_id = :bid'
                    ),
                    {"bid": business_id},
                )
                counts[table_name] = result.scalar() or 0

            # Tables without business_id are not counted (system/global)

        except Exception as exc:
            logger.warning(
                "migrate/count: cannot count %s — %s", table_name, exc
            )
            counts[table_name] = -1  # sentinel: exists but count failed

    return counts
