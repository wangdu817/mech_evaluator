import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    path=Path(__file__).resolve().parents[1]/'tools/launch_ui.py'
    spec=importlib.util.spec_from_file_location('test_local_launcher',path)
    module=importlib.util.module_from_spec(spec)
    with monkeypatch.context() as scoped:
        scoped.setattr(sys,'path',list(sys.path))
        scoped.setenv('PYTHONPATH','')
        spec.loader.exec_module(module)
        source=tmp_path/'src'
        (source/'pyteck').mkdir(parents=True)
        (source/'pyteck/module.py').write_text('value=1\n')
        tools=tmp_path/'tools';tools.mkdir()
        script=tools/'launch_ui.py';script.write_text('# launcher\n')
        (tmp_path/'start.ps1').write_text('# start\n')
        scoped.setattr(module,'ROOT',tmp_path)
        scoped.setattr(module,'SOURCE',source)
        scoped.setattr(module,'__file__',str(script))
        yield module


def test_source_revision_detects_code_but_ignores_runtime(launcher):
    before=launcher.source_revision()
    (launcher.ROOT/'results').mkdir()
    (launcher.ROOT/'results/log.txt').write_text('runtime')
    assert launcher.source_revision()==before
    (launcher.SOURCE/'pyteck/module.py').write_text('value=2\n')
    assert launcher.source_revision()!=before


def test_existing_service_reloads_after_source_change(launcher):
    directory=launcher.ROOT/'results/runtime';directory.mkdir(parents=True)
    (directory/'server.json').write_text(json.dumps({'pid':100,'source_revision':launcher.source_revision()}))
    assert not launcher.service_needs_reload(100)
    (launcher.SOURCE/'pyteck/module.py').write_text('value=3\n')
    assert launcher.service_needs_reload(100)


def test_legacy_service_detects_updated_source(launcher, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil,'Process',lambda _:SimpleNamespace(create_time=lambda:0))
    assert launcher.service_needs_reload(100)


def test_restart_checks_selected_external_workspace(launcher, monkeypatch, tmp_path):
    import psutil
    from pyteck.respecth import cache_maintenance
    workspace=tmp_path/'chosen-project'
    monkeypatch.setattr(psutil,'Process',lambda _:SimpleNamespace(
        environ=lambda:{'PYTECK_WORKSPACE':str(workspace)},children=lambda **_:[]))
    checked=[]
    def busy(root):
        checked.append(root)
        return ['active run'] if root==workspace else []
    monkeypatch.setattr(cache_maintenance,'busy_reasons',busy)
    assert launcher.restart_blockers(100)==['active run']
    assert checked==[launcher.ROOT,workspace]


def test_stale_busy_service_is_reused_without_shutdown(launcher, monkeypatch):
    app=launcher.SOURCE/'app.py';app.write_text('')
    monkeypatch.setattr(launcher,'APP',app)
    monkeypatch.setattr(launcher,'project_service',lambda _:100)
    monkeypatch.setattr(launcher,'service_needs_reload',lambda _:True)
    monkeypatch.setattr(launcher,'restart_blockers',lambda _:['active run'])
    result=launcher.launch(8502,no_browser=True)
    assert result['reused'] and result['pid']==100
