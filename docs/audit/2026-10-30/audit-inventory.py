"""Inventory tracked source without importing product code or opening runtime data."""
import ast
import collections
import csv
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs' / 'audit' / '2026-10-30'
OUT.mkdir(parents=True, exist_ok=True)
files = subprocess.check_output(['git', '-c', 'core.fsmonitor=false', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
rows, errors = [], []
root_deep = {'repair_line_items.py', 'check_db.py', 'debug_fk.py', 'debug_lineitem.py', 'debug_remap.py',
             'start_dev.bat', 'run_tests.ps1', '.gitignore', '.gitleaks.toml', '.pre-commit-config.yaml',
             'README.md', 'dev/dev_env.ps1', 'dev/check_cloud_release.py', 'serve_dashboard.py', 'dependencies.bat',
             'backend-task/app/security.py', 'backend-task/app/config.py', 'backend-task/app/db.py',
             'backend-task/app/main.py', 'backend-task/app/models.py', 'backend-task/app/invoices.py',
             'backend-task/app/billing_context.py', 'backend-task/app/collections.py', 'backend-task/app/services.py',
             'backend-task/app/geo.py', 'backend-task/app/plan.py', 'backend-task/app/routers/auth.py',
             'backend-task/app/routers/attendance.py', 'backend-task/app/routers/tasks.py', 'backend-task/app/routers/runs.py',
             'backend-task/app/routers/requests.py', 'backend-task/app/routers/shops.py', 'backend-task/app/routers/tracking.py',
             'backend-task/app/routers/dashboard.py', 'backend-task/tests/conftest.py',
             'frontend-task/src/lib/api.js', 'frontend-task/src/lib/auth.jsx', 'frontend-task/src/lib/tracker.js',
             'frontend-task/src/layouts/StaffLayout.jsx', 'frontend-task/src/pages/staff/Today.jsx',
             'frontend-task/src/pages/staff/NewRequest.jsx', 'frontend-task/src/components/NotificationBell.jsx',
             'frontend-task/public/sw.js', 'frontend-task/src/App.jsx',
             '.github/workflows/ci.yml', '.github/workflows/field-team.yml', '.github/workflows/release.yml',
             '.github/workflows/db-backup.yml',
             'docs/MASTER_PLAN.md', 'docs/ARCHITECTURE.md', 'docs/FIELD_TEAM_MASTER_PLAN.md',
             'docs/plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md', 'docs/plans/BIZASSIST_BUILD_PLAN_NEXT_3_PHASES.md',
             'docs/plans/REALTIME_SYNC_ROBUSTNESS_PLAN.md', 'docs/plans/HOSTING_MODE_MASTER_PLAN.md',
             'docs/plans/PHASE_COMPLETION_CHECKLIST.md', 'docs/release/2026-10-28-verification.md',
             'docs/release/2026-10-29-field-app-agent-audit.md', 'docs/release/2026-10-29-sync-import-lifecycle-review.md'}
for name in filter(None, files):
    path = ROOT / name
    data = path.read_bytes()
    binary = b'\0' in data[:8192] or path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.ico', '.woff', '.woff2', '.ttf', '.pdf', '.xlsx'}
    content = '' if binary else data.decode('utf-8-sig', errors='replace')
    validation = 'binary metadata only' if binary else 'text inventory/content-pattern screening'
    if path.suffix == '.py':
        try:
            tree = ast.parse(content, filename=name)
            validation = 'Python AST parse passed'
        except SyntaxError as exc:
            validation = f'Python AST parse failed at {exc.lineno}: {exc.msg}'
            errors.append({'path': name, 'line': exc.lineno, 'error': exc.msg})
    elif path.suffix == '.json' or path.name.endswith('.webmanifest'):
        try:
            json.loads(content)
            validation = 'JSON parse passed'
        except ValueError as exc:
            validation = f'JSON parse failed: {exc}'
            errors.append({'path': name, 'error': str(exc)})
    root_owned = name.startswith(('backend-task/', 'frontend-task/', 'docs/', 'dev/', '.github/', 'sample_data/')) or '/' not in name
    depth = 'screened'
    if root_owned and name in root_deep:
        depth = 'deep'
    if depth != 'deep' and (root_owned and '/tests/' in name or name.startswith('frontend-task/') and '.test.' in name):
        depth = 'test'
    if binary:
        depth = 'metadata-only'
    rows.append({'path': name, 'bytes': len(data), 'lines': content.count('\n') + bool(content),
                 'sha256': hashlib.sha256(data).hexdigest(), 'kind': 'binary' if binary else 'text',
                 'validation': validation, 'primary_auditor': 'root' if root_owned else 'agent',
                 'review_depth': depth if root_owned else 'await-agent-coverage'})
with (OUT / 'tracked-files.csv').open('w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
with (OUT / 'field-release-plans-coverage.csv').open('w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['path', 'review_depth', 'notes'])
    writer.writeheader()
    writer.writerows({'path': r['path'], 'review_depth': r['review_depth'], 'notes': r['validation']} for r in rows if r['primary_auditor'] == 'root')
summary = {'baseline': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
           'date': '2026-10-30', 'timezone': 'Asia/Kolkata', 'tracked_files': len(rows),
           'roots': dict(collections.Counter(r['path'].split('/')[0] if '/' in r['path'] else '(root)' for r in rows)),
           'binary_files': sum(r['kind'] == 'binary' for r in rows),
           'text_lines': sum(r['lines'] for r in rows), 'syntax_errors': errors}
(OUT / 'inventory-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
