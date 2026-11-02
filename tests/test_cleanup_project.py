import importlib.util
import json
import sys
from pathlib import Path
from pyteck.respecth.runner import project_root


def cleanup_module(monkeypatch,tmp_path):
    path=project_root()/'tools/cleanup_project.py'
    spec=importlib.util.spec_from_file_location('cleanup_project',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'busy_reasons',lambda root:[])
    monkeypatch.setattr(module.psutil,'process_iter',lambda fields:[])
    return module


def test_cleanup_removes_only_reviewed_debris(monkeypatch,tmp_path):
    module=cleanup_module(monkeypatch,tmp_path)
    preserved=['results/run/cache/case.h5','results/run/cache/case.json',
        'results/projects/project/manifest.json','.cache/sessions/current/simulation/cache/case.h5',
        'inputs/original.xml','results/chemistry/conversion.log','results/chemistry/load-warnings.log',
        '.cache/ui-session.json','.git/config','.venv313/python.exe','src/live.py']
    removed=['.cache/tmp/test.txt','.cache/wheel-install/source.py','.pytest_cache/cache.json',
        'src/__pycache__/live.pyc','results/runtime/streamlit-old.log',
        'tools/repair_result_view.py','docs/delivery/ui-state-before-update.json']
    for name in preserved+removed:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'unchanged')
    monkeypatch.setattr(sys,'argv',['cleanup_project','--apply'])
    module.main()
    assert all((tmp_path/p).read_bytes()==b'unchanged' for p in preserved)
    assert all(not (tmp_path/p).exists() for p in removed)
    report=json.loads((tmp_path/'docs/delivery/project-cleanup.json').read_text())
    assert report['protected_inventory_unchanged'] and not report['errors']


def test_cleanup_blocks_busy_tasks(monkeypatch,tmp_path):
    import pytest
    module=cleanup_module(monkeypatch,tmp_path)
    monkeypatch.setattr(module,'busy_reasons',lambda root:['active'])
    monkeypatch.setattr(sys,'argv',['cleanup_project','--apply'])
    with pytest.raises(RuntimeError,match='Active tasks'): module.main()


def test_dead_code_cleanup_signature_alias_is_exact(monkeypatch):
    from pyteck.respecth import analysis_cache
    baseline=analysis_cache.numeric_signature()
    actual_hash=analysis_cache.file_hash
    monkeypatch.setattr(analysis_cache,'file_hash',lambda path:'changed' if Path(path).name=='solvers.py' else actual_hash(path))
    assert analysis_cache.numeric_signature()!=baseline


def test_package_sources_compile_and_retired_functions_are_absent():
    import ast
    root=project_root()/'src/pyteck'
    for path in root.rglob('*.py'): compile(path.read_text(encoding='utf-8-sig'),str(path),'exec')
    for name,function in [('analysis.py','_finite_difference_reference'),('solvers.py','_new_history')]:
        tree=ast.parse((root/'respecth'/name).read_text(encoding='utf-8'))
        assert function not in {n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
