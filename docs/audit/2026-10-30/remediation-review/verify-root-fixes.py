"""Verify repair containment and source/release facts without live data access."""
from pathlib import Path
import ast
import contextlib
import io
import json
import os
import runpy
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
temp = Path(tempfile.mkdtemp(prefix='repair_review_test_', dir=ROOT / 'scratch'))
(temp / 'backend').mkdir()
db_path = temp / 'backend' / 'bizassist.db'
with sqlite3.connect(db_path) as conn:
    conn.execute('CREATE TABLE invoices(id INTEGER PRIMARY KEY, invoice_id TEXT, total_amount REAL, subtotal REAL, business_id INTEGER)')
    columns = ['product_name TEXT', 'description TEXT', 'hsn_sac TEXT', 'batch_no TEXT', 'serial_no TEXT',
               'quantity REAL', 'unit TEXT', 'unit_price REAL', 'discount REAL', 'taxable_value REAL',
               'cgst_rate REAL', 'cgst_amount REAL', 'sgst_rate REAL', 'sgst_amount REAL', 'igst_rate REAL',
               'igst_amount REAL', 'cess_amount REAL', 'line_total REAL', 'created_at TEXT', 'updated_at TEXT', 'business_id INTEGER']
    conn.execute('CREATE TABLE invoice_line_items(id INTEGER PRIMARY KEY, invoice_id INTEGER, '+','.join(columns)+')')
    conn.executemany('INSERT INTO invoices VALUES(?,?,?,?,?)', [(1,'LCL-MISSING',100,100,1), (2,'UNRELATED',100,100,1)])
    conn.execute("INSERT INTO invoice_line_items(invoice_id,product_name,quantity,unit_price,line_total,business_id) VALUES(2,'Synthetic unrelated item',1,100,100,1)")
original = Path.cwd()
try:
    os.chdir(temp)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        runpy.run_path(str(ROOT / 'repair_line_items.py'), run_name='__main__')
finally:
    os.chdir(original)
with sqlite3.connect(db_path) as conn:
    copied = conn.execute('SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id=1').fetchone()[0]
assert copied == 0, 'Equal-total fallback still fabricated lines'
tracked_exports = subprocess.check_output(['git', '-c', 'core.fsmonitor=false', 'ls-files', 'backend/voided_payment_*.json'], cwd=ROOT, text=True).splitlines()
ignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
field_ci = (ROOT / '.github/workflows/field-team.yml').read_text(encoding='utf-8')
foundation = (ROOT / 'backend/FOUNDATION.md').read_text(encoding='utf-8')
historical_issues = json.loads((HERE.parent / 'issues.json').read_text(encoding='utf-8'))
repair_source = (ROOT / 'repair_line_items.py').read_text(encoding='utf-8')
result = {
    'OPS-01': {'equal_total_fallback_refused': True, 'live_default_path_remains': 'DB = "backend/bizassist.db"' in repair_source, 'dry_run_default_present': '--dry-run' in repair_source},
    'OPS-02': {'tracked_financial_snapshot_count': len(tracked_exports), 'ignore_rule_occurrences': ignore.count('backend/voided_payment_*.json'), 'financial_values_read_or_printed': False},
    'CI-01': {'admin_test_build_added': 'Test and build frontend-admin' in ci, 'billing_build_added': 'Build frontend-billing' in ci, 'field_core_models_trigger_added': 'backend/core/models.py' in field_ci, 'field_cleanup_trigger': 'backend/services/field_business_cleanup.py' in field_ci, 'field_collections_trigger': 'backend/core/field_team.py' in field_ci, 'contract_uses_create_all': 'Base.metadata.create_all' in field_ci, 'secret_scan_job_present': 'gitleaks' in ci, 'landing_job_present': 'bizassist-landing' in ci},
    'DOC-01': {'foundation_historical_status_marker_added': 'Status Marker (2026-10-30)' in foundation, 'original_register_statuses': sorted(set(x['status'] for x in historical_issues)), 'scope_note': 'Original baseline audit is intentionally historical; this review supplies the current status matrix.'},
}
(HERE / 'root-proof-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
