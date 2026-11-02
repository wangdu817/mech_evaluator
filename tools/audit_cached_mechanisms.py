"""Inspect only HDF5 identity headers; no trajectory arrays loaded."""
from pathlib import Path
from collections import Counter,defaultdict
import json
import h5py
root=Path(__file__).resolve().parents[1]
counts=Counter();experiments=defaultdict(set);errors=[]
for path in (root/'results/ui-run/cache').glob('*.h5'):
    try:
        with h5py.File(path,'r') as history:
            case=json.loads(history.attrs['case'])
            result_path=path.with_suffix('.json')
            if not result_path.exists(): continue
            result=json.loads(result_path.read_text(encoding='utf-8'))
            if result['case_id']!=case['id'] or result['status']!='success' or not result['validation'].get('passed'): continue
            name=case['mechanism']['id'];counts[name]+=1;experiments[name].add(case['experiment_id'])
    except Exception as error:errors.append({'path':str(path),'reason':str(error)})
report={'verified_cache_counts':dict(counts),'xml_counts':{k:len(v) for k,v in experiments.items()},'errors':errors}
(root/'results/cached-mechanism-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
