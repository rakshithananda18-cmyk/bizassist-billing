"""Create the 40-ID current ledger without rewriting the historical audit."""
from pathlib import Path
import ast
import collections
import csv
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
baseline = json.loads((HERE.parent / 'issues.json').read_text(encoding='utf-8'))
by_id = {}
reports = {'backend-status.json': 'backend-domain.md', 'trust-status.json': 'trust-sync-ops.md',
           'web-status.json': 'web-apps.md', 'root-status.json': 'field-ci-operations.md'}
def text(value):
    if isinstance(value, list):
        return ' '.join(str(v) for v in value)
    return str(value or '')
for filename, report in reports.items():
    payload = json.loads((HERE / filename).read_text(encoding='utf-8'))
    records = payload if isinstance(payload, list) else payload['issues']
    for item in records:
        assert item['id'] not in by_id
        by_id[item['id']] = (item, filename, report)
assert set(by_id) == {r['id'] for r in baseline}
rows = []
for old in baseline:
    current, filename, report = by_id[old['id']]
    assert current['status'] in {'fixed', 'partial', 'open', 'unverified'}
    fixed = current.get('resolution') or current.get('fixed_part') or current.get('summary') or text(current.get('verified'))
    remaining = current.get('remaining') or current.get('remaining_condition') or text(current.get('remaining_conditions'))
    refs = current.get('current_file_line') or current.get('current_evidence') or current.get('source')
    if not refs and isinstance(current.get('evidence'), list):
        refs = current['evidence']
    observations = current.get('evidence') if isinstance(current.get('evidence'), str) else text(current.get('verified'))
    rows.append({'id': old['id'], 'date': '2026-10-30', 'original_priority': old['priority'],
                 'title': old['title'], 'status': current['status'], 'verified_change': text(fixed),
                 'remaining': text(remaining), 'observations': observations or '',
                 'current_locations': '; '.join(refs) if isinstance(refs, list) else refs or '',
                 'report': report, 'detail_file': filename})
(HERE / 'issue-status.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
with (HERE / 'issue-status.csv').open('w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
counts = dict(collections.Counter(r['status'] for r in rows))
snapshot = json.loads((HERE / 'reviewed-snapshot.json').read_text(encoding='utf-8'))
drift = []
for row in snapshot['files']:
    path = ROOT / row['path']
    if path.is_file() != row['exists'] or path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        drift.append(row['path'])
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
summary = {'date': '2026-10-30', 'reviewed_head': head, 'includes_uncommitted_working_tree': True,
           'original_issue_count': len(baseline), 'counts': counts,
           'not_closed': sum(r['status'] != 'fixed' for r in rows),
           'not_closed_by_original_priority': dict(collections.Counter(r['original_priority'] for r in rows if r['status'] != 'fixed')),
           'head_unchanged_during_review': head == snapshot['head'], 'source_drift_during_review': drift,
           'product_changes_made_by_review': False,
           'status_meaning': 'Fixed is local correction/containment of the original defect, not a production, migration, historical-data or full-release certification.'}
(HERE / 'verification-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
table = ['| ID | Original priority | Status | Verified change / remaining work |', '|---|---|---|---|']
for row in rows:
    note = row['verified_change'] if row['status'] == 'fixed' else row['remaining']
    note = note.replace('|', '/').replace('\n', ' ')
    table.append(f"| {row['id']} | {row['original_priority']} | **{row['status']}** | {note} |")
(HERE / 'STATUS.md').write_text('# All 40 remediation statuses — 30 October 2026\n\n'
    + 'Reviewed HEAD `'+head+'` plus the unstaged and new files captured in `reviewed-snapshot.json`. '
    + 'Detailed observations, current source locations and individual reports are linked in `issue-status.csv` and JSON. '
    + 'Fixed includes explicit safe containment where a feature was disabled; deployment and historical-data proof remain separate.\n\n'
    + '\n'.join(table)+'\n', encoding='utf-8')
for path in HERE.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
print(json.dumps(summary, indent=2))
assert not drift, 'The reviewed implementation changed during verification; reassess drift before delivering.'
