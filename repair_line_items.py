"""Evidence-based SQLite line repair. Importing this module never opens a DB.

Dry run: python repair_line_items.py --database PATH --mapping mapping.json
Apply requires --apply --backup-dir PRIVATE_DIR and a 16+ character password.
Mapping: {"repairs": [{"business_bizid": "...", "target_invoice_uid": "...",
"donor_invoice_uid": "...", "reason": "independently verified provenance"}]}.
Invoice numbers and equal amounts never select donors automatically.
"""
from __future__ import annotations
import argparse
import base64
from decimal import Decimal
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid


class RepairRefused(ValueError):
    pass


def money(value):
    number = Decimal(str(value or 0))
    if not number.is_finite():
        raise RepairRefused("Non-finite document amount")
    return number.quantize(Decimal("0.01"))


def _invoice(conn, uid, bid):
    rows = conn.execute("SELECT * FROM invoices WHERE uid=? AND business_id=?", (uid, bid)).fetchall()
    if len(rows) != 1:
        raise RepairRefused("Mapped invoice UID is absent or ambiguous for this business")
    return dict(rows[0])


def plan_repairs(conn, mappings):
    if not isinstance(mappings, list) or not mappings:
        raise RepairRefused("An explicit non-empty repairs mapping is required")
    plans, targets = [], set()
    for item in mappings:
        for key in ("business_bizid", "target_invoice_uid", "donor_invoice_uid", "reason"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise RepairRefused("Mapping requires BizID, target/donor UIDs and an evidence reason")
        businesses = conn.execute("SELECT id FROM users WHERE public_id=? AND parent_business_id IS NULL", (item["business_bizid"],)).fetchall()
        if len(businesses) != 1:
            raise RepairRefused("Mapped business BizID is absent or ambiguous")
        bid = businesses[0][0]
        target = _invoice(conn, item["target_invoice_uid"], bid)
        donor = _invoice(conn, item["donor_invoice_uid"], bid)
        if target["id"] == donor["id"] or target["id"] in targets:
            raise RepairRefused("Target must be distinct from donor and appear only once")
        targets.add(target["id"])
        if conn.execute("SELECT 1 FROM invoice_line_items WHERE invoice_id=?", (target["id"],)).fetchone():
            raise RepairRefused("Target already has lines; refusing to append or replace financial facts")
        lines = [dict(r) for r in conn.execute("SELECT * FROM invoice_line_items WHERE invoice_id=? ORDER BY id", (donor["id"],))]
        if not lines:
            raise RepairRefused("Explicit donor has no line evidence")
        for key in ("subtotal", "total_amount", "cgst_total", "sgst_total", "igst_total", "cess_total", "discount_total", "round_off", "cash_discount"):
            if key in target and money(target[key]) != money(donor[key]):
                raise RepairRefused("Mapped document headers disagree: " + key)
        for key in ("invoice_type", "customer_id", "gstin_buyer", "place_of_supply", "is_tax_inclusive"):
            if key in target and target[key] != donor[key]:
                raise RepairRefused("Mapped document identities/tax policy disagree: " + key)
        for line in lines:
            if line.get("business_id") not in (None, bid):
                raise RepairRefused("Donor line belongs to another business")
            if line.get("product_id") is not None:
                product = conn.execute("SELECT business_id FROM products WHERE id=?", (line["product_id"],)).fetchone()
                if product is None or product[0] != bid:
                    raise RepairRefused("Donor line has an unverified product identity")
        for header, detail in (("subtotal", "taxable_value"), ("cgst_total", "cgst_amount"),
                               ("sgst_total", "sgst_amount"), ("igst_total", "igst_amount"), ("cess_total", "cess_amount")):
            if header in target and detail in lines[0] and abs(sum(money(l.get(detail)) for l in lines) - money(target[header])) > Decimal("0.01"):
                raise RepairRefused("Donor line/header invariant failed: " + header)
        total = sum(money(l["line_total"]) for l in lines)
        expected = money(target.get("total_amount", target.get("amount"))) - money(target.get("round_off")) + money(target.get("cash_discount"))
        if abs(total - expected) > Decimal("0.01"):
            raise RepairRefused("Donor lines do not reproduce the target total")
        plans.append({"business_id": bid, "target": target, "lines": lines, "mapping": item})
    return plans


def _encrypted_backup(database, output_dir, password, mappings):
    if len(password or "") < 16:
        raise RepairRefused("Backup password must contain at least 16 characters")
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    # Another read connection sees the exact committed state while our repair
    # transaction holds its write reservation; no financial mutation yet.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        memory = sqlite3.connect(":memory:")
        try:
            source.backup(memory)
            dump = "\n".join(memory.iterdump()).encode("utf-8")
        finally:
            memory.close()
    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode("utf-8"))
    plaintext = json.dumps({"sql": dump.decode(), "mapping": mappings}).encode()
    cipher = AESGCM(key).encrypt(nonce, plaintext, b"bizassist-repair-backup-v1")
    b64 = lambda data: base64.b64encode(data).decode("ascii")
    envelope = {"format": "bizassist-repair-backup-v1", "kdf": "scrypt-n32768-r8-p1",
                "salt": b64(salt), "nonce": b64(nonce), "ciphertext": b64(cipher),
                "sql_sha256": hashlib.sha256(dump).hexdigest()}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / ("line-repair-" + uuid.uuid4().hex + ".encrypted.json")
    with path.open("x", encoding="utf-8") as f:
        json.dump(envelope, f)
    restored = AESGCM(key).decrypt(nonce, base64.b64decode(envelope["ciphertext"]), b"bizassist-repair-backup-v1")
    if json.loads(restored)["sql"].encode() != dump:
        raise RepairRefused("Encrypted backup verification failed")
    return path


def restore_backup(archive, password, destination):
    """Restore only into a NEW path, never overwrite a developer/production DB."""
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    envelope = json.loads(Path(archive).read_text(encoding="utf-8"))
    if envelope.get("format") != "bizassist-repair-backup-v1" or envelope.get("kdf") != "scrypt-n32768-r8-p1":
        raise RepairRefused("Unrecognized encrypted backup format")
    dec = base64.b64decode
    key = Scrypt(salt=dec(envelope["salt"]), length=32, n=32768, r=8, p=1).derive(password.encode())
    payload = json.loads(AESGCM(key).decrypt(dec(envelope["nonce"]), dec(envelope["ciphertext"]), b"bizassist-repair-backup-v1"))
    if hashlib.sha256(payload["sql"].encode()).hexdigest() != envelope["sql_sha256"]:
        raise RepairRefused("Backup digest mismatch")
    destination = Path(destination)
    # Exclusive create reserves the output; an existing database is never used.
    with destination.open("xb"):
        pass
    try:
        with sqlite3.connect(destination) as conn:
            conn.executescript(payload["sql"])
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RepairRefused("Restored database failed integrity check")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def repair(database, mappings, *, apply=False, backup_dir=None, password=None):
    database = Path(database).resolve(strict=True)
    if not database.is_file():
        raise RepairRefused("Explicit database path must be a regular file")
    uri = database.as_uri() + ("?mode=rw" if apply else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        plans = plan_repairs(conn, mappings)
        backup = None
        if apply:
            if not backup_dir:
                raise RepairRefused("Apply requires an explicit private backup directory")
            backup = _encrypted_backup(database, Path(backup_dir), password, mappings)
            for plan in plans:
                for original in plan["lines"]:
                    line = dict(original)
                    line.pop("id", None)
                    line["invoice_id"] = plan["target"]["id"]
                    if "uid" in line:
                        line["uid"] = str(uuid.uuid4())
                    if "business_id" in line:
                        line["business_id"] = plan["business_id"]
                    # Column names originate only from SQLite table metadata.
                    columns = ",".join('"' + key + '"' for key in line)
                    placeholders = ",".join("?" for _ in line)
                    conn.execute(f"INSERT INTO invoice_line_items ({columns}) VALUES ({placeholders})", tuple(line.values()))
            conn.commit()
        else:
            conn.rollback()
        return {"mode": "applied" if apply else "dry_run", "documents": len(plans),
                "lines": sum(len(p["lines"]) for p in plans), "backup": str(backup) if backup else None}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir")
    parser.add_argument("--password-env", help="Environment variable containing the backup password")
    args = parser.parse_args(argv)
    try:
        mappings = json.loads(Path(args.mapping).read_text(encoding="utf-8"))["repairs"]
        password = None
        if args.apply:
            password = os.environ.get(args.password_env) if args.password_env else getpass.getpass("Private backup password (16+ characters): ")
        print(json.dumps(repair(args.database, mappings, apply=args.apply, backup_dir=args.backup_dir, password=password)))
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        print("Repair refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
