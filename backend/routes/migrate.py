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
import sqlalchemy as sa
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


def _resolve_owner_id(user: dict, db: Session) -> int:
    """
    Resolve the ACTUAL owner id in THIS DB for the authenticated user.

    Cross-DB migrations assign different integer ids to the same account
    (e.g. local id=122, cloud id=7). We match on the most stable key first:

      1. BizID (public_id) **confirmed by username** — the identity spine (D9).
         We require username to agree too: BizID is not yet globally unique
         (minted per-DB), so a chance collision with a *different* business must
         not mis-route. Requiring the username match removes that risk.
      2. username — bridge for the FIRST migration / older tokens.
      3. JWT id — same-DB fallback.
    """
    username = user.get("username") or user.get("sub") or ""
    public_id = user.get("public_id")
    if public_id and username:
        try:
            row = db.execute(
                text('SELECT id FROM "users" WHERE public_id = :p AND username = :u AND parent_business_id IS NULL'),
                {"p": public_id, "u": username},
            ).first()
            if row:
                return int(row[0])
        except Exception as exc:
            logger.debug("_resolve_owner_id: public_id lookup failed — %s", exc)

    if username:
        try:
            row = db.execute(
                text('SELECT id FROM "users" WHERE username = :u AND parent_business_id IS NULL'),
                {"u": username},
            ).first()
            if row:
                return int(row[0])
        except Exception as exc:
            logger.debug("_resolve_owner_id: username lookup failed — %s", exc)

    # Fallback: use JWT id (same-DB case)
    return int(user.get("parent_business_id") or user.get("id"))


# Backward-compatible alias (old name used elsewhere).
_resolve_owner_id_by_username = _resolve_owner_id


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
                with db.begin_nested():   # (M-1) per-row savepoint
                    db.execute(
                        text(f'UPDATE "users" SET {set_parts} WHERE username = :username'),
                        params,
                    )
                count += 1
            except Exception as exc:
                logger.warning("migrate/import: owner user update failed for %s — %s", r.get("username"), exc)
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
                with db.begin_nested():   # (M-1) per-row savepoint
                    db.execute(sql, r)
                count += 1
            except Exception as exc:
                logger.warning("migrate/import: staff user upsert failed for %s — %s", r.get("username"), exc)

    return count


# ---------------------------------------------------------------------------
# UPSERT HELPER
# ---------------------------------------------------------------------------

def _upsert_rows(
    db: Session,
    table_name: str,
    rows: list[dict],
    existing_tables: set[str],
    merge: bool = False,
) -> int:
    """
    Insert (or update on PK conflict) rows into `table_name`.
    Preserves original IDs.  Per-row errors do not abort the batch.

    merge=False (default, migration): destination row is overwritten on conflict.
    merge=True  (sync buttons): **non-destructive Last-Write-Wins** — insert new
                rows, update an existing row ONLY when the incoming copy is newer
                (`updated_at`), and never delete or clobber a newer/local-only row.

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
    # (Bug-A) SQLite stores booleans as 0/1 integers; Postgres columns are real
    # BOOLEAN and reject an integer via raw SQL ("is of type boolean but
    # expression is of type integer"). Coerce these columns back to bool so
    # customers/products/invoices/barcodes/godowns actually import.
    bool_cols = {c["name"] for c in col_info if isinstance(c["type"], sa.Boolean)}
    has_updated_at = "updated_at" in col_names
    count = 0
    dialect = db.bind.dialect.name  # "sqlite" | "postgresql"
    pk_str = ", ".join(f'"{c}"' for c in sorted(pk_cols))

    for row in rows:
        # Only keep columns that exist in the current schema
        filtered = {k: v for k, v in row.items() if k in col_names}
        if not filtered:
            continue
        # Coerce integer/string booleans to real bools for BOOLEAN columns.
        for bc in bool_cols:
            if bc in filtered and filtered[bc] is not None and not isinstance(filtered[bc], bool):
                v = filtered[bc]
                filtered[bc] = (
                    v != 0 if isinstance(v, (int, float))
                    else str(v).strip().lower() in ("1", "true", "t", "yes", "y")
                )

        col_list = list(filtered.keys())
        placeholders = ", ".join(f":{c}" for c in col_list)
        col_str = ", ".join(f'"{c}"' for c in col_list)
        update_cols = [c for c in col_list if c not in pk_cols]

        if not pk_cols:
            # No primary key to conflict on — plain insert.
            sql = text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})')
        elif not update_cols:
            sql = text(
                f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) '
                f"ON CONFLICT ({pk_str}) DO NOTHING"
            )
        elif merge:
            # (Sync) Non-destructive Last-Write-Wins: insert new rows; update an
            # existing one ONLY when the incoming copy is newer. Rows with no
            # timestamp, or where the destination is newer, are kept untouched.
            update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
            if has_updated_at:
                sql = text(
                    f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) '
                    f'ON CONFLICT ({pk_str}) DO UPDATE SET {update_set} '
                    f'WHERE EXCLUDED."updated_at" > "{table_name}"."updated_at"'
                )
            else:
                sql = text(
                    f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) '
                    f"ON CONFLICT ({pk_str}) DO NOTHING"
                )
        else:
            # Mirror / overwrite (migration default): destination row replaced.
            # (M-4) Both dialects use ON CONFLICT … DO UPDATE — never the
            # destructive SQLite INSERT OR REPLACE, which deletes+reinserts.
            update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
            sql = text(
                f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders}) '
                f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_set}"
            )

        # (M-1) SAVEPOINT per row: a bad row rolls back ONLY itself, never the
        # whole import. Without this, db.rollback() discarded every row already
        # imported in this transaction while the API still reported success.
        try:
            with db.begin_nested():
                db.execute(sql, filtered)
            count += 1
        except Exception as exc:
            # Log only the DB driver's concise message (exc.orig), not the full
            # SQLAlchemy statement+params dump — that was flooding the log and
            # slowing the import on every failed row.
            orig = getattr(exc, "orig", exc)
            reason = str(orig).strip().splitlines()[0] if orig else str(exc)
            logger.warning(
                "migrate/import: row skip in %s (pk=%s): %s",
                table_name,
                {k: filtered.get(k) for k in pk_cols},
                reason,
            )

    return count


def _reset_sequences(db: Session, table_names: list[str]) -> None:
    """
    (M-2) After importing rows with their original explicit ``id``s, bump each
    Postgres identity sequence to MAX(id). Without this, the next cloud-side
    INSERT calls nextval() and collides with an already-imported id (silent
    IntegrityError / ON CONFLICT skip → new records appear to vanish).

    No-op on SQLite (its rowid allocator already advances past inserted ids).
    """
    if db.bind.dialect.name != "postgresql":
        return
    for t in table_names:
        try:
            with db.begin_nested():
                seq = db.execute(
                    text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": t}
                ).scalar()
                if not seq:
                    continue  # table has no id sequence (e.g. composite/no PK)
                # Table name comes from our own _EXPORT_ORDER allow-list, not user
                # input, so f-string interpolation here is safe.
                db.execute(
                    text(
                        f'SELECT setval(:seq, COALESCE((SELECT MAX(id) FROM "{t}"), 1), true)'
                    ),
                    {"seq": seq},
                )
        except Exception as exc:
            logger.warning("migrate/import: sequence reset skipped for %s — %s", t, exc)


# ---------------------------------------------------------------------------
# ENTITY-ID REMAP (R-3) — cross-DB-safe import that does NOT force source ids
# ---------------------------------------------------------------------------
# Natural keys for idempotent remap (first existing, non-null column wins). A
# row whose natural key already exists on the destination is reused, not
# duplicated — so a re-import is safe for these tables.
_NATURAL_KEYS: dict[str, list[str]] = {
    "customers": ["phone", "name"],
    "vendors": ["phone", "name"],
    "products": ["barcode", "sku", "name"],
    "invoices": ["invoice_id"],
    "purchase_invoices": ["invoice_id", "bill_no"],
    "purchase_orders": ["order_no"],
    "godowns": ["name"],
    "product_barcodes": ["barcode"],
    "inventory": ["product_id"],     # product_id is FK-rewritten before this lookup
    "business_settings": [],         # one row per business → match on business_id alone
}


def _uid_lookup(db: Session, table: str, col_names: set, business_id: int, filtered: dict):
    """(Step 3 / R-3) Return an existing destination row id matching this row's
    durable ``uid``, or None.

    `uid` is a globally-unique key carried by every BusinessOwnedMixin row, so it
    identifies "the same row across DBs" exactly — immune to the per-DB ``id``
    divergence that natural keys (phone/name) only approximate. Scoped to
    business_id (matches RLS) when the column exists. Returns None for tables
    without a uid column, or rows that predate the column (uid IS NULL) — the
    caller then falls back to the natural-key match.
    """
    if "uid" not in col_names:
        return None
    uid = filtered.get("uid")
    if not uid:
        return None
    try:
        if "business_id" in col_names:
            row = db.execute(
                text(f'SELECT id FROM "{table}" WHERE business_id = :b AND uid = :u LIMIT 1'),
                {"b": business_id, "u": uid},
            ).first()
        else:
            row = db.execute(
                text(f'SELECT id FROM "{table}" WHERE uid = :u LIMIT 1'),
                {"u": uid},
            ).first()
        return int(row[0]) if row else None
    except Exception as exc:
        logger.debug("migrate/import[remap]: uid lookup failed for %s — %s", table, exc)
        return None


def _natural_lookup(db: Session, table: str, col_names: set, business_id: int, filtered: dict):
    """Return an existing destination row id matching this row's natural key, or None.

    Returns None (→ always insert) for tables not listed in _NATURAL_KEYS.
    """
    candidates = _NATURAL_KEYS.get(table)
    if candidates is None:
        return None
    try:
        if candidates == []:   # singleton-per-business (e.g. business_settings)
            row = db.execute(
                text(f'SELECT id FROM "{table}" WHERE business_id = :b LIMIT 1'),
                {"b": business_id},
            ).first()
            return int(row[0]) if row else None
        for col in candidates:
            if col in col_names and filtered.get(col) not in (None, ""):
                row = db.execute(
                    text(f'SELECT id FROM "{table}" WHERE business_id = :b AND "{col}" = :v LIMIT 1'),
                    {"b": business_id, "v": filtered[col]},
                ).first()
                return int(row[0]) if row else None
    except Exception as exc:
        logger.debug("migrate/import[remap]: natural lookup failed for %s — %s", table, exc)
    return None


def _import_with_remap(db: Session, table_name: str, rows: list[dict],
                       cloud_owner_id: int, local_owner_id: int,
                       existing_tables: set[str], id_maps: dict) -> int:
    """
    (R-3) Import rows WITHOUT forcing their source ids. The destination assigns
    fresh ids; we record old→new per table in `id_maps` and rewrite every
    foreign key that points at an already-remapped table. Natural-key dedup
    makes a re-import idempotent for tables that have a stable key.

    Unlike the id-preserving upsert, this can merge into an account that already
    has its own rows without overwriting them — the cross-DB-safe path.
    Process tables parent-before-child (the caller uses _EXPORT_ORDER).
    """
    if not rows or table_name not in existing_tables:
        return 0
    try:
        insp = inspect(db.bind)
        col_info = insp.get_columns(table_name)
        fks = insp.get_foreign_keys(table_name)
    except Exception as exc:
        logger.warning("migrate/import[remap]: cannot inspect %s — %s", table_name, exc)
        return 0

    col_names = {c["name"] for c in col_info}
    bool_cols = {c["name"] for c in col_info if isinstance(c["type"], sa.Boolean)}
    # single-column FKs that reference <referred_table>.id
    fk_targets = [
        (fk["constrained_columns"][0], fk["referred_table"])
        for fk in fks
        if len(fk.get("constrained_columns", [])) == 1
        and fk.get("referred_columns") == ["id"]
    ]
    dialect = db.bind.dialect.name
    table_map = id_maps.setdefault(table_name, {})
    count = 0

    for row in rows:
        old_id = row.get("id")
        filtered = {k: v for k, v in row.items() if k in col_names and k != "id"}
        if not filtered:
            continue
        # owner remap (business/owner references)
        for f in ("business_id", "parent_business_id", "user_id"):
            if f in filtered and filtered[f] == local_owner_id:
                filtered[f] = cloud_owner_id
        # boolean coercion (SQLite int → Postgres BOOLEAN)
        for bc in bool_cols:
            if bc in filtered and filtered[bc] is not None and not isinstance(filtered[bc], bool):
                v = filtered[bc]
                filtered[bc] = (v != 0 if isinstance(v, (int, float))
                                else str(v).strip().lower() in ("1", "true", "t", "yes", "y"))
        # rewrite foreign keys using maps already built for parent tables
        for col, ref_table in fk_targets:
            if filtered.get(col) is not None:
                m = id_maps.get(ref_table)
                if m and filtered[col] in m:
                    filtered[col] = m[filtered[col]]
                # else leave as-is; a dangling FK will fail and be skipped (logged)

        # Idempotent dedup. (Step 3 / R-3) Match on the durable `uid` first — it
        # identifies the same row across DBs exactly. Fall back to the natural key
        # (phone/name/invoice_id) for rows that predate the uid column. A matched
        # row is reused (its destination id is recorded so child FKs rewrite to
        # it), never duplicated or overwritten.
        existing_id = _uid_lookup(db, table_name, col_names, cloud_owner_id, filtered)
        if existing_id is None:
            existing_id = _natural_lookup(db, table_name, col_names, cloud_owner_id, filtered)
        if existing_id is not None:
            if old_id is not None:
                table_map[old_id] = existing_id
            continue

        cols = list(filtered.keys())
        col_str = ", ".join(f'"{c}"' for c in cols)
        ph = ", ".join(f":{c}" for c in cols)
        try:
            with db.begin_nested():
                if dialect == "postgresql":
                    new_id = db.execute(
                        text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({ph}) RETURNING id'),
                        filtered,
                    ).scalar()
                else:
                    new_id = db.execute(
                        text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({ph})'),
                        filtered,
                    ).lastrowid
            if old_id is not None and new_id is not None:
                table_map[old_id] = int(new_id)
            count += 1
        except Exception as exc:
            orig = getattr(exc, "orig", exc)
            reason = str(orig).strip().splitlines()[0] if orig else str(exc)
            logger.warning("migrate/import[remap]: row skip in %s (old_id=%s): %s",
                           table_name, old_id, reason)

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
    remap_ids: bool = False,
    merge: bool = False,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Restore tenant data from an export payload.

    Owner identity (cross-DB)
    -------------------------
    Local and cloud assign different ids to the same account (local id=122,
    cloud id=7). The owner is resolved in THIS DB by BizID → username → JWT id,
    and every business_id / parent_business_id is remapped local → cloud.

    Two import modes
    ----------------
    • default (`remap_ids=false`): id-PRESERVING upsert — keeps source entity
      ids and upserts by PK. Best when merging into a FRESH cloud account.
    • `?remap_ids=true`: entity-id REMAP (R-3) — destination assigns fresh ids,
      foreign keys are rewritten, and natural-key dedup makes it idempotent.
      Use this to merge into an account that ALREADY has its own rows, so source
      ids can't collide with / overwrite existing cloud records.

    Response: {"imported": {...}, "total": N, "id_remap": {"from":122,"to":7}}
    """
    # Resolve the ACTUAL owner id in THIS (destination) DB (BizID-first)
    cloud_owner_id = _resolve_owner_id(current_user, db)
    existing = _existing_tables(db)
    imported: dict[str, int] = {}

    # Detect the local owner id from the exported payload
    local_owner_id = _detect_local_owner_id(body.tables)
    if local_owner_id is None:
        local_owner_id = cloud_owner_id  # same-DB migration, no remap needed

    logger.info(
        "migrate/import: user=%s local_owner_id=%s cloud_owner_id=%s mode=%s",
        current_user.get("username"), local_owner_id, cloud_owner_id,
        "remap" if remap_ids else ("merge-lww" if merge else "mirror"),
    )

    # Process in canonical dependency order first, then any extras from payload
    ordered = [t for t in _EXPORT_ORDER if t in body.tables]
    extras = [t for t in body.tables if t not in _EXPORT_ORDER]
    process_order = ordered + extras

    # Entity-id remap mode keeps old→new id maps so child FKs can be rewritten.
    id_maps: dict[str, dict] = {}

    try:
        for table_name in process_order:
            rows = body.tables.get(table_name, [])
            if not rows:
                continue

            if table_name == "users":
                # Users are always identity-matched by username (owner/staff),
                # never id-remapped — they define the business scope itself.
                n = _upsert_users(db, rows, cloud_owner_id, existing)
            elif remap_ids:
                n = _import_with_remap(
                    db, table_name, rows, cloud_owner_id, local_owner_id, existing, id_maps
                )
            else:
                remapped = _remap_rows(rows, local_owner_id, cloud_owner_id)
                n = _upsert_rows(db, table_name, remapped, existing, merge=merge)

            if n > 0:
                imported[table_name] = n

        # (M-2) Only the id-preserving path inserts explicit ids → realign
        # sequences. Remap mode used the DB's own sequence already.
        if not remap_ids:
            _reset_sequences(db, list(imported.keys()))

        db.commit()

    except Exception as exc:
        db.rollback()
        logger.error("migrate/import: fatal error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    total = sum(imported.values())
    _mode = "remap" if remap_ids else ("merge-lww" if merge else "mirror")
    remap_info = {"from": local_owner_id, "to": cloud_owner_id} if local_owner_id != cloud_owner_id else None
    logger.info(
        "migrate/import: cloud_owner_id=%s imported=%s total=%s remap=%s mode=%s",
        cloud_owner_id, imported, total, remap_info, _mode,
    )
    result = {"imported": imported, "total": total, "mode": _mode}
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
