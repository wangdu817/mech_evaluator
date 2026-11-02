"""Exercise progress on actual saved predictions without running a solver."""
from pathlib import Path
import json
import time
from pyteck.respecth.runner import project_root,load_run
from pyteck.respecth.reporting import render_figures
from pyteck.respecth.atomic_io import atomic_json


def main():
    root=project_root()
    manifest,experiments,cases,results=load_run(root/'results/ui-run')
    result_map={r.case_id:r for r in results}
    successful={c.experiment_id for c in cases if c.id in result_map
        and result_map[c.id].status=='success' and result_map[c.id].validation.get('passed')}
    species=[e for e in experiments if e.id in successful and e.kind in {'pfr','jsr'}][:4]
    macro=[e for e in experiments if e.id in successful and e.kind=='ignition'][:2]
    selected=species+macro
    if not species or len(macro)<2: raise RuntimeError('Insufficient saved successful datasets')
    events=[]
    def progress(done,total,message):
        event={'done':done,'total':total,'message':message}
        events.append(event)
        print(json.dumps(event,ensure_ascii=False),flush=True)
    start=time.monotonic()
    paths=render_figures(experiments,{'cases':cases,'results':results},
        {'output':str(root/'results/figure-progress-validation/figures'),
         'experiments':[e.id for e in selected],'macro_layout':'subplots'},progress=progress)
    assert events[-1]['done']==events[-1]['total']==len(species)+1
    assert all(Path(p).is_file() for p in paths)
    summary={'source_status':manifest['status'],'datasets':[e.path for e in selected],
        'mechanisms':sorted({c.mechanism.id for c in cases}),
        'figures':events[-1]['total'],'files':len(paths),'seconds':time.monotonic()-start,
        'events':events,'new_simulations':0,'paths':paths}
    atomic_json(root/'docs/delivery/figure-progress-verification.json',summary)
    print(json.dumps({'figures':summary['figures'],'files':len(paths),'seconds':summary['seconds']},ensure_ascii=False))


if __name__=='__main__': main()
