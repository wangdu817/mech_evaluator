"""Compare full-history streaming predictions with two actual saved mechanisms."""
from pathlib import Path
from dataclasses import asdict
import json
import psutil
import h5py
from pyteck.respecth.runner import load_run
from pyteck.respecth.solvers import simulate_case
from pyteck.respecth.models import case_from_dict

root=Path(__file__).resolve().parents[1]
directory=root/'results/memory-fix/reference'
reports=[]
for folder in ('actual-audited/full','clear-26092002/run'):
    _,_,cases,results=load_run(root/'results'/folder)
    for kind in ('pfr','jsr','ignition'):
        case,reference=next((c,r) for c,r in zip(cases,results) if c.kind==kind and r.status=='success' and (kind!='jsr' or c.condition.temperature>=1100))
        revised=case_from_dict(asdict(case))
        before=psutil.Process().memory_info().rss
        calculated=simulate_case(revised,directory)
        assert calculated.status=='success',calculated.reason
        errors={k:abs(v-calculated.predictions[k]) for k,v in reference.predictions.items()}
        assert all(error<=max(1e-12,abs(reference.predictions[k])*1e-9) for k,error in errors.items()),errors
        with h5py.File(calculated.history_path) as f:
            assert f.attrs['complete']
            nodes=len(f['temperature'])
        reports.append({'mechanism':case.mechanism.id,'kind':kind,'case_id':case.id,
                        'max_absolute_error':max(errors.values()),'history_rows':nodes,
                        'RSS_change_MiB':round((psutil.Process().memory_info().rss-before)/2**20,2),
                        'verification_passed':calculated.validation['passed']})
        print(json.dumps(reports[-1],ensure_ascii=False),flush=True)
(root/'results/memory-fix/reference-validation.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
