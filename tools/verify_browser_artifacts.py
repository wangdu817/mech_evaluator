"""Verify artifacts produced by manual real-browser end-to-end operations."""
from pathlib import Path
from collections import Counter
import csv
import io
import json
import zipfile
import xml.etree.ElementTree as ET
import h5py
from PIL import Image
from pyteck.respecth.runner import load_config

root = Path(__file__).resolve().parents[1]
directory = root/'results/browser-e2e'
report = {'browser': 'actual in-app browser', 'service': 'http://127.0.0.1:8501'}
for folder, count in [('full', 26), ('chemkin-run', 2), ('cancel-clean', 80), ('cancel-flame', 6)]:
    manifest = json.loads((directory/folder/'manifest.json').read_text(encoding='utf8'))
    assert len(manifest['results']) == count
    assert all(r['status'] == 'success' and r['validation'].get('passed') is True for r in manifest['results'])
    for result in manifest['results']:
        with h5py.File(result['history_path']) as history:
            assert history['temperature'].size > 1
            assert history['mole_fractions'].shape[0] == history['temperature'].size
    report[folder] = {'verified': count, 'status': manifest['status']}

cancelled = json.loads((directory/'cancelled-flame-manifest.json').read_text(encoding='utf8'))
assert Counter(r['status'] for r in cancelled['results']) == {'success': 4, 'cancelled': 2}
for name in ['cancelled-flame-history-times.json', 'history-times-before-postprocess.json']:
    saved = json.loads((directory/name).read_text())
    assert all(Path(path).stat().st_mtime_ns == timestamp for path, timestamp in saved.items())
    report[name] = {'unchanged_histories': len(saved)}

with zipfile.ZipFile(directory/'downloaded-results.zip') as archive:
    assert archive.testzip() is None
    rows = list(csv.DictReader(io.StringIO(archive.read('comparison.csv').decode('utf-8-sig'))))
    assert len(rows) == 34 and all(row['property_id'] and row['case_id'] for row in rows)
    for name in archive.namelist():
        if name.endswith('.png'):
            with Image.open(io.BytesIO(archive.read(name))) as picture:
                assert all(abs(v-300) < 1 for v in picture.info['dpi'])
                picture.verify()
        elif name.endswith('.pdf'):
            assert archive.read(name).startswith(b'%PDF')
        elif name.endswith('.svg'):
            ET.fromstring(archive.read(name))
    report['download'] = {'files': len(archive.namelist()), 'comparison_rows': len(rows), 'png_dpi': 300}
configuration = load_config(directory/'downloaded-config-absolute.yaml')
assert all(Path(p).is_absolute() and Path(p).is_file() for p in configuration.datasets)
assert all(Path(m['path']).is_absolute() and Path(m['path']).is_file() for m in configuration.mechanisms)
report['portable_config'] = True
tests = ET.parse(directory/'tests-all.xml').getroot()
report['tests_passed'] = sum(int(s.get('tests', 0)) for s in tests.findall('testsuite'))
assert report['tests_passed'] == 94
report['methylamine'] = {'status': 'strict_conversion_rejected', 'predictions_validated': False}
(directory/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(report, ensure_ascii=False))
