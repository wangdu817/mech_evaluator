"""Actual-mechanism ignition-temperature sensitivity and macro plot smoke."""
from pathlib import Path
from dataclasses import asdict
import json
import numpy as np
from pyteck.respecth.runner import project_root,load_run
from pyteck.respecth.analysis import history_coordinates
from pyteck.respecth.analysis_job import run_job
from pyteck.respecth.reporting import render_figures
from pyteck.respecth.atomic_io import atomic_json


def main():
    root=project_root();source=root/'results/ui-run'
    manifest,experiments,cases,results=load_run(source)
    result_map={r.case_id:r for r in results}
    candidates=[c for c in cases if c.kind=='ignition' and c.role=='scoring'
        and c.mechanism.id=='Mech25_47_v1_NH3_CH4_260324_MECH'
        and result_map[c.id].status=='success' and 1100<=c.condition.temperature<=1400]
    case=min(candidates,key=lambda c:abs(c.condition.temperature-1300))
    result=result_map[case.id];delay=float(next(iter(result.predictions.values())))
    times=history_coordinates(case,result)[1]
    directory=root/'results/analysis/temperature-entry-validation'
    directory.mkdir(parents=True,exist_ok=True)
    settings={'rop':False,'sensitivity':True,'species':None,'target_key':'temperature_at_fixed_time',
              'reference_time':delay,'reaction_indices':[0,1],'row':int(np.argmin(abs(times-delay))),
              'top_n':15,'zero_floor':1e-20}
    payload={'case':asdict(case),'result':asdict(result),'settings':settings,'source_run':str(source)}
    from pyteck.respecth.analysis_cache import reusable_directory
    cached=reusable_directory(payload,component='sensitivity')
    if cached:
        directory=cached
        report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    else:
        atomic_json(directory/'job.json',payload)
        report=run_job(directory/'job.json')
    if report['status']!='completed': raise RuntimeError(report.get('reason',report['status']))
    selected=[e for e in experiments if e.kind=='ignition'][:2]
    paths=render_figures(experiments,{'cases':cases,'results':results},
        {'output':str(root/'results/postprocessing-validation/figures'),'macro_layout':'subplots','columns':2,'experiments':[e.id for e in selected]})
    summary={'case_id':case.id,'mechanism':case.mechanism.id,'temperature_K':case.condition.temperature,
        'analysis_time_s':delay,'status':report['status'],'baseline_K':report['sensitivity']['baseline'],
        'method':report['sensitivity']['method'],'reaction_count':2,'macro_figures':paths,
        'report':str(directory/'report.json')}
    atomic_json(root/'docs/delivery/postprocessing-extension-verification.json',summary)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__': main()
