"""Validate audit consistency; never import product code or open live databases."""
import ast
import collections
import csv
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
issues = json.loads((HERE / 'issues.json').read_text(encoding='utf-8'))
errors = []
ids = [issue['id'] for issue in issues]
if len(ids) != len(set(ids)):
    errors.append('Duplicate issue IDs')
for issue in issues:
    source, line = issue['source'].rsplit(':', 1)
    path = ROOT / source
    if not path.is_file() or int(line) > len(path.read_text(encoding='utf-8-sig').splitlines()):
        errors.append('Invalid issue source: ' + issue['id'])
    if not (HERE / issue['report']).is_file():
        errors.append('Missing issue report: ' + issue['id'])
with (HERE / 'issues.csv').open(encoding='utf-8', newline='') as f:
    if list(csv.DictReader(f)) != issues:
        errors.append('CSV and JSON issue registers disagree')
with (HERE / 'file-coverage.csv').open(encoding='utf-8', newline='') as f:
    coverage = list(csv.DictReader(f))
for row in coverage:
    path = ROOT / row['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        errors.append('Baseline content changed: ' + row['path'])
for path in HERE.glob('*.md'):
    content = path.read_text(encoding='utf-8')
    for source, line in re.findall(r'((?:backend|backend-task|frontend-billing|frontend-task|frontend-ai|frontend-admin|desktop|bizassist-landing|\.github|docs|ops)/[\w./-]+\.(?:py|js|jsx|yml|md)):(\d+)', content):
        referenced = ROOT / source
        if not referenced.is_file() or int(line) > len(referenced.read_text(encoding='utf-8-sig').splitlines()):
            errors.append(f'Invalid Markdown source in {path.name}: {source}:{line}')
    for target in re.findall(r'\]\(([^)]+)\)', content):
        if '://' not in target and not target.startswith('#'):
            local = target.split('#')[0].strip('<>')
            if not (path.parent / local).exists():
                errors.append(f'Broken local link in {path.name}: {target}')
for path in HERE.glob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'), filename=path.name)
for path in HERE.glob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
summary = {'date': '2026-10-30', 'tracked_files_verified': len(coverage),
           'issue_count': len(issues), 'priorities': dict(collections.Counter(i['priority'] for i in issues)),
           'checks': ['unique issue IDs', 'CSV/JSON parity', 'issue source files and line bounds',
                      'baseline file hashes', 'Markdown source bounds', 'local Markdown links', 'audit Python/JSON syntax'],
           'errors': errors}
(HERE / 'artifact-validation.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
assert not errors
