"""Real XML proof: resume skips, force submits, backups preserve, resume skips again."""
from pathlib import Path
from dataclasses import replace
import json,hashlib,shutil
from pyteck.respecth.runner import load_config,run_project

root=Path(__file__).resolve().parents[1]
config=load_config(root/'examples/respecth/clear-26092002.yaml')
output=root/'results/force-rerun-validation'
config=replace(config,datasets=[str(root.parent/'exp5/Hjuler_1995_Set13.xml')],output=str(output),
               reuse_results=[str(root/'results/clear-26092002/run')],retry_failed=False)
if __name__=='__main__':
    first=run_project(config)
    assert len(first['cache_hits'])==12 and not first['submitted_cases']
    # Localize the unchanged historical bytes to exercise backup of local HDF5 files.
    for result in first['results']:
        local=output/'cache'/f"{result['case_id']}.h5"
        if Path(result['history_path'])!=local:shutil.copy2(result['history_path'],local)
        result['history_path']=str(local)
        (output/'cache'/f"{result['case_id']}.json").write_text(json.dumps(result),encoding='utf8')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (output/'cache').iterdir() if p.is_file()}
    ids={c['id'] for c in first['cases']}
    forced=run_project(config,force_rerun=True)
    assert not forced['cache_hits'] and not forced['reused_cases']
    assert len(forced['submitted_cases'])==12 and {c['id'] for c in forced['cases']}==ids
    assert all(r['status']=='success' and r['validation']['passed'] for r in forced['results'])
    backup=Path(forced['execution']['cache_backup'])
    for name,sha in before.items():assert hashlib.sha256((backup/'cache'/name).read_bytes()).hexdigest()==sha
    after={p.name:p.stat().st_mtime_ns for p in (output/'cache').iterdir() if p.is_file()}
    resumed=run_project(config)
    assert len(resumed['cache_hits'])==12 and not resumed['submitted_cases']
    assert after=={p.name:p.stat().st_mtime_ns for p in (output/'cache').iterdir() if p.is_file()}
    report={'actual_mechanism':'clear_26092002','XML':'Hjuler_1995_Set13.xml','cases':12,
        'normal_cache_hits':12,'forced_cache_hits':0,'forced_submitted':12,'forced_verified_success':12,
        'cache_identity_unchanged':True,'backup_files_verified':len(before),'backup_directory':str(backup),'resume_cache_hits':12}
    (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
