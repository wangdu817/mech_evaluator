"""Read committed cases without changing the batch owner lock."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import uuid
from .atomic_io import atomic_json
from .recovery import verified_history
from .runner import project_root


def create_completed_snapshot(output):
    source = Path(output).resolve()
    if not source.is_relative_to(project_root()):
        raise ValueError('Snapshot source must be inside the project')
    if not (source/'manifest.json').is_file():
        raise ValueError('该目录暂无运行结果，请先运行工况')
    manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    token = hashlib.sha256((str(source)+manifest['created_utc']).encode()).hexdigest()[:12]
    root = project_root()/'results/live-snapshots'/token
    for parent in source.parents:
        if parent.parent == project_root()/'.cache/sessions' and (parent/'session.json').is_file():
            root = parent/'snapshots'/token
            break
    directory = root/'view'
    directory.mkdir(parents=True, exist_ok=True)
    (root/'h').mkdir(exist_ok=True)
    shutil.copytree(source/'inputs', directory/'inputs', dirs_exist_ok=True)
    fallback = {r['case_id']: r for r in manifest.get('results', [])}
    results, pending, committed = [], 0, 0
    for case in manifest['cases']:
        identity = case['id']
        value = fallback.get(identity)
        cache = source/'cache'/f'{identity}.json'
        if cache.is_file():
            try:
                candidate = json.loads(cache.read_text(encoding='utf-8'))
                if candidate.get('case_id') == identity: value = candidate
            except (OSError, ValueError):
                pass
        if value and value.get('status') == 'success':
            if verified_history(value):
                retained = root/'h'/f'{identity[:24]}.h5'
                if not retained.exists():
                    temporary = retained.parent/(uuid.uuid4().hex[:12]+'.tmp')
                    try:
                        # Histories are committed by atomic replacement, never
                        # edited in place. An NTFS link preserves the old inode
                        # through later reruns without duplicating large files.
                        try:
                            os.link(value['history_path'], temporary)
                        except OSError as error:
                            raise ValueError('Cannot retain history with a hard link; use a snapshot on the same NTFS volume') from error
                        if not verified_history({**value, 'history_path': str(temporary)}):
                            raise ValueError('History changed during snapshot copy; refresh the snapshot')
                        temporary.replace(retained)
                    finally:
                        temporary.unlink(missing_ok=True)
                value = {**value, 'history_path': str(retained)}
                if not verified_history(value):
                    raise ValueError('Snapshot history identity mismatch')
            else:
                value = {**value, 'status': 'unverified', 'history_path': '',
                         'reason': 'Snapshot found missing or inconsistent committed history'}
        elif value:
            value = {**value, 'history_path': ''}
        if value: committed += 1
        else:
            pending += 1
            value = {'case_id': identity, 'status': 'cancelled', 'predictions': {},
                'history_path': '', 'validation': {}, 'metadata': {'snapshot_pending': True},
                'reason': 'Snapshot: this case has not yet committed a result; refresh after completion'}
        results.append(value)
    if not committed:
        raise ValueError('暂无完整提交的工况结果，请稍后再载入快照')
    manifest.update(status='snapshot', results=results, active_cases=[], pending_cases=pending,
        snapshot={'source': str(source), 'source_status': manifest['status'],
                  'captured_utc': datetime.now(timezone.utc).isoformat(),
                  'committed_cases': committed, 'pending_cases': pending})
    # Store large mechanism definitions once, rather than once per case.
    catalog = {}
    compact_cases = []
    for case in manifest['cases']:
        mechanism = case['mechanism']
        key = hashlib.sha256(json.dumps(mechanism, sort_keys=True).encode()).hexdigest()
        catalog[key] = mechanism
        compact_cases.append({**case, 'mechanism': {'id': mechanism['id']}, '_snapshot_mechanism': key})
    manifest['cases'] = compact_cases
    manifest['snapshot_mechanisms'] = catalog
    manifest['config'] = {**manifest['config'], 'output': str(directory)}
    atomic_json(directory/'manifest.json', manifest)
    return directory
