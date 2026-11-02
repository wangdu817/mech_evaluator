"""Paired real-case timings; never change or reuse production simulation cache."""
from pathlib import Path
from dataclasses import asdict
import argparse
import json
import statistics
import subprocess
import sys
import time

from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.models import case_from_dict, digest
from pyteck.respecth.solvers import simulate_case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--one', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.one:
        case = case_from_dict(json.loads(args.one.read_text(encoding='utf-8')))
        started = time.perf_counter()
        result = simulate_case(case, args.output.parent / 'histories')
        record = asdict(result)
        record['wall_seconds'] = time.perf_counter() - started
        atomic_json(args.output, record)
        return
    root = Path(__file__).resolve().parents[1]
    directory = root / 'results' / ('preconditioner-benchmark-' + time.strftime('%Y%m%d-%H%M%S'))
    directory.mkdir(parents=True)
    source = root / 'results/ui-run/manifest.json'
    manifest = json.loads(source.read_text(encoding='utf-8'))
    selection = []
    for mechanism in sorted({c['mechanism']['id'] for c in manifest['cases']}):
        for kind, temperature in [('pfr', 1100), ('jsr', 1100), ('ignition', 1400)]:
            candidates = [c for c in manifest['cases'] if c['mechanism']['id'] == mechanism
                          and c['kind'] == kind and not c['issues'] and c['role'] == 'scoring']
            if candidates:
                selection.append(min(candidates, key=lambda c: abs(c['condition']['temperature']-temperature)))
    atomic_json(directory/'selected-cases.json', selection)
    rows = []
    for index, original in enumerate(selection):
        trials = {'dense': [], 'adaptive_preconditioned': []}
        for repeat in range(2):
            # Alternate order to reduce warm-filesystem / CPU scheduling bias.
            order = ['dense', 'adaptive_preconditioned'] if repeat == 0 else ['adaptive_preconditioned', 'dense']
            for backend in order:
                case = case_from_dict(original)
                case.config = {**case.config, 'linear_solver': backend}
                case.config.pop('_cancel_file', None)
                case.id = digest({'original': original['id'], 'backend': backend, 'repeat': repeat})
                stem = f'{index}-{repeat}-{backend}'
                input_file = directory / (stem+'.case.json')
                output = directory / (stem+'.result.json')
                atomic_json(input_file, asdict(case))
                try:
                    completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--one',
                        str(input_file), '--output', str(output)], capture_output=True, text=True,
                        encoding='utf-8', errors='replace', timeout=60)
                    (directory/(stem+'.log')).write_text(completed.stdout+completed.stderr, encoding='utf-8')
                    result = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {
                        'status': 'process_failed', 'reason': f'exit {completed.returncode}'}
                except subprocess.TimeoutExpired:
                    result = {'status': 'timeout', 'reason': '60 s subprocess deadline'}
                trials[backend].append(result)
                print(index, original['mechanism']['id'], original['kind'], backend,
                      result['status'], result.get('wall_seconds'), flush=True)
        passed = all(r['status'] == 'success' and r['validation'].get('passed') is True
                     for runs in trials.values() for r in runs)
        row = {'case_id': original['id'], 'mechanism': original['mechanism']['id'],
               'kind': original['kind'], 'temperature': original['condition']['temperature'],
               'experiment_id': original['experiment_id'], 'config': original['config'],
               'both_verified': passed, 'trials': trials}
        if passed:
            dense = statistics.median(r['wall_seconds'] for r in trials['dense'])
            adaptive = statistics.median(r['wall_seconds'] for r in trials['adaptive_preconditioned'])
            discrepancies = []
            for base, preconditioned in zip(trials['dense'], trials['adaptive_preconditioned']):
                for key, value in base['predictions'].items():
                    other = preconditioned['predictions'][key]
                    floor = original['config'].get('validation_absolute', 1e-10)
                    discrepancies.append(abs(value-other)/max(abs(value), floor))
            row.update(dense_seconds=dense, adaptive_seconds=adaptive,
                       speedup=dense/adaptive, max_scaled_prediction_difference=max(discrepancies, default=0))
        rows.append(row)
        atomic_json(directory/'comparison.json', {'source': str(source), 'repeats': 2,
            'includes': 'mechanism load, integration, configured verification and HDF5 export; excludes child Python startup',
            'production_batch_running': True, 'rows': rows})
    print('REPORT', directory, flush=True)


if __name__ == '__main__':
    main()
