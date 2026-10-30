"""Demonstrate unsafe equal-total donor selection on a temporary synthetic DB."""
from pathlib import Path
import contextlib
import io
import json
import os
import runpy
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[3]
temp = Path(tempfile.mkdtemp(prefix='bizassist_repair_audit_test_'))
(temp / 'backend').mkdir()
db_path = temp / 'backend' / 'bizassist.db'
conn = sqlite3.connect(db_path)
conn.execute('CREATE TABLE invoices(id INTEGER PRIMARY KEY, invoice_id TEXT, total_amount REAL, subtotal REAL, business_id INTEGER)')
columns = ['product_name TEXT', 'description TEXT', 'hsn_sac TEXT', 'batch_no TEXT', 'serial_no TEXT',
           'quantity REAL', 'unit TEXT', 'unit_price REAL', 'discount REAL', 'taxable_value REAL',
           'cgst_rate REAL', 'cgst_amount REAL', 'sgst_rate REAL', 'sgst_amount REAL', 'igst_rate REAL',
           'igst_amount REAL', 'cess_amount REAL', 'line_total REAL', 'created_at TEXT', 'updated_at TEXT', 'business_id INTEGER']
conn.execute('CREATE TABLE invoice_line_items(id INTEGER PRIMARY KEY, invoice_id INTEGER, '+','.join(columns)+')')
conn.executemany('INSERT INTO invoices VALUES(?,?,?,?,?)', [(1,'LCL-MISSING',100,100,1), (2,'UNRELATED',100,100,1)])
conn.execute("INSERT INTO invoice_line_items(invoice_id,product_name,quantity,unit_price,line_total,business_id) VALUES(2,'Unrelated medicine',1,100,100,1)")
conn.commit()
conn.close()
original = Path.cwd()
try:
    os.chdir(temp)
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(ROOT / 'repair_line_items.py'), run_name='__main__')
finally:
    os.chdir(original)
with sqlite3.connect(db_path) as conn:
    copied = conn.execute('SELECT product_name FROM invoice_line_items WHERE invoice_id=1').fetchall()
assert copied == [('Unrelated medicine',)]
print(json.dumps({'finding':'OPS-01','unrelated_donor_copied':True,'basis':'same business and equal total only',
                  'scope':'unmodified repair script, synthetic temporary SQLite DB'}, indent=2))
