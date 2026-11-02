import json
from unittest.mock import patch
import pytest
from pyteck.respecth import result_cleanup, runner


def test_cleanup_removes_outputs_and_related_snapshots_preserves_inputs(tmp_path):
    output = tmp_path/'results/batch'
    for name in ('cache', 'prepared', 'inputs', 'figures', 'saved-batches', 'rerun-backups'):
        (output/name).mkdir(parents=True)
        (output/name/'test').write_text('data')
    (output/'config.yaml').write_text('config')
    (output/'manifest.json').write_text('{}')
    other = tmp_path/'results/other'
    other.mkdir()
    (other/'manifest.json').write_text('{}')
    snapshot = tmp_path/'results/live-snapshots/token/view'
    snapshot.mkdir(parents=True)
    (snapshot/'manifest.json').write_text(json.dumps({'snapshot': {'source': str(output)}}))
    with patch.object(result_cleanup, 'project_root', return_value=tmp_path):
        result_cleanup.discard_output_results(output)
    assert not (output/'cache').exists()
    assert not (output/'manifest.json').exists()
    assert not snapshot.exists()
    assert (output/'prepared/test').read_text() == 'data'
    assert (output/'inputs/test').read_text() == 'data'
    assert (output/'config.yaml').read_text() == 'config'
    assert (other/'manifest.json').exists()


def test_cleanup_requires_explicit_full_rerun():
    with pytest.raises(ValueError, match='explicit full rerun'):
        runner.run_project({}, discard_previous=True)


def test_bad_new_inputs_leave_previous_results(tmp_path):
    output = tmp_path/'batch'
    output.mkdir()
    previous = output/'manifest.json'
    previous.write_text('{"status":"completed"}')
    with patch.object(runner, 'prepare_run', side_effect=ValueError('bad mechanism')):
        with pytest.raises(ValueError, match='bad mechanism'):
            runner._run(None, output, None, None, force_rerun=True, discard_previous=True)
    assert previous.read_text() == '{"status":"completed"}'
