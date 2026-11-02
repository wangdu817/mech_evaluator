"""Audit actual saved-result comparison, download contents and immutable sources."""
from pathlib import Path
import csv
import hashlib
import json
import zipfile
from collections import Counter

root = Path(__file__).resolve().parents[1]
base = root/'results/multi-mechanism'
manifest = json.loads((base/'web-saved-comparison/manifest.json').read_text(encoding='utf8'))
assert manifest['saved_comparison']['simulations_executed'] == 0
assert len(manifest['cases']) == 24
assert Counter(r['status'] for r in manifest['results']) == {'success':24}
assert {c['mechanism']['id'] for c in manifest['cases']} == {'audited_working','N_CHO_240725_working'}
rows = list(csv.DictReader((base/'web-saved-comparison/comparison.csv').open(encoding='utf-8-sig')))
assert len(rows) == 72
with zipfile.ZipFile(base/'evidence/saved-comparison-export.zip') as archive:
    names = archive.namelist()
    assert any(n.endswith('figure.yaml') for n in names)
    assert all(any(n.endswith(ext) for n in names) for ext in ('.csv','.png','.pdf','.svg'))
audit = json.loads((base/'inputs/audit.json').read_text(encoding='utf8'))
for path, expected in audit['original_inputs'].items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
batch = json.loads((base/'run/manifest.json').read_text(encoding='utf8'))
counts = dict(Counter(r['status'] for r in batch['results']))
assert counts == {'success':172,'solver_failed':2,'invalid_input':18}
for result in manifest['results']:
    assert result['validation']['passed']
report = {'comparison_cases':24,'comparison_measurements':len(rows),'mechanisms':sorted({c['mechanism']['id'] for c in manifest['cases']}),
          'simulations_executed':0,'actual_batch_status':counts,'original_mechanism_and_thermo_unchanged':True,
          'download_entries':names,'browser_merge_and_mechanism_selection':True}
(base/'evidence/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
