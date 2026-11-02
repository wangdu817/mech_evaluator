import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import patch

import h5py
import pytest

from pyteck.respecth import runner
from pyteck.respecth.recovery import verified_history
from pyteck.respecth.models import RunConfig


def test_history_identity_and_commit_are_required(tmp_path):
    path = tmp_path / 'history.h5'
    result = {'case_id': 'a', 'status': 'success', 'validation': {'passed': True},
              'history_path': str(path)}
    assert not verified_history(result)
    with h5py.File(path, 'w') as history:
        history.attrs.update(case_id='a', complete=True, validation='{"passed": true}')
        history['temperature'] = [1000.0]
        history['mole_fractions'] = [[0.1, 0.9]]
    assert verified_history(result)
    with h5py.File(path, 'r+') as history:
        history.attrs['complete'] = False
    assert not verified_history(result)
    with h5py.File(path, 'r+') as history:
        history.attrs.update(complete=True, case_id='other')
    assert not verified_history(result)


def minimal_run(path):
    manifest = {'status': 'running', 'config': {}, 'created_utc': '2026-10-10',
                'workers': 1, 'experiments': [], 'cases': [], 'results': []}
    (path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


def test_load_recovers_dead_owner_without_solver(tmp_path):
    minimal_run(tmp_path)
    (tmp_path / 'run.lock').write_text('{"pid": 99999999, "thread": 0}')
    with patch.object(runner, 'project_root', return_value=tmp_path.parent), \
         patch.object(runner.psutil, 'pid_exists', return_value=False), \
         patch.object(runner, 'simulate_case', side_effect=AssertionError('must not solve')):
        manifest, _, _, _ = runner.load_run(tmp_path)
    assert manifest['status'] == 'cancelled'
    assert not (tmp_path / 'run.lock').exists()
    assert (tmp_path / 'progress.json').exists()
    assert list((tmp_path / 'recovery-backups').glob('*/manifest.json'))


def test_load_refuses_live_owner(tmp_path):
    minimal_run(tmp_path)
    lock = tmp_path / 'run.lock'
    lock.write_text(json.dumps({'pid': os.getpid(), 'thread': threading.get_ident()}))
    with patch.object(runner, 'project_root', return_value=tmp_path.parent):
        with pytest.raises(ValueError, match='still active'):
            runner.load_run(tmp_path)
    assert lock.exists()
    assert json.loads((tmp_path / 'manifest.json').read_text())['status'] == 'running'


def test_precheck_does_not_overwrite_saved_input(tmp_path):
    frozen = tmp_path / 'inputs'
    frozen.mkdir()
    snapshot = frozen / 'saved.xml'
    snapshot.write_bytes(b'original saved input')
    source = tmp_path / 'changed-source.xml'
    source.write_bytes(b'new input bytes')
    experiment = SimpleNamespace(id='saved', path=str(source))
    config = RunConfig(datasets=[str(source)], mechanisms=[], output=str(tmp_path))
    with patch.object(runner, 'project_root', return_value=tmp_path.parent), \
         patch.object(runner, 'load_experiment', return_value=experiment), \
         patch.object(runner, 'build_cases', return_value=([], [])):
        assert runner.prepare_run(config) == ([experiment], [], [])
    assert snapshot.read_bytes() == b'original saved input'
