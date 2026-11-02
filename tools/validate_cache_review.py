"""Validate resume and explicit rerun with actual saved clear-mechanism cases."""
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
import json, shutil
from pyteck.respecth import runner
from pyteck.respecth.models import RunConfig, file_hash
from pyteck.respecth.atomic_io import atomic_json
ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT/'results/memory-review/batch'
    original,experiments,cases,results=runner.load_run(source)
    before={Path(r.history_path):file_hash(r.history_path) for r in results}
    config=RunConfig.from_dict(original['config'])
    output=ROOT/'results/cache-review/resume'
    config.output=str(output);config.reuse_results=[str(source)];config.retry_failed=True
    config.figure={'formats':['png']};config.workers=2
    _,prepared,_=runner.prepare_run(config)
    assert [c.id for c in prepared]==[c.id for c in cases], 'Engine identity changed; no unsafe compatibility override'
    (output/'cache').mkdir(parents=True,exist_ok=True)
    atomic_json(output/'cache'/f'{cases[0].id}.json',{'case_id':cases[0].id,'status':'solver_failed','reason':'earlier local failure','predictions':{},'validation':{},'history_path':'','metadata':{}})
    with patch('pyteck.respecth.process_entry.execute_case',side_effect=AssertionError('Cached cases must not solve')):
        first=runner.run_project(config)
        second=runner.run_project(config)
    assert len(first['cache_hits'])==30 and not first['submitted_cases']
    assert len(second['cache_hits'])==30 and not second['submitted_cases']
    assert all(r['status']=='success' for r in second['results'])
    # An explicit force run must compute exactly the selected one case, preserving its old history.
    forced_output=ROOT/'results/cache-review/force-single'
    forced_output.mkdir(parents=True,exist_ok=True)
    shutil.copy2(output/'manifest.json',forced_output/'manifest.json')
    shutil.copytree(output/'inputs',forced_output/'inputs',dirs_exist_ok=True)
    (forced_output/'cache').mkdir(exist_ok=True)
    case=cases[0];result=results[0]
    shutil.copy2(result.history_path,forced_output/'cache'/f'{case.id}.h5')
    atomic_json(forced_output/'cache'/f'{case.id}.json',asdict(result))
    forced_config=RunConfig.from_dict(original['config']);forced_config.output=str(forced_output)
    forced_config.reuse_results=[str(source)];forced_config.workers=1
    real_prepare=runner.prepare_run
    def one(config):
        exps,all_cases,notes=real_prepare(config)
        return exps,[next(c for c in all_cases if c.id==case.id)],notes
    with patch.object(runner,'prepare_run',side_effect=one):
        forced=runner.run_project(forced_config,force_rerun=True)
    assert len(forced['submitted_cases'])==1 and not forced['cache_hits']
    assert forced['results'][0]['status']=='success'
    backup=forced['execution']['cache_backup']
    loaded_backup=runner.load_run(backup)
    assert len(loaded_backup[2])==30 and all(r.status=='success' for r in loaded_backup[3])
    assert all(file_hash(path)==sha for path,sha in before.items())
    report={'actual_cases':30,'reuse_over_local_failure':len(first['cache_hits']),
            'first_submitted':len(first['submitted_cases']),'second_submitted':len(second['submitted_cases']),
            'retry_keeps_success':True,'explicit_force_submitted':len(forced['submitted_cases']),
            'force_backup_loadable_cases':len(loaded_backup[2]),'source_histories_unchanged':True}
    atomic_json(ROOT/'results/cache-review/validation.json',report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
