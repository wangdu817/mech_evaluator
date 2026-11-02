"""Recover an interrupted manifest from independently committed case files."""
from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
import h5py
import numpy as np
from .atomic_io import atomic_json


def verified_history(result):
    if result.get('status') != 'success' or result.get('validation', {}).get('passed') is not True:
        return False
    try:
        with h5py.File(result['history_path'], 'r') as history:
            if history.attrs.get('case_id') != result['case_id'] or not history.attrs.get('complete', True):
                return False
            if json.loads(history.attrs['validation']).get('passed') is not True:
                return False
            return bool(len(history['temperature']) and np.all(np.isfinite(history['mole_fractions'][-1])))
    except (OSError, KeyError, ValueError, TypeError):
        return False


def recover_interrupted_run(output):
    from .runner import project_root, _publish_progress
    from .models import result_from_dict
    output=Path(output).resolve()
    if not output.is_relative_to(project_root()):
        raise ValueError('Recovery output must be inside the project')
    if (output/'run.lock').exists():
        raise ValueError('Run owner lock exists; recovery must wait until the owner has stopped')
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'running':
        return manifest
    destination=output/'recovery-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    destination.mkdir(parents=True)
    shutil.copy2(output/'manifest.json', destination/'manifest.json')
    records={r['case_id']:r for r in manifest['results']}
    recovered=[]
    for case in manifest['cases']:
        path=output/'cache'/f"{case['id']}.json"
        if path.exists():
            try:
                value=json.loads(path.read_text(encoding='utf-8'))
                if value['case_id']==case['id']:
                    records[case['id']]=value
            except (OSError, ValueError, KeyError):
                pass
        value=records.get(case['id'])
        if value and value['status']=='success' and not verified_history(value):
            value={**value, 'status':'unverified', 'reason':'Recovery found missing or inconsistent committed history'}
        if value is None:
            value={'case_id':case['id'],'status':'cancelled','predictions':{},
                   'reason':'Interrupted batch: no committed result; resume to compute this case',
                   'history_path':'','validation':{},'metadata':{}}
        recovered.append(value)
    manifest.update(results=recovered,status='cancelled',active_cases=[],pending_cases=0,
                    finished_utc=datetime.now(timezone.utc).isoformat(),
                    recovery={'original_manifest':str(destination/'manifest.json'),
                              'source':'Committed per-case JSON and HDF5; uncommitted cases cancelled'})
    atomic_json(output/'manifest.json', manifest)
    _publish_progress(output,manifest,{r['case_id']:result_from_dict(r) for r in recovered},{},0)
    return manifest
