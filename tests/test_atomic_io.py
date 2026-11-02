import json
from pathlib import Path
from pyteck.respecth.atomic_io import atomic_json


def test_atomic_publication_retries_sharing_violation(tmp_path, monkeypatch):
    original = Path.replace
    calls = []
    def sharing_conflict(path, target):
        calls.append(path)
        if len(calls) < 3:
            raise PermissionError('Windows reader temporarily holds destination')
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', sharing_conflict)
    monkeypatch.setattr('pyteck.respecth.atomic_io.time.sleep', lambda duration: None)
    destination = tmp_path/'manifest.json'
    destination.write_text('{"old": true}')
    atomic_json(destination, {'status': 'running', 'active_cases': ['actual_case']})
    assert len(calls) == 3
    assert json.loads(destination.read_text())['active_cases'] == ['actual_case']
    assert not destination.with_suffix('.json.tmp').exists()
