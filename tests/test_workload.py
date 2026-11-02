from dataclasses import asdict
from types import SimpleNamespace
import json
import h5py
import pytest
from pyteck.respecth.models import CaseResult
from pyteck.respecth.workload import preview_workload, cached_result


def case(name, mechanism='old', issues=None):
    return SimpleNamespace(id=name, mechanism=SimpleNamespace(id=mechanism),
                           role='scoring', issues=issues or [], targets=[{'key':'X'}])


def save(tmp_path, identity, status='success', prediction=1.):
    history = tmp_path/f'{identity}.h5'
    with h5py.File(history, 'w') as file:
        file.attrs['case_id'] = identity
        file.attrs['validation'] = json.dumps({'passed':True})
        file.create_dataset('temperature', data=[300.])
        file.create_dataset('mole_fractions', data=[[1.]])
    result = CaseResult(identity, status, {'X':prediction}, history_path=str(history), validation={'passed':True})
    (tmp_path/'cache').mkdir(exist_ok=True)
    (tmp_path/'cache'/f'{identity}.json').write_text(json.dumps(asdict(result)))
    return result


def test_existing_new_failed_blocked_accounting(tmp_path):
    save(tmp_path, 'good')
    save(tmp_path, 'failed', 'solver_failed')
    cases = [case('good'), case('failed'), case('new', 'new'), case('invalid', 'new', ['missing T'])]
    config = SimpleNamespace(output=str(tmp_path), reuse_results=[], retry_failed=False)
    plan = preview_workload(cases, config)
    assert plan['totals']['total'] == 4
    assert plan['totals']['processed'] == 2
    assert plan['totals']['pending'] == 2
    assert plan['totals']['new_solves'] == 1
    assert plan['totals']['blocked'] == 1
    assert plan['mechanisms'][1]['processed'] == 0
    config.retry_failed = True
    assert preview_workload(cases, config)['totals']['new_solves'] == 2
    forced = preview_workload(cases, config, force=True)['totals']
    assert forced['processed'] == 0 and forced['pending'] == 4 and forced['new_solves'] == 3


def test_missing_invalid_histories_and_predictions_not_reused(tmp_path):
    save(tmp_path, 'good')
    (tmp_path/'good.h5').unlink()
    assert cached_result(case('good'), tmp_path) is None
    save(tmp_path, 'nan', prediction=float('nan'))
    assert cached_result(case('nan'), tmp_path) is None
    save(tmp_path, 'cancelled', status='cancelled')
    config = SimpleNamespace(output=str(tmp_path), reuse_results=[], retry_failed=False)
    assert preview_workload([case('cancelled')], config)['totals']['processed'] == 0


def test_external_success_overrides_local_failure(tmp_path):
    save(tmp_path, 'good', status='solver_failed')
    prior = save(tmp_path, 'prior')
    prior.case_id = 'good'
    result = cached_result(case('good'), tmp_path, {'good':(prior,'external')})
    assert result.status == 'success' and result.metadata['reused_from'] == 'external'


def test_mechanism_grid_override_preserves_other_case_ids():
    from pathlib import Path
    from pyteck.respecth.runner import load_config, prepare_run
    root = Path(__file__).resolve().parents[1]
    config = load_config(root/'examples/respecth/demo.yaml')
    config.grid = {'enabled':True, 'mode':'count', 'points':8}
    config.mechanisms = [dict(config.mechanisms[0], id='old'), dict(config.mechanisms[0], id='new')]
    _, before, _ = prepare_run(config)
    config.mechanisms[1]['grid'] = {'enabled':True, 'mode':'count', 'points':12}
    _, after, _ = prepare_run(config)
    assert {c.id for c in before if c.mechanism.id=='old'} == {c.id for c in after if c.mechanism.id=='old'}
    assert len([c for c in after if c.mechanism.id=='new']) > len([c for c in before if c.mechanism.id=='new'])
