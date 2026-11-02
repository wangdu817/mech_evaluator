from pathlib import Path
import pytest
from pyteck.respecth.runner import load_config, prepare_run
from pyteck.respecth.solvers import simulate_case
from pyteck.respecth.analysis import compute_sensitivity, _solve_observable
import math


def test_native_flame_adjoint_against_independent_difference(tmp_path):
    root=Path(__file__).resolve().parents[1]
    config=load_config(root/'examples/respecth/demo.yaml')
    _,cases,_=prepare_run(config)
    case=next(c for c in cases if c.kind=='flame' and c.condition.scan_value==1 and c.mechanism.id=='h2o2')
    result=simulate_case(case,tmp_path/'flame')
    assert result.status=='success',result.reason
    target=case.targets[0]['key'];index=10
    output=compute_sensitivity(case,result,target,[index],tmp_path,isolated=False)
    assert output['method']=='Cantera flame-speed adjoint'
    assert output['planned_perturbed_solves']==0
    assert output['rows'][0]['status']=='success'
    step=1e-3
    values=[_solve_observable(case,target,tmp_path,index,math.exp(h)) for h in (step,-step)]
    reference=(values[0]-values[1])/(2*step*output['baseline'])
    assert output['rows'][0]['coefficient']==pytest.approx(reference,rel=.03,abs=1e-4)
