"""Verify real-result reuse in a separate output without new solver calls."""
from pathlib import Path
import json
from pyteck.respecth.runner import load_config, prepare_run, run_project
from pyteck.respecth.workload import preview_workload


def main():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root/'results/ui-run/precheck-config.yaml')
    original = Path(config.output)
    before = {p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in (original/'cache').glob('*.json')}
    config.datasets = config.datasets[:1]
    config.mechanisms = config.mechanisms[:1]
    config.grid = {'enabled':False}
    config.output = str(root/'results/workload-validation/cached-resume')
    config.reuse_results = [str(original)]
    _, cases, _ = prepare_run(config)
    plan = preview_workload(cases, config)
    assert plan['totals']['pending']==0, 'Stop: real cache did not cover every selected case'
    events = []
    manifest = run_project(config, progress=lambda *event:events.append(event))
    assert len(manifest['cache_hits'])==len(cases)
    assert not manifest['submitted_cases']
    assert events[0][0]==len(cases), 'Initial progress must include all existing results'
    assert before=={p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in (original/'cache').glob('*.json')}
    report = {'cases':len(cases), 'cache_hits':len(manifest['cache_hits']),
        'new_solver_calls':len(manifest['submitted_cases']), 'initial_progress':events[0],
        'source_cache_unchanged':True, 'output':config.output}
    (root/'docs/delivery/cached-resume-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
