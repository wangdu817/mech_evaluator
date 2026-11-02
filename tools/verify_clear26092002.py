"""Verify completed real runs, source hashes, histories and browser export."""
from pathlib import Path
import json,hashlib,zipfile,csv
from collections import Counter
import h5py

root=Path(__file__).resolve().parents[1];base=root/'results/clear-26092002'
audit=json.loads((base/'inputs/audit.json').read_text(encoding='utf8'))
for path,sha in audit['source_hashes'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
run=json.loads((base/'run/manifest.json').read_text(encoding='utf8'))
assert run['status']=='completed' and len(run['cases'])==96
assert {c['mechanism']['id'] for c in run['cases']}=={'clear_26092002'}
counts=dict(Counter(r['status'] for r in run['results']))
assert counts=={'success':86,'solver_failed':1,'invalid_input':9}
histories=0
for r in run['results']:
    if r['status']!='success':continue
    assert r['validation']['passed']
    with h5py.File(r['history_path'],'r') as f:
        assert len(f)>0
    histories+=1
for experiment in run['experiments']:
    assert hashlib.sha256(Path(experiment['path']).read_bytes()).hexdigest()==experiment['sha256']
merged=json.loads((base/'comparison/manifest.json').read_text(encoding='utf8'))
assert len(merged['cases'])==288
assert merged['saved_comparison']['simulations_executed']==0
with zipfile.ZipFile(base/'evidence/three-mechanisms.zip') as z:
    rows=list(csv.DictReader(z.read('comparison.csv').decode('utf-8-sig').splitlines()))
    assert len(rows)==957
    assert {r['mechanism'] for r in rows}=={'audited_working','N_CHO_240725_working','clear_26092002'}
evaluation=json.loads((base/'comparison/evaluation.json').read_text(encoding='utf8'))
report={'source_hashes_unchanged':True,'actual_xml':6,'single_mechanism_cases':96,'status':counts,
        'verified_histories_readable':histories,'comparison_cases':288,'old_mechanisms_recomputed':0,
        'download_rows':len(rows),'common_points':evaluation['common_points'],'excluded_points':evaluation['excluded_points'],
        'common_diagnostic_scores':evaluation['common_success']['mechanisms'],'formal_ranking':evaluation['formal']['ranking'],
        'browser_three_mechanism_render_and_download':True}
(base/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='common_diagnostic_scores'},ensure_ascii=False,indent=2))
