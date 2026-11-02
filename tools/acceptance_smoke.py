"""Executable end-to-end checks; outputs stay inside this project."""
from pathlib import Path
from dataclasses import replace
import json
import threading
import tarfile
import zipfile
import csv
import h5py

from pyteck.respecth.runner import load_config, run_project, load_run
from pyteck.respecth.reporting import render_figures
from pyteck.respecth.evaluation import evaluate_results
from pyteck.respecth.solvers import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def history_times(manifest):
    return {r['case_id']: Path(r['history_path']).stat().st_mtime_ns
            for r in manifest['results'] if r['status'] == 'success'}


def main():
    report = {}
    config = load_config(ROOT/'examples/respecth/demo.yaml')
    first = run_project(config)
    assert len(first['results']) == 26
    assert all(r['status'] == 'success' and r['validation']['passed'] for r in first['results'])
    report['four_solvers_two_mechanisms'] = {'cases': 26, 'verified': 26}
    before = history_times(first)
    config.figure = {'linewidth': 1.8}
    config.scoring = {'type_weights': {'ignition': 2}}
    resumed = run_project(config)
    assert history_times(resumed) == before
    manifest, experiments, cases, results = load_run(config.output)
    render_figures(experiments, {'cases': cases, 'results': results},
                   {'output': str(Path(config.output)/'figures'), 'linewidth': 1.5})
    evaluation = evaluate_results(experiments, results, {}, cases)
    atomic_json(Path(config.output)/'evaluation.json', evaluation)
    assert history_times(resumed) == before
    report['resume_and_offline_postprocessing'] = 'all 26 histories unchanged'
    for item in results:
        with h5py.File(item.history_path) as history:
            assert history['temperature'].size > 1
            assert history['mole_fractions'].shape[1] >= 10
    with (Path(config.output)/'comparison.csv').open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
        assert all(row['property_id'] and row['group_id'] and row['case_id'] for row in rows)
    report['readable_exports'] = {'comparison_rows': len(rows), 'history_files': len(results)}
    cancel_config = replace(config, datasets=[config.datasets[0]],
        output=str(ROOT/'results/cancel-resume'), grid={'enabled': True, 'points': 12},
        figure={'formats': ['png']}, workers=1)
    stop = threading.Event()
    interrupted = run_project(cancel_config, lambda n, *_: stop.set() if n >= 1 else None, stop)
    assert interrupted['status'] == 'cancelled'
    assert any(r['status'] == 'cancelled' for r in interrupted['results'])
    retained = history_times(interrupted)
    recovered = run_project(cancel_config)
    assert all(r['status'] == 'success' for r in recovered['results'])
    assert all(history_times(recovered)[key] == value for key, value in retained.items())
    report['cancel_resume'] = {'retained': len(retained), 'recovered': len(recovered['results'])}
    bad = recovered['results'][0].copy()
    bad.update(status='solver_failed', reason='Injected failure for retry acceptance')
    cache = Path(cancel_config.output)/'cache'/f"{bad['case_id']}.json"
    atomic_json(cache, bad)
    partial = run_project(cancel_config)
    assert any(r['status'] == 'solver_failed' for r in partial['results'])
    retried = run_project(replace(cancel_config, retry_failed=True))
    assert all(r['status'] == 'success' for r in retried['results'])
    report['failure_retry'] = 'explicit retry replaces failed result'
    report['demo_mechanisms'] = evaluation['formal']['mechanisms']
    atomic_json(ROOT/'results/acceptance-smoke.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
