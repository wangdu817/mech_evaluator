"""Run actual-methylamine full-domain ROP including integration refinement."""
from pathlib import Path
import json
from pyteck.respecth.runner import project_root
from pyteck.respecth.models import case_from_dict, result_from_dict, file_hash
from pyteck.respecth.analysis import analysis_identity
from pyteck.respecth.analysis_job import run_job
from pyteck.respecth.atomic_io import atomic_json


if __name__=='__main__':
    root=project_root()
    records=json.loads((root/'results/case-analysis-actual-validation.json').read_text(encoding='utf-8'))
    record=next(r for r in records if r['kind']=='pfr')
    payload=json.loads((Path(record['directory'])/'job.json').read_text(encoding='utf-8'))
    case=case_from_dict(payload['case']);result=result_from_dict(payload['result'])
    before=file_hash(result.history_path)
    settings={**payload['settings'],'rop':True,'sensitivity':False}
    directory=root/'results/analysis'/analysis_identity(case,result,settings)
    directory.mkdir(parents=True,exist_ok=True)
    atomic_json(directory/'job.json',{**payload,'settings':settings})
    report=run_job(directory/'job.json')
    assert report['status']=='completed',report.get('reason')
    assert report['rop']['aggregation']=='domain_integral'
    assert report['rop']['quadrature']['passed'],report['rop']['quadrature']
    assert file_hash(result.history_path)==before
    evidence={'case_id':case.id,'mechanism':case.mechanism.id,'directory':str(directory),
        'original_history_unchanged':True,'quadrature':report['rop']['quadrature']}
    atomic_json(root/'results/pfr-integral-actual-validation.json',evidence)
    print(json.dumps(evidence,ensure_ascii=False))
