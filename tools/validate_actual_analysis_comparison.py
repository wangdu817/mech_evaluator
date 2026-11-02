from pathlib import Path
import json
from pyteck.respecth.models import case_from_dict,result_from_dict,digest
from pyteck.respecth.analysis import analysis_identity
from pyteck.respecth.analysis_batch_job import run_batch
from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.runner import project_root
jobs=[]
for path in list(Path('results/analysis').glob('*/report.json')):
    report=json.loads(path.read_text(encoding='utf-8'))
    if report.get('status')!='completed' or not report.get('sensitivity'):continue
    payload=json.loads((path.parent/'job.json').read_text(encoding='utf-8'))
    case=case_from_dict(payload['case']);result=result_from_dict(payload['result'])
    settings={'rop':True,'species':'CH3NH2','row':payload['settings']['row'],'top_n':15,'sensitivity':False,'zero_floor':1e-20}
    directory=project_root()/'results/analysis'/analysis_identity(case,result,settings)
    directory.mkdir(parents=True,exist_ok=True)
    atomic_json(directory/'job.json',{**payload,'settings':settings})
    jobs.append({'job':str(directory/'job.json'),'label':f'{case.mechanism.id} / {case.condition.temperature:g} K / CH3NH2 ROP'})
directory=project_root()/'results/analysis-batches'/digest(jobs)
directory.mkdir(parents=True,exist_ok=True);atomic_json(directory/'jobs.json',{'jobs':jobs})
print(run_batch(directory/'jobs.json'))
