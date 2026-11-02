from dataclasses import asdict
from pathlib import Path
import pytest
from pyteck.respecth.runner import load_run
from pyteck.respecth.models import case_from_dict,digest
from pyteck.respecth.solvers import simulate_case

@pytest.mark.parametrize("kind",["pfr","jsr","ignition"])
def test_preconditioned_matches_actual_dense(kind,tmp_path):
 root=Path(__file__).resolve().parents[1]
 if not (root/'results/actual-audited/full/manifest.json').exists(): pytest.skip("Actual run not distributed")
 _,_,cases,results=load_run(root/'results/actual-audited/full')
 case,reference=next((c,r) for c,r in zip(cases,results) if c.kind==kind and r.status=='success' and (kind!='jsr' or c.condition.temperature>=1100))
 revised=case_from_dict(asdict(case));revised.config['linear_solver']='adaptive_preconditioned';revised.id=digest(asdict(revised))
 result=simulate_case(revised,tmp_path)
 assert result.status=='success',result.reason
 assert result.metadata['solver']['linear_solver']=='adaptive_preconditioned'
 assert result.metadata['solver']['solver_stats']['lin_iters']>0
 for key,value in reference.predictions.items():
  assert abs(value-result.predictions[key])<=max(1e-10,.01*abs(value))
