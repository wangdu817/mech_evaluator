"""Actual CH3NH2 mechanisms/XML, preserving source predictions and histories."""
from pathlib import Path
from dataclasses import asdict
import json
import numpy as np
from pyteck.respecth.runner import load_run,project_root
from pyteck.respecth.analysis import analysis_identity,history_coordinates
from pyteck.respecth.analysis_job import run_job
from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.models import file_hash

def main():
    root=project_root(); evidence=[]
    selections=[('actual-audited/full','pfr','NO',True),
                ('actual-audited/full','jsr','NO',True),
                ('ui-run','ignition','OH',True)]
    for folder,kind,species,sensitivity in selections:
        manifest,experiments,cases,results=load_run(root/'results'/folder)
        result_map={r.case_id:r for r in results}
        candidates=[c for c in cases if c.kind==kind and c.role=='scoring'
            and result_map[c.id].status=='success' and (kind=='ignition' or c.condition.temperature>=1100)
            and (species in c.mechanism.species or species in c.mechanism.species_map)]
        case=min(candidates,key=lambda c:abs(c.condition.temperature-(1400 if kind=='ignition' else 1100)))
        result=result_map[case.id]
        paths=[Path(result.history_path),root/'results'/folder/'cache'/f'{case.id}.json']
        original={str(p):file_hash(p) for p in paths if p.exists()}
        _,coordinate=history_coordinates(case,result)
        row=int(np.argmin(abs(coordinate-next(iter(result.predictions.values()))))) if kind=='ignition' else len(coordinate)-1
        settings={'species':species,'row':row,'top_n':10,'sensitivity':False}
        directory=root/'results/analysis'/analysis_identity(case,result,settings)
        directory.mkdir(parents=True,exist_ok=True)
        atomic_json(directory/'job.json',{'case':asdict(case),'result':asdict(result),'settings':settings,'source_run':str(root/'results'/folder)})
        report=run_job(directory/'job.json')
        assert report['status']=='completed',report.get('reason')
        if sensitivity:
            target=next((t for t in case.targets if t.get('species')==species),case.targets[0])
            settings={**settings,'sensitivity':True,'target_key':target['key'],
                'reaction_indices':[r['reaction_index'] for r in report['rop']['rows'][:1]],'delta':.01,'zero_floor':1e-20}
            if kind=='ignition':
                settings.update(target_key='temperature_at_fixed_time',reference_time=next(iter(result.predictions.values())))
            directory=root/'results/analysis'/analysis_identity(case,result,settings)
            directory.mkdir(parents=True,exist_ok=True)
            atomic_json(directory/'job.json',{'case':asdict(case),'result':asdict(result),'settings':settings,'source_run':str(root/'results'/folder)})
            report=run_job(directory/'job.json')
            assert report['status']=='completed',report.get('reason')
            assert report['sensitivity']['rows'][0]['status']=='success',report['sensitivity']['rows']
        assert all(file_hash(p)==sha for p,sha in original.items())
        evidence.append({'mechanism':case.mechanism.id,'kind':kind,'case_id':case.id,
            'directory':str(directory),'ROP_species':species,'ROP_balance_absolute_error':report['rop']['balance_absolute_error'],
            'sensitivity':report.get('sensitivity'),'original_case_files_unchanged':True})
        print(json.dumps({k:v for k,v in evidence[-1].items() if k!='sensitivity'},ensure_ascii=False),flush=True)
    atomic_json(root/'results/case-analysis-actual-validation.json',evidence)

if __name__=='__main__': main()
