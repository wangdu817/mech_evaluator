"""Real single-mechanism subset: cross-directory reuse, then local resume."""
from pathlib import Path
from dataclasses import replace
import json
from pyteck.respecth.runner import load_config,run_project

root=Path(__file__).resolve().parents[1]
source=root/'results/clear-26092002/run'
config=load_config(root/'examples/respecth/clear-26092002.yaml')
output=root/'results/run-selection-cache'
config=replace(config,datasets=[str(root.parent/'exp5/Hjuler_1995_Set13.xml')],
    output=str(output),reuse_results=[str(source)],retry_failed=False)
first=run_project(config)
assert len(first['cases'])==12
assert len(first['cache_hits'])==12 and not first['submitted_cases']
before={p.name:p.stat().st_mtime_ns for p in (output/'cache').glob('*.json')}
second=run_project(config)
assert len(second['cache_hits'])==12 and not second['submitted_cases']
assert all(r['status']=='success' and r['validation']['passed'] for r in second['results'])
assert before=={p.name:p.stat().st_mtime_ns for p in (output/'cache').glob('*.json')}
report={'actual_mechanism':'clear_26092002','XML':'Hjuler_1995_Set13.xml','cases':12,
    'cross_directory_hits':len(first['reused_cases']),'local_resume_hits':len(second['cache_hits']),
    'submitted_simulations_both_runs':0,'local_cache_files_untouched':True}
(output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
