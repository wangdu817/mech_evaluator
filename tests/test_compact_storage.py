from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import json
import h5py
import numpy as np
import pytest
from pyteck.respecth.compact_storage import compact_history,is_compact,retain_plot_result
from pyteck.respecth.models import CaseResult
from pyteck.respecth.recovery import verified_history


def history(path,rows=101):
    with h5py.File(path,'w') as out:
        out.attrs.update(case_id='case',complete=True,validation=json.dumps({'passed':True}),species_names='["A", "B"]')
        out.create_dataset('time',data=np.linspace(0,1,rows))
        out.create_dataset('temperature',data=np.linspace(300,900,rows))
        out.create_dataset('mole_fractions',data=np.tile([.2,.8],(rows,1)))
        out.create_dataset('mass_fractions',data=np.tile([.1,.9],(rows,1)))
        out.create_dataset('pressure',data=np.full(rows,101325.))
    return path


def test_compact_preserves_observables_validation_and_continuation(tmp_path):
    source=history(tmp_path/'case.h5',10001)
    before=source.stat().st_size
    result=CaseResult('case','success',{'A':.2},history_path=str(source),validation={'passed':True})
    retain_plot_result(result)
    assert is_compact(source) and verified_history(vars(result))
    assert result.predictions=={'A':.2} and result.metadata['analysis_requires_reconstruction']
    assert source.stat().st_size<before/5
    with h5py.File(source) as data:
        np.testing.assert_array_equal(data['time'][:],[0,1])
        np.testing.assert_array_equal(data['mole_fractions'][-1],[.2,.8])
    compact_history(source)
    assert verified_history(vars(result))


def test_compact_copy_keeps_original_and_refuses_unknown_layout(tmp_path):
    source=history(tmp_path/'full.h5');before=source.read_bytes()
    destination=tmp_path/'small.h5';compact_history(source,destination)
    assert source.read_bytes()==before and is_compact(destination)
    with h5py.File(source,'a') as data: data.create_group('unexpected')
    before=source.read_bytes()
    with pytest.raises(ValueError): compact_history(source)
    assert source.read_bytes()==before and not list(tmp_path.glob('*.tmp'))


def test_worker_compacts_after_success_without_changing_solver(tmp_path):
    from pyteck.respecth.process_entry import execute_case
    result=CaseResult('case','success',{'A':.2},history_path=str(history(tmp_path/'case.h5')),validation={'passed':True})
    with patch('pyteck.respecth.solvers.simulate_case',return_value=result):
        assert execute_case({},str(tmp_path),'') is result
    assert is_compact(result.history_path)


def test_diagnostic_reconstructs_then_discards_full_trajectory(tmp_path):
    from types import SimpleNamespace
    from pyteck.respecth import analysis_reconstruction as module
    result=CaseResult('case','success',{'A':.2},history_path=str(history(tmp_path/'small.h5')),validation={'passed':True})
    compact_history(result.history_path)
    case=SimpleNamespace(config={})
    paths=[]
    def simulate(c,d,cancel):
        path=history(Path(d)/'rebuilt.h5');paths.append(path)
        return replace(result,history_path=str(path))
    with patch('pyteck.respecth.runner.project_root',return_value=tmp_path),patch.object(module,'simulate_case',side_effect=simulate):
        with module.full_trajectory(case,result) as rebuilt:
            assert not is_compact(rebuilt.history_path)
            assert Path(rebuilt.history_path).exists()
        assert not paths[0].exists()
    assert is_compact(result.history_path)


def test_reconstruction_mismatch_does_not_modify_original(tmp_path):
    from types import SimpleNamespace
    from pyteck.respecth import analysis_reconstruction as module
    result=CaseResult('case','success',{'A':.2},history_path=str(history(tmp_path/'small.h5')),validation={'passed':True})
    compact_history(result.history_path);before=Path(result.history_path).read_bytes()
    with patch('pyteck.respecth.runner.project_root',return_value=tmp_path),patch.object(module,'simulate_case',return_value=replace(result,predictions={'A':.8})):
        with pytest.raises(ValueError,match='disagrees'):
            with module.full_trajectory(SimpleNamespace(config={}),result): pass
    assert Path(result.history_path).read_bytes()==before
    assert not list((tmp_path/'.cache/analysis-trajectories').iterdir())


def test_rop_uses_rebuilt_full_domain_not_two_point_trapezoid(tmp_path):
    from types import SimpleNamespace
    from pyteck.respecth import analysis_reconstruction as module
    result=CaseResult('case','success',{'A':.2},history_path=str(history(tmp_path/'small.h5')),validation={'passed':True})
    compact_history(result.history_path)
    case=SimpleNamespace(id='case',kind='pfr',config={},mechanism=SimpleNamespace(species=['A','B']))
    def simulate(c,d,cancel): return replace(result,history_path=str(history(Path(d)/'full.h5')))
    def compute(c,r,species,row,*args,**kwargs):
        with h5py.File(r.history_path) as stream: assert len(stream['time'])==101
        assert row==100
        return {'aggregation':'domain_integral'}
    with patch('pyteck.respecth.runner.project_root',return_value=tmp_path),patch.object(module,'simulate_case',side_effect=simulate),patch.object(module.analysis,'compute_rop',side_effect=compute):
        assert module.compute_rop(case,result,'A',1)['aggregation']=='domain_integral'
    assert not list((tmp_path/'.cache/analysis-trajectories').iterdir())
