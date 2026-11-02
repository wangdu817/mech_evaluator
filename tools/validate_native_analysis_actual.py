"""Real CH3NH2 mechanisms, independent derivative checks, no batch mutation."""
from pathlib import Path
from dataclasses import asdict
import json
import math
import numpy as np
from pyteck.respecth.runner import project_root
from pyteck.respecth.models import case_from_dict, result_from_dict, file_hash
from pyteck.respecth.analysis import (analysis_identity, compute_rop, _solve_observable)
from pyteck.respecth.analysis_job import run_job
from pyteck.respecth.atomic_io import atomic_json


def main():
    root=project_root(); evidence=[]
    previous=json.loads((root/'results/case-analysis-actual-validation.json').read_text(encoding='utf-8'))
    for record in previous:
        payload=json.loads((Path(record['directory'])/'job.json').read_text(encoding='utf-8'))
        case=case_from_dict(payload['case']); result=result_from_dict(payload['result'])
        before=file_hash(result.history_path)
        settings={**payload['settings'], 'rop':False}
        # More than one parameter is integrated together, unlike the old workflow.
        original=settings['reaction_indices'][0]
        settings['reaction_indices']=list(dict.fromkeys([original, 0, 1]))
        directory=root/'results/analysis'/analysis_identity(case,result,settings)
        directory.mkdir(parents=True,exist_ok=True)
        atomic_json(directory/'job.json',{**payload,'settings':settings})
        report=run_job(directory/'job.json')
        assert report['status']=='completed',report.get('reason')
        assert not report['rop']
        assert all(r['status']=='success' for r in report['sensitivity']['rows']),report['sensitivity']['rows']
        finite_check=None
        if case.kind in {'pfr','jsr'}:
            # Verification only: two independent perturbations for one parameter.
            # This reference check is not part of the production sensitivity method.
            step=1e-4
            values=[_solve_observable(case,settings['target_key'],directory,original,math.exp(h)) for h in [step,-step]]
            reference=(values[0]-values[1])/(2*step*report['sensitivity']['baseline'])
            native=report['sensitivity']['rows'][0]['coefficient']
            assert abs(reference-native)<max(abs(reference)*.02,1e-5),(reference,native)
            finite_check={'independent_difference':reference,'native':native,'passed':True}
        rop=None
        if case.kind=='pfr':
            rop=compute_rop(case,result,settings['species'],settings['row'])
            assert rop['aggregation']=='domain_integral'
            assert rop['quadrature']['reaction_balance_absolute_error']<1e-10
            atomic_json(directory/'pfr-domain-rop.json',rop)
        assert file_hash(result.history_path)==before
        evidence.append({'kind':case.kind,'mechanism':case.mechanism.id,'case_id':case.id,
            'directory':str(directory),'sensitivity_method':report['sensitivity']['method'],
            'sensitivity_only':True,'reaction_count':len(settings['reaction_indices']),
            'independent_reference':finite_check,'pfr_quadrature':rop['quadrature'] if rop else None,
            'history_unchanged':True})
        atomic_json(root/'results/native-analysis-actual-validation.json',evidence)
        print(json.dumps(evidence[-1],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
