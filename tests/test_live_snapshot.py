import json
import shutil
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
import pytest
from pyteck.respecth import live_snapshot, runner
from pyteck.respecth import result_access


@pytest.fixture
def active_batch(tmp_path):
    from pyteck.respecth.solvers import simulate_case
    config = runner.load_config(runner.project_root()/'examples/respecth/demo.yaml')
    source = tmp_path/'active'
    source.mkdir()
    config.output = str(source)
    config.datasets = config.datasets[:1]
    config.mechanisms = config.mechanisms[:1]
    experiments, cases, _ = runner.prepare_run(config)
    cases = cases[:2]
    (source/'inputs').mkdir()
    for experiment in experiments:
        shutil.copy2(experiment.path, source/'inputs'/f'{experiment.id}.xml')
    results = [asdict(simulate_case(case, source)) for case in cases]
    if all(r['status']=='cancelled' and r.get('reason','').startswith('Memory guard:') for r in results):
        pytest.skip(results[0]['reason'])
    assert all(r['status'] == 'success' for r in results), [(r['status'],r.get('reason')) for r in results]
    (source/'cache').mkdir(exist_ok=True)
    manifest = {'status': 'running', 'created_utc': '2026-10-10', 'workers': 1,
                'config': config.to_dict(), 'experiments': [asdict(e) for e in experiments],
                'cases': [asdict(c) for c in cases], 'results': []}
    (source/'manifest.json').write_text(json.dumps(manifest))
    (source/'run.lock').write_text('{"pid": 1, "thread": 1}')
    (source/'cache'/f"{results[0]['case_id']}.json").write_text(json.dumps(results[0]))
    return source, results


def test_active_snapshot_and_refresh_preserve_owner_and_old_view(active_batch, tmp_path):
    source, results = active_batch
    original = (source/'manifest.json').read_bytes()
    lock = (source/'run.lock').read_bytes()
    with patch.object(live_snapshot, 'project_root', return_value=tmp_path), \
         patch.object(runner, 'project_root', return_value=tmp_path):
        first = live_snapshot.create_completed_snapshot(source)
        manifest, _, _, loaded = runner.load_run(first)
        assert manifest['snapshot']['pending_cases'] == 1
        assert loaded[0].status == 'success'
        assert loaded[1].metadata['snapshot_pending']
        assert loaded[0].history_path != results[0]['history_path']
        retained = Path(loaded[0].history_path)
        modified = retained.stat().st_mtime_ns
        (source/'cache'/f"{results[1]['case_id']}.json").write_text(json.dumps(results[1]))
        second = live_snapshot.create_completed_snapshot(source)
        assert all(r.status == 'success' for r in runner.load_run(second)[3])
        assert second == first  # One refreshed view per batch, not growing snapshots.
        assert retained.stat().st_mtime_ns == modified
    assert (source/'manifest.json').read_bytes() == original
    assert (source/'run.lock').read_bytes() == lock


def test_incomplete_history_cannot_be_used_as_success(active_batch, tmp_path):
    source, results = active_batch
    result = {**results[0], 'history_path': str(tmp_path/'missing.h5')}
    (source/'cache'/f"{result['case_id']}.json").write_text(json.dumps(result))
    with patch.object(live_snapshot, 'project_root', return_value=tmp_path), \
         patch.object(runner, 'project_root', return_value=tmp_path):
        snapshot = live_snapshot.create_completed_snapshot(source)
        assert runner.load_run(snapshot)[3][0].status == 'unverified'


@pytest.mark.parametrize('progress_file', [True, False])
def test_normal_load_automatically_reads_active_batch(active_batch, tmp_path, progress_file):
    import os
    import threading
    from pyteck.respecth.evaluation import evaluate_results
    from pyteck.respecth.reporting import render_figures
    source, _ = active_batch
    (source/'run.lock').write_text(json.dumps({'pid': os.getpid(), 'thread': threading.get_ident()}))
    if progress_file:
        (source/'progress.json').write_text('{"status":"running"}')
    original = (source/'manifest.json').read_bytes()
    owner = (source/'run.lock').read_bytes()
    with patch.object(live_snapshot, 'project_root', return_value=tmp_path), \
         patch.object(runner, 'project_root', return_value=tmp_path), \
         patch.object(result_access, 'project_root', return_value=tmp_path):
        directory, (manifest, experiments, cases, results) = result_access.load_result_view(source)
        assert directory != source
        assert manifest['status'] == 'snapshot'
        assert results[0].status == 'success'
        evaluation = evaluate_results(experiments, results, {}, cases)
        assert not evaluation['formal']['ranking']
        assert render_figures(experiments, {'cases': cases, 'results': results}, {'output': str(directory/'figures')})
    assert (source/'manifest.json').read_bytes() == original
    assert (source/'run.lock').read_bytes() == owner


def load_after_widget(source):
    import streamlit as st
    from pyteck.respecth.ui_loading import load_results_into_session
    st.text_input('结果目录', value=source, key='saved_result_output')
    if st.button('载入'):
        load_results_into_session(source)


def test_snapshot_load_after_directory_widget(active_batch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from pyteck.respecth import result_library
    source, _ = active_batch
    (source/'progress.json').write_text('{"status":"running"}')
    with patch.object(live_snapshot, 'project_root', return_value=tmp_path), \
         patch.object(runner, 'project_root', return_value=tmp_path), \
         patch.object(result_access, 'project_root', return_value=tmp_path), \
         patch.object(result_library, 'project_root', return_value=tmp_path):
        at = AppTest.from_function(load_after_widget, args=(str(source),), default_timeout=30).run()
        at.button[0].click().run()
        assert not at.exception
        assert at.session_state['loaded_run'][0]['status'] == 'snapshot'
        assert at.session_state['saved_result_output'] == str(source)
        assert '部分结果评分' in at.session_state['result_load_notice']


def test_same_loader_reads_full_batch_after_completion(active_batch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from pyteck.respecth import result_library
    source, results = active_batch
    manifest = json.loads((source/'manifest.json').read_text())
    manifest.update(status='completed', results=results)
    (source/'manifest.json').write_text(json.dumps(manifest))
    (source/'progress.json').write_text('{"status":"completed"}')
    (source/'run.lock').unlink()
    with patch.object(runner, 'project_root', return_value=tmp_path), \
         patch.object(result_access, 'project_root', return_value=tmp_path), \
         patch.object(result_library, 'project_root', return_value=tmp_path):
        at = AppTest.from_function(load_after_widget, args=(str(source),), default_timeout=30).run()
        at.button[0].click().run()
        assert not at.exception
        assert at.session_state['loaded_output'] == str(source)
        assert at.session_state['loaded_run'][0]['status'] == 'completed'
        assert len(at.session_state['loaded_run'][3]) == 2
        assert '载入成功' in at.session_state['result_load_notice']
        assert '原任务继续运行' not in at.session_state['result_load_notice']
