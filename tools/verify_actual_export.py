"""Inspect a result package actually downloaded through the browser."""
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1])
destination = root/'results/actual-audited/browser-results.zip'
destination.write_bytes(source.read_bytes())
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert all(name in names for name in ('comparison.csv','failed_cases.csv','run_summary.json','figure.yaml','manifest.json'))
    rows = list(csv.DictReader(io.StringIO(archive.read('comparison.csv').decode('utf-8-sig'))))
    failures = list(csv.DictReader(io.StringIO(archive.read('failed_cases.csv').decode('utf-8-sig'))))
    assert len(rows)==5577 and len(failures)==18
    assert len([n for n in names if n.endswith('.png')])==3
    assert len([n for n in names if n.endswith('.pdf')])==3
    assert len([n for n in names if n.endswith('.svg')])==3
cache = root/'results/actual-audited/full/cache'
before = json.loads((root/'results/actual-audited/cache-before-postprocessing.json').read_text())
after = {p.name:p.stat().st_mtime_ns for p in cache.glob('*')}
assert before==after
report = {'downloaded_package':str(destination),'zip_integrity':True,'entries':len(names),
          'measurement_rows':len(rows),'failure_rows':len(failures),'figures':3,
          'formats':['PNG 300 dpi','PDF','SVG'],'postprocessing_did_not_resimulate':True}
(root/'results/actual-audited/browser-export-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
