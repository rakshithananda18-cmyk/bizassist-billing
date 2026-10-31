"""Repair requires explicit provenance, matching facts and recoverable evidence."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location("line_repair", Path(__file__).resolve().parents[2] / "repair_line_items.py")
repair_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair_module)


@pytest.fixture
def fixture_db(tmp_path):
    path = tmp_path / "test_repairs.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
          CREATE TABLE users(id INTEGER PRIMARY KEY, public_id TEXT, parent_business_id INTEGER);
          CREATE TABLE invoices(id INTEGER PRIMARY KEY, uid TEXT, business_id INTEGER,
            invoice_id TEXT, subtotal REAL, total_amount REAL, cgst_total REAL,
            sgst_total REAL, igst_total REAL, cess_total REAL, round_off REAL);
          CREATE TABLE invoice_line_items(id INTEGER PRIMARY KEY, uid TEXT UNIQUE,
            invoice_id INTEGER REFERENCES invoices(id), business_id INTEGER,
            product_name TEXT, quantity REAL, taxable_value REAL, line_total REAL,
            cgst_amount REAL, sgst_amount REAL, igst_amount REAL, cess_amount REAL);
          INSERT INTO users VALUES(1,'TEST-BIZ',NULL),(2,'OTHER-BIZ',NULL);
          INSERT INTO invoices VALUES(1,'target',1,'LCL-1',10,12,1,1,0,0,0);
          INSERT INTO invoices VALUES(2,'donor',1,'1',10,12,1,1,0,0,0);
          INSERT INTO invoices VALUES(3,'other',2,'1',10,12,1,1,0,0,0);
          INSERT INTO invoice_line_items VALUES(1,'original',2,1,'Synthetic item',1,10,12,1,1,0,0);
        """)
    mappings = [{"business_bizid": "TEST-BIZ", "target_invoice_uid": "target",
                 "donor_invoice_uid": "donor", "reason": "Synthetic independently confirmed source"}]
    return path, mappings


def test_dry_run_is_read_only_and_never_guesses(fixture_db):
    path, mappings = fixture_db
    before = path.read_bytes()
    result = repair_module.repair(path, mappings)
    assert (result["mode"], result["lines"]) == ("dry_run", 1)
    assert path.read_bytes() == before
    with pytest.raises(repair_module.RepairRefused):
        repair_module.repair(path, [])


def test_apply_has_encrypted_recoverable_backup_and_no_duplicate_replay(fixture_db, tmp_path):
    path, mappings = fixture_db
    password = "fixture" * 4
    result = repair_module.repair(path, mappings, apply=True, backup_dir=tmp_path / "private", password=password)
    encrypted = Path(result["backup"])
    assert "Synthetic item" not in encrypted.read_text()
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT uid,quantity,line_total FROM invoice_line_items WHERE invoice_id=1").fetchall()
    assert len(rows) == 1 and rows[0][0] != "original" and rows[0][1:] == (1, 12)
    restored = repair_module.restore_backup(encrypted, password, tmp_path / "restored.db")
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id=1").fetchone()[0] == 0
    with pytest.raises(FileExistsError):
        repair_module.restore_backup(encrypted, password, restored)
    with pytest.raises(repair_module.RepairRefused):
        repair_module.repair(path, mappings, apply=True, backup_dir=tmp_path / "private", password=password)


@pytest.mark.parametrize("failure", ["cross_business", "wrong_total", "no_backup"])
def test_refuses_inconsistent_or_unrecoverable_repairs(fixture_db, tmp_path, failure):
    path, mappings = fixture_db
    if failure == "cross_business":
        mappings[0]["donor_invoice_uid"] = "other"
    elif failure == "wrong_total":
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE invoice_line_items SET line_total=99")
    before = path.read_bytes()
    with pytest.raises(repair_module.RepairRefused):
        repair_module.repair(path, mappings, apply=True, backup_dir=None if failure == "no_backup" else tmp_path / "private", password="fixture" * 4)
    assert path.read_bytes() == before
