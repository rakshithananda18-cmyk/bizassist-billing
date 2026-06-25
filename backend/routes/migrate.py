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

    Returns every table that (a) exists in the live DB and (b) has rows
    belonging to the authenticated user's business, serialised in
    dependency order so the payload is safe to feed directly into import.

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
    business_id = _business_id_for(current_user)
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

    Records are upserted (INSERT … ON CONFLICT DO UPDATE / INSERT OR REPLACE)
    in dependency order.  Original IDs are preserved.  Individual row errors
    are logged and skipped — the rest of the batch continues.

    Response shape:
      {
        "imported": {"invoices": 342, "parties": 55, ...},
        "total": 397
      }
    """
    business_id = _business_id_for(current_user)
    existing = _existing_tables(db)
    imported: dict[str, int] = {}

    # Process in canonical dependency order first, then any extras from payload
    ordered = [t for t in _EXPORT_ORDER if t in body.tables]
    extras = [t for t in body.tables if t not in _EXPORT_ORDER]
    process_order = ordered + extras

    try:
        for table_name in process_order:
            rows = body.tables.get(table_name, [])
            if not rows:
                continue
            n = _upsert_rows(db, table_name, rows, existing)
            if n > 0:
                imported[table_name] = n

        db.commit()

    except Exception as exc:
        db.rollback()
        logger.error("migrate/import: fatal error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    total = sum(imported.values())
    logger.info(
        "migrate/import: business_id=%s imported=%s total=%s",
        business_id, imported, total,
    )
    return {"imported": imported, "total": total}


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
