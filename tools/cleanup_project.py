"""Dry-run or clean reproducible debris, preserving inputs and numerical results."""
from pathlib import Path
from collections import Counter
import argparse
import datetime
import json
import os
import psutil
from pyteck.respecth.runner import project_root
from pyteck.respecth.cache_maintenance import contained,files_under,busy_reasons,inventory
from pyteck.respecth.atomic_io import atomic_json

ROOT=project_root().resolve()
RETIRED_TOOLS={
    'repair_result_view.py','recover_memory_interruption.py','enable_storage_cache_compatibility.py',
    'run_clear26092002.py','retry_actual_preconditioner.py','ui_result_restore_smoke.py',
    'test_saved_species_ui.py',
    '_remove_retired_code.py',
}
DELIVERY_DEBRIS={
    'cleanup-audit.json','build.txt','legacy-eval-timeout.txt','gui-independent-grid.yaml',
    'live-config-before-update.yaml','ui-state-before-analysis-cache.json','ui-state-before-update.json',
    'tests-final.txt','tests-final.xml','tests-workload.txt','tests-analysis-auto-cache.txt',
    'storage-tests.xml','compact-storage-tests.xml','compact-domain-tests.xml',
}


def selected():
    candidates={}
    def add(path,kind):
        path=contained(ROOT,path)
        if path.is_file(): candidates[path]=kind
    for name in ('tmp','wheel-install','matplotlib','check-storage-solver','compact-validation','analysis-trajectories'):
        for path in files_under(ROOT/'.cache'/name): add(path,'development-cache')
    for path in files_under(ROOT/'.pytest_cache'): add(path,'test-cache')
    for base in ('src','tests','tools','examples'):
        for path in files_under(ROOT/base):
            if '__pycache__' in path.parts or path.suffix in {'.pyc','.pyo'}: add(path,'bytecode')
    for item in inventory(ROOT)['items']:
        if item['category'] in {'obsolete','previews','archives'}: add(Path(item['path']),'reproducible-media')
    for path in files_under(ROOT/'results'):
        if path.suffix=='.log' and not (path.name.startswith('conversion') or path.name in {'initial-conversion.log','load-warnings.log'}):
            add(path,'inactive-log')
        if path.parent==ROOT/'results/runtime' and path.name.startswith('log-cleanup-') and path.suffix=='.json':
            add(path,'old-cleanup-record')
    for name in RETIRED_TOOLS: add(ROOT/'tools'/name,'retired-script')
    for name in DELIVERY_DEBRIS: add(ROOT/'docs/delivery'/name,'obsolete-record')
    return candidates


def protected_snapshot(excluded):
    # No chemistry or numerical artifact is exempted by directory name.
    return {str(p.relative_to(ROOT)):(p.stat().st_size,p.stat().st_mtime_ns)
        for base in (ROOT/'results',ROOT/'inputs',ROOT/'.cache/sessions')
        for p in files_under(base) if p not in excluded}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if reasons:=busy_reasons(ROOT): raise RuntimeError('Active tasks; cleanup refused: '+'; '.join(reasons))
    candidates=selected();opened=set()
    for process in psutil.process_iter(['pid']):
        try:
            opened.update(str(Path(f.path).resolve()).casefold() for f in process.open_files()
                if str(f.path).casefold().startswith(str(ROOT).casefold()))
        except (psutil.Error,OSError): pass
    candidates={p:k for p,k in candidates.items() if str(p.resolve()).casefold() not in opened}
    before=protected_snapshot(candidates)
    expected={p:(p.stat().st_size,p.stat().st_mtime_ns) for p in candidates}
    counts=Counter();sizes=Counter();errors=[]
    for path,kind in sorted(candidates.items()):
        if not args.apply:
            counts[kind]+=1;sizes[kind]+=expected[path][0];continue
        try:
            contained(ROOT,path)
            stat=path.stat()
            if (stat.st_size,stat.st_mtime_ns)!=expected[path]: raise ValueError('File changed; skipped')
            path.unlink();counts[kind]+=1
            if stat.st_nlink==1: sizes[kind]+=stat.st_size
        except (OSError,ValueError) as error: errors.append({'file':str(path.relative_to(ROOT)),'reason':str(error)})
    # Empty directories only, verified inside the project; never recursive-delete a computed root.
    if args.apply:
        for base in (ROOT/'.cache',ROOT/'.pytest_cache',ROOT/'src',ROOT/'tests',ROOT/'tools'):
            for folder,dirs,files in os.walk(base,topdown=False,followlinks=False):
                path=Path(folder)
                if path==base or (base.name!='.cache' and path.name!='__pycache__'): continue
                if path.is_symlink() or path.is_junction(): continue
                try: contained(ROOT,path).rmdir()
                except OSError: pass
    after=protected_snapshot(candidates)
    if before!=after: raise RuntimeError('Protected result/input inventory changed during cleanup')
    report={'date':datetime.date.today().isoformat(),'applied':args.apply,'categories':dict(counts),
        'files':sum(counts.values()),'apparent_freed_bytes':sum(sizes.values()),'bytes_by_category':dict(sizes),
        'protected_files':len(before),'protected_inventory_unchanged':True,'errors':errors,
        'preserved':['source XML/mechanisms','simulation results','saved projects','unsaved sessions',
            'mechanism conversion audit','environment','Git repository','scientific validation evidence']}
    if args.apply: atomic_json(ROOT/'docs/delivery/project-cleanup.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
