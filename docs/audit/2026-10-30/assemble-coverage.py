"""Combine review ledgers against the immutable tracked-file snapshot."""
from pathlib import Path
import collections
import csv
import json

HERE = Path(__file__).resolve().parent
inventories = ['backend-domain-coverage.csv', 'trust-sync-ops-coverage.csv', 'additional-coverage.csv',
               'web-apps-coverage.csv', 'field-release-plans-coverage.csv']
reviews = collections.defaultdict(list)
for filename in inventories:
    with (HERE / filename).open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            reviews[row['path'].replace('\\', '/')].append((filename, row))
with (HERE / 'tracked-files.csv').open(encoding='utf-8-sig', newline='') as f:
    baseline = list(csv.DictReader(f))
combined, gaps = [], []
for row in baseline:
    path = row['path']
    assigned = reviews[path]
    active = [(name, detail) for name, detail in assigned if detail['review_depth'] != 'excluded']
    if row['kind'] == 'binary':
        level = 'binary-metadata'
    elif any(detail['review_depth'] == 'deep' for _, detail in active):
        level = 'targeted-source-trace'
    elif any(detail['review_depth'] == 'test-run' for _, detail in active):
        level = 'test-file-exercised'
    elif active:
        level = 'automated-or-test-source-screen'
    else:
        level = 'coverage-gap'
        gaps.append(path)
    combined.append({**row, 'combined_review_depth': level,
        'review_ledgers': '; '.join(f"{name}:{detail['review_depth']}" for name, detail in assigned)})
with (HERE / 'file-coverage.csv').open('w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=combined[0].keys())
    writer.writeheader()
    writer.writerows(combined)
summary = {'baseline_files': len(combined), 'coverage_gaps': gaps,
           'review_depth_counts': dict(collections.Counter(r['combined_review_depth'] for r in combined)),
           'meaning': 'Depth describes selected evidence, not a guarantee that every line or branch is correct. Test-file coverage does not imply every test passed or none skipped.'}
(HERE / 'coverage-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
assert not gaps, 'Some baseline files have no assigned review ledger'
