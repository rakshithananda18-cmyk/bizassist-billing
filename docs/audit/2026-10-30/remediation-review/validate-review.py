"""Check only the new remediation evidence; preserve historical audit artifacts."""
from pathlib import Path
import ast
import csv
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
errors = []
rows = json.loads((HERE / 'issue-status.json').read_text(encoding='utf-8'))
with (HERE / 'issue-status.csv').open(encoding='utf-8', newline='') as f:
    if list(csv.DictReader(f)) != rows:
        errors.append('Current CSV/JSON status registers differ')
original = json.loads((HERE.parent / 'issues.json').read_text(encoding='utf-8'))
if {r['id'] for r in rows} != {r['id'] for r in original} or len(rows) != 40:
    errors.append('Current register does not cover exactly the original 40 IDs')
for row in rows:
    for reference in row['current_locations'].split('; '):
        if not reference:
            continue
        match = re.fullmatch(r'(.+):(\d+)', reference)
        if match:
            path = ROOT / match[1]
            if not path.is_file() or int(match[2]) > len(path.read_text(encoding='utf-8-sig').splitlines()):
                errors.append('Invalid current source location: ' + reference)
for path in HERE.rglob('*.md'):
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
        if '://' not in target and not target.startswith('#'):
            if not (path.parent / target.split('#')[0].strip('<>')).exists():
                errors.append(f'Broken review link: {path.name}: {target}')
for path in HERE.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
for path in HERE.rglob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
result = {'date': '2026-10-30', 'issues_checked': len(rows),
          'checks': ['complete original-ID coverage', 'CSV/JSON parity', 'current source bounds',
                     'review links', 'review Python/JSON syntax'], 'errors': errors}
(HERE / 'review-validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
assert not errors
