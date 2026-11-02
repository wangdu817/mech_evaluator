"""Round-trip an actual saved case through a project and remove its temp source."""
from dataclasses import asdict
from pathlib import Path
import json
import shutil
from pyteck.respecth.runner import project_root,load_run
from pyteck.respecth.project_storage import new_session,save_project,discard_sessions
from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.models import file_hash


def main():
    root=project_root()
    source=root/'results/ui-run'
    manifest,experiments,cases,results=load_run(source)
    result_map={r.case_id:r for r in results}
    case=next(c for c in cases if c.id in result_map and result_map[c.id].status=='success'
              and result_map[c.id].validation.get('passed') and Path(result_map[c.id].history_path).is_file())
    result=result_map[case.id];experiment=next(e for e in experiments if e.id==case.experiment_id)
    original_manifest=file_hash(source/'manifest.json')
    history_hash=file_hash(result.history_path)
    workspace=new_session(root);run=workspace/'simulation'
    (run/'inputs').mkdir(parents=True)
    shutil.copy2(source/'inputs'/f'{experiment.id}.xml',run/'inputs'/f'{experiment.id}.xml')
    frozen={**manifest,'cases':[asdict(case)],'results':[asdict(result)],'experiments':[asdict(experiment)],
            'config':{**manifest['config'],'output':str(run)}}
    atomic_json(run/'manifest.json',frozen)
    name='storage-validation-'+workspace.name[:8]
    saved=save_project(root,name,run_output=run,include_figures=False,config=frozen['config'])
    discarded=discard_sessions(root,[str(workspace)])
    restored=load_run(saved/'simulation')
    assert restored[2][0].id==case.id
    assert file_hash(restored[3][0].history_path)==history_hash
    assert file_hash(source/'manifest.json')==original_manifest
    assert Path(restored[2][0].mechanism.path).is_relative_to(saved)
    report={'saved_project':str(saved),'case':case.id,'mechanism':case.mechanism.id,
            'status':restored[3][0].status,'history_hash_preserved':True,'source_manifest_unchanged':True,
            'temporary_directories_removed':discarded,'new_simulations':0}
    atomic_json(root/'docs/delivery/project-storage-verification.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__': main()
