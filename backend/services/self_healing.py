"""
services/self_healing.py
========================
Master Self-Healing Engine for BizAssist Billing.
Consolidates diagnostic & automated repair logic across 4 core domains:
  1. Accounting & SHA-256 Hash Chain Re-Sealing
  2. Stock Ledger & Inventory Drift Reconciliation
  3. Sync Outbox & Quarantined Queue Recovery
  4. Staff Accounts & Tenant Security Integrity

STRICT SAFETY GUARANTEES:
  • ZERO Data Deletions: Never deletes business documents, payments, products, or stock entries.
  • Append-Only Recovery: Repairs via re-linking, re-hashing, and audit-logged ledger entries.
  • SAVEPOINT Isolation: Each domain executes inside an isolated transaction savepoint.
  • Structured Audit Logging: Every repair step logs with [SELF_HEAL] tag.
"""
import os
import json
import logging
from typing import Dict, Any, List
from sqlalchemy import text, func, or_
from sqlalchemy.orm import Session, selectinload

from database.db import utc_now
from database.models import (
    User, SyncQueue, SyncLog, ConflictLog, Inventory, Product, Customer, Vendor,
    Invoice, PurchaseInvoice, InvoicePayment, Expense, DeletedBusiness,
    _serialize_orm_obj, _BUSINESS_ID_VIA_PARENT
)
from database.sync_map import MODEL_MAP
from core.models import JournalEntry, StockLedger
from core.accounting import posting
from core.stock import ledger as SL

logger = logging.getLogger("bizassist.services.self_healing")


# ── Domain 1: Accounting & Hash Chain Re-Sealing ──────────────────────────────

def heal_hash_chain(db: Session, business_id: int) -> int:
    """Idempotently detect, re-link, and re-seal the journal hash chain in a single pass O(N).
    Never deletes entries; re-calculates SHA-256 signatures deterministically.
    """
    healed_count = 0
    try:
        with db.begin_nested():
            entries = (
                db.query(JournalEntry)
                .options(selectinload(JournalEntry.lines))
                .filter(JournalEntry.business_id == business_id)
                .order_by(JournalEntry.id.asc())
                .with_for_update()
                .all()
            )

            if not entries:
                return 0

            prev_hash = posting.GENESIS_HASH

            for entry in entries:
                if not entry.entry_hash and entry.prev_hash is None:
                    continue

                clean_lines = [
                    (l.account, posting._r2(l.debit), posting._r2(l.credit))
                    for l in sorted(entry.lines, key=lambda x: (x.account, posting._r2(x.debit), posting._r2(x.credit), x.id))
                ]

                expected_hash = posting._chain_hash(
                    business_id=entry.business_id,
                    entry_date=entry.entry_date,
                    source_type=entry.source_type,
                    source_id=entry.source_id,
                    ref_no=entry.ref_no or "",
                    narration=entry.narration or "",
                    clean=clean_lines,
                    prev_hash=prev_hash,
                )

                if entry.prev_hash != prev_hash or entry.entry_hash != expected_hash:
                    entry.prev_hash = prev_hash
                    entry.entry_hash = expected_hash
                    healed_count += 1

                prev_hash = entry.entry_hash

            if healed_count > 0:
                db.flush()
                logger.info("[SELF_HEAL][ACCT] Re-sealed hash chain for biz=%s: %d entries healed", business_id, healed_count)
    except Exception as e:
        logger.error("[SELF_HEAL][ACCT] Hash chain healing failed for biz=%s: %s", business_id, e, exc_info=True)

    return healed_count


# ── Domain 2: Stock Ledger & Inventory Reconciliation ────────────────────────

def heal_stock_ledger_drift(db: Session, business_id: int, auto_fix_import_drift: bool = True) -> Dict[str, Any]:
    """Audit and reconcile cached stock against immutable StockLedger.
    Auto-creates OPENING StockLedger rows for un-ledgered CSV imports.
    """
    stats = {
        "inventory_rows_audited": 0,
        "drift_detected_count": 0,
        "inventory_rows_fixed": 0,
        "import_ledger_entries_created": 0,
        "missing_inventory_rows_created": 0,
    }

    try:
        with db.begin_nested():
            # Step 1: Un-ledgered CSV import inventory records
            if auto_fix_import_drift:
                inv_rows = db.query(Inventory).filter(Inventory.business_id == business_id).all()
                for inv in inv_rows:
                    if not inv.product_id and inv.product_name:
                        prod = db.query(Product).filter(
                            Product.business_id == business_id,
                            Product.name == inv.product_name
                        ).first()
                        if prod:
                            inv.product_id = prod.id
                            db.flush()

                    if inv.product_id:
                        ledger_count = db.query(func.count(StockLedger.id)).filter(
                            StockLedger.business_id == business_id,
                            StockLedger.product_id == inv.product_id,
                            StockLedger.godown_id == inv.godown_id,
                            StockLedger.batch_no == inv.batch_no,
                        ).scalar() or 0

                        if ledger_count == 0 and (inv.stock or 0) != 0:
                            opening_qty = float(inv.stock)
                            SL.record_movement(
                                db,
                                business_id=business_id,
                                movement_type=SL.OPENING,
                                qty_delta=opening_qty,
                                product_id=inv.product_id,
                                product_name=inv.product_name,
                                godown_id=inv.godown_id,
                                batch_no=inv.batch_no,
                                expiry_date=inv.expiry_date,
                                reference_type="reconciliation_heal",
                                note="Self-healing auto-created ledger entry for un-ledgered inventory import",
                                update_cache=False
                            )
                            stats["import_ledger_entries_created"] += 1

            # Step 2: Discover all products/batches in StockLedger & reconcile cache
            ledger_groups = db.query(
                StockLedger.product_id,
                StockLedger.product_name,
                StockLedger.godown_id,
                StockLedger.batch_no,
                StockLedger.expiry_date
            ).filter(
                StockLedger.business_id == business_id,
                StockLedger.product_id.isnot(None)
            ).group_by(
                StockLedger.product_id,
                StockLedger.product_name,
                StockLedger.godown_id,
                StockLedger.batch_no
            ).all()

            for group in ledger_groups:
                pid, pname, godown_id, batch_no, expiry_date = group
                inv_row = db.query(Inventory).filter(
                    Inventory.business_id == business_id,
                    Inventory.product_id == pid,
                    Inventory.godown_id == godown_id,
                    Inventory.batch_no == batch_no
                ).first()

                correct_stock = SL.current_stock(
                    db, business_id, product_id=pid, godown_id=godown_id, batch_no=batch_no
                )

                if not inv_row:
                    prod = db.query(Product).filter(Product.id == pid, Product.business_id == business_id).first()
                    if prod:
                        new_inv = Inventory(
                            business_id=business_id,
                            product_id=pid,
                            product_name=pname or prod.name,
                            stock=float(correct_stock),
                            godown_id=godown_id,
                            batch_no=batch_no,
                            expiry_date=expiry_date,
                            unit=prod.unit,
                            hsn_sac=prod.hsn_sac,
                            selling_price=prod.selling_price,
                            cost_price=prod.cost_price,
                            mrp=prod.mrp,
                        )
                        db.add(new_inv)
                        stats["missing_inventory_rows_created"] += 1
                else:
                    stats["inventory_rows_audited"] += 1
                    current_cache = float(inv_row.stock or 0.0)
                    if abs(current_cache - correct_stock) > 1e-5:
                        stats["drift_detected_count"] += 1
                        inv_row.stock = float(correct_stock)
                        stats["inventory_rows_fixed"] += 1

            db.flush()
            logger.info("[SELF_HEAL][STOCK] Completed stock heal for biz=%s: %s", business_id, stats)
    except Exception as e:
        logger.error("[SELF_HEAL][STOCK] Stock heal failed for biz=%s: %s", business_id, e, exc_info=True)

    return stats


# ── Domain 3: Sync Outbox & Queue Recovery ───────────────────────────────────

def heal_sync_outbox_stalls(db: Session, business_id: int) -> Dict[str, Any]:
    """Clean, repair, retry, and reconcile stuck or quarantined outbox items."""
    report = {
        "payloads_patched": 0,
        "parents_queued": 0,
        "corrupt_repaired": 0,
        "errors_reset": 0,
        "redundant_children_cleared": 0,
    }

    try:
        with db.begin_nested():
            # 1. Re-enrich child payloads missing parent UIDs
            child_entities = list(_BUSINESS_ID_VIA_PARENT.keys())
            if child_entities:
                stuck = db.query(SyncQueue).filter(
                    SyncQueue.business_id == business_id,
                    SyncQueue.synced_at.is_(None),
                    SyncQueue.entity.in_(child_entities)
                ).all()

                parent_tbl_map = {
                    "invoice_line_items":          ("invoices",          "invoice_id",          "invoice_id_uid"),
                    "purchase_invoice_line_items": ("purchase_invoices", "purchase_invoice_id", "purchase_invoice_id_uid"),
                    "purchase_order_line_items":   ("purchase_orders",   "purchase_order_id",   "purchase_order_id_uid"),
                    "stock_transfer_line_items":   ("stock_transfers",   "transfer_id",         "transfer_id_uid"),
                    "invoice_payments":            ("invoices",          "invoice_id",          "invoice_id_uid"),
                    "shift_cash_movements":        ("register_shifts",   "shift_id",            "shift_id_uid"),
                }

                for item in stuck:
                    spec = parent_tbl_map.get(item.entity)
                    if not spec:
                        continue
                    parent_tbl, fk_col, uid_key = spec
                    pay = json.loads(item.payload) if item.payload else {}
                    fk_raw = pay.get(fk_col)
                    if not fk_raw:
                        continue

                    try:
                        fk_val = int(fk_raw)
                    except (ValueError, TypeError):
                        continue

                    # Check if parent document record has already been synced to cloud in sync_queue
                    parent_sq = db.execute(
                        text("SELECT id FROM sync_queue WHERE business_id = :bid AND entity = :ent AND entity_id = :eid AND synced_at IS NOT NULL"),
                        {"bid": int(business_id), "ent": parent_tbl, "eid": int(fk_val)}
                    ).fetchone()

                    if parent_sq:
                        # Parent invoice synced aggregate payload — mark child row synced
                        item.synced_at = utc_now()
                        item.error = "Already synced via parent aggregate document payload"
                        report["redundant_children_cleared"] = report.get("redundant_children_cleared", 0) + 1
                        continue

                    if not pay.get(uid_key):
                        row = db.execute(
                            text(f'SELECT uid FROM "{parent_tbl}" WHERE id = :id'),
                            {"id": fk_val}
                        ).fetchone()

                        if row and row[0]:
                            uid_str = str(row[0])
                            pay[uid_key] = uid_str
                            item.payload = json.dumps(pay)
                            item.error = None
                            report["payloads_patched"] += 1

            # 2. Repair corrupt / NULL payloads from live ORM
            corrupt_items = db.query(SyncQueue).filter(
                SyncQueue.business_id == business_id,
                SyncQueue.synced_at.is_(None),
                (SyncQueue.payload.is_(None) | SyncQueue.error.like("%Corrupt payload%") | SyncQueue.error.like("%No payload%"))
            ).all()

            conn = db.connection()
            for item in corrupt_items:
                model_cls = MODEL_MAP.get(item.entity)
                if not model_cls:
                    continue
                obj = db.query(model_cls).filter(model_cls.id == item.entity_id).first()
                if obj:
                    item.payload = json.dumps(_serialize_orm_obj(obj, conn), default=str)
                    item.error = None
                    report["corrupt_repaired"] += 1

            # 3. Reset transient push error messages
            transient_keywords = [
                "%Push failed%", "%HTTP 500%", "%HTTP 502%", "%HTTP 503%", "%HTTP 504%",
                "%Timeout%", "%Connection refused%"
            ]
            conditions = [SyncQueue.error.like(kw) for kw in transient_keywords]
            stuck_items = db.query(SyncQueue).filter(
                SyncQueue.business_id == business_id,
                SyncQueue.synced_at.is_(None)
            ).filter(or_(*conditions)).all()

            for item in stuck_items:
                item.error = None
                report["errors_reset"] += 1

            db.flush()
            logger.info("[SELF_HEAL][SYNC] Completed sync outbox heal for biz=%s: %s", business_id, report)
    except Exception as e:
        logger.error("[SELF_HEAL][SYNC] Sync outbox heal failed for biz=%s: %s", business_id, e, exc_info=True)

    return report


# ── Domain 4: Staff & Tenant Security Integrity ─────────────────────────────

def heal_staff_and_tenant_integrity(db: Session, business_id: int) -> Dict[str, Any]:
    """Verify staff account integrity, normalize login names, and resync token versions."""
    report = {
        "names_normalized": 0,
        "tokens_resynced": 0,
    }

    try:
        with db.begin_nested():
            # 1. Normalize staff login names & usernames
            staff_rows = db.query(User).filter(User.parent_business_id == business_id).all()
            for s in staff_rows:
                updated = False
                if not s.staff_login_name or "__" in s.staff_login_name:
                    bare = s.staff_login_name.split("__")[0] if s.staff_login_name else s.username.split("__")[0]
                    s.staff_login_name = bare
                    updated = True

                expected_username = f"{s.staff_login_name}__{s.parent_business_id}"
                if s.username != expected_username and s.username != s.staff_login_name:
                    collision = db.query(User.id).filter(User.username == expected_username, User.id != s.id).first()
                    if not collision:
                        s.username = expected_username
                        updated = True

                if updated:
                    report["names_normalized"] += 1

            # 2. Resync null token versions for tenant users
            tenant_users = db.query(User).filter(
                or_(User.id == business_id, User.parent_business_id == business_id),
                User.token_version.is_(None)
            ).all()

            for u in tenant_users:
                u.token_version = 0
                report["tokens_resynced"] += 1

            db.flush()
            logger.info("[SELF_HEAL][STAFF] Completed staff integrity heal for biz=%s: %s", business_id, report)
    except Exception as e:
        logger.error("[SELF_HEAL][STAFF] Staff heal failed for biz=%s: %s", business_id, e, exc_info=True)

    return report


# ── Master Controller ─────────────────────────────────────────────────────────

def diagnose_and_heal_tenant(db: Session, business_id: int) -> Dict[str, Any]:
    """Central Master Entry Point.
    Executes all 4 repair domains, re-posts unposted journal entries, and returns
    a comprehensive, non-destructive audit summary.
    """
    logger.info("[SELF_HEAL] Master self-healing started for business_id=%s", business_id)

    # 1. Re-post unposted documents & re-seal hash chain
    from core.accounting.repost import repost_unposted_documents
    repost_summary = repost_unposted_documents(db, business_id)

    # 2. Re-seal hash chain explicitly
    hash_chain_healed = heal_hash_chain(db, business_id)

    # 3. Reconcile stock ledger drift
    stock_summary = heal_stock_ledger_drift(db, business_id)

    # 4. Recover sync outbox stalls
    sync_summary = heal_sync_outbox_stalls(db, business_id)

    # 5. Check staff & tenant integrity
    staff_summary = heal_staff_and_tenant_integrity(db, business_id)

    # 6. Evaluate final books integrity after repair
    from core.accounting.integrity import run_integrity_check
    final_integrity = run_integrity_check(db, business_id)

    db.commit()

    result = {
        "ok": final_integrity.get("ok", False),
        "business_id": business_id,
        "repost_summary": repost_summary,
        "hash_chain_healed": hash_chain_healed,
        "stock_summary": stock_summary,
        "sync_summary": sync_summary,
        "staff_summary": staff_summary,
        "final_integrity": final_integrity,
    }

    logger.info("[SELF_HEAL] Master self-healing complete for business_id=%s ok=%s", business_id, result["ok"])
    return result
