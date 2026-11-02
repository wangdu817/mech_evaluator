"""Read-only audit of current input inventory against saved batch snapshots."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
from pyteck.respecth.reader import discover_experiments
from pyteck.respecth.models import file_hash

root = Path(__file__).resolve().parents[1]
files = discover_experiments(root.parent)
current = {str(p.resolve()): {'sha256': file_hash(p),
    'points': len(ET.parse(p).findall('dataGroup/dataPoint'))} for p in files}
comparisons = []
for path in sorted((root/'results/ui-run/saved-batches').glob('*/manifest.json')):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if len(manifest.get('experiments', [])) != len(files):
        continue
    changed = []
    for record in manifest['experiments']:
        actual = current.get(str(Path(record['path']).resolve()))
        if actual and record['sha256'] != actual['sha256']:
            changed.append({'xml': record['path'], 'old_sha256': record['sha256'],
                'current_sha256': actual['sha256'],
                'old_points': sum(len(g['points']) for g in record['groups']),
                'current_points': actual['points']})
    if changed:
        comparisons.append({'manifest': str(path), 'changed': changed})
report = {'xml_count': len(files), 'current_raw_points': sum(r['points'] for r in current.values()),
    'inputs': current, 'historical_differences': comparisons}
(root/'results/cache-review/input-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'xml_count': len(files), 'current_raw_points': report['current_raw_points'],
    'changed_snapshots': len(comparisons), 'latest_difference': comparisons[-1] if comparisons else None},ensure_ascii=False))
