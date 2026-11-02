"""Persistent result selection, independent of the last simulated mechanism."""
from pathlib import Path
import json
import os
from .atomic_io import atomic_json
from .runner import project_root,load_run


def save_result_view(output):
    path=Path(output).resolve()
    if not path.is_relative_to(project_root()) or not (path/'manifest.json').is_file():
        raise ValueError('Select an existing project result directory')
    # Remembering a view is temporary UI state, not an explicit saved project.
    destination=project_root()/'.cache/result-view-state.json'
    destination.parent.mkdir(exist_ok=True)
    atomic_json(destination,{'loaded_output':str(path)})


def restore_result_view():
    path=project_root()/'.cache/result-view-state.json'
    if not path.exists(): path=project_root()/'results/result-view-state.json'
    if not path.exists(): return None
    saved=json.loads(path.read_text(encoding='utf-8'));directory=Path(saved['loaded_output']).resolve()
    if not directory.is_relative_to(project_root()): raise ValueError('Saved result view escaped the project')
    from .result_access import load_result_view
    directory, run = load_result_view(directory)
    return str(directory), run


def discover_saved_results():
    """Bounded discovery; never traverse histories, analysis jobs or backups."""
    base=project_root()/'results';records=[]
    skip={'cache','prepared','inputs','figures','analysis','recovery-backups','memory-fix'}
    for location,folders,files in os.walk(base):
        path=Path(location);relative=path.relative_to(base)
        folders[:]=[name for name in folders if name not in skip and not any(word in name.lower() for word in ('smoke','test','demo','browser','acceptance'))] if len(relative.parts)<3 else []
        if 'manifest.json' not in files: continue
        try:
            data=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
            if not isinstance(data.get('cases'),list): continue
            successes=sum(r.get('status')=='success' and r.get('validation',{}).get('passed') is True for r in data.get('results',[]))
            records.append({'path':str(path.resolve()),'mechanisms':sorted({c['mechanism']['id'] for c in data['cases']}),
                'xml_count':len(data['experiments']),'success':successes,'total':len(data['cases']),
                'status':data['status'],'mtime':(path/'manifest.json').stat().st_mtime})
        except (OSError,ValueError,KeyError,TypeError): continue
    return sorted(records,key=lambda r:-r['mtime'])
