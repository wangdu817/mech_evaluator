import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pyteck.respecth.ui_workspace import initialize_workspace, WORKSPACE_ENV


@pytest.fixture(autouse=True)
def isolate_workspace(monkeypatch):
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    yield
    os.environ.pop(WORKSPACE_ENV, None)


def startup_app():
    from pyteck.respecth.ui_workspace import select_workspace
    from pyteck.respecth.project_storage import new_session
    import streamlit as st
    root = select_workspace()
    st.session_state.setdefault('session_workspace', str(new_session(root)))


def test_startup_waits_then_uses_selected_directory(tmp_path):
    app = AppTest.from_function(startup_app, default_timeout=60).run()
    assert not app.exception
    assert 'session_workspace' not in app.session_state
    target = tmp_path / '中文项目' / '工作目录'
    app.text_input(key='workspace_path_input').set_value(str(target))
    app.button[0].click().run()
    assert not app.exception
    assert Path(app.session_state['session_workspace']).is_relative_to(target)
    assert any(str(target) in x.value for x in app.success)
    from pyteck.respecth.runner import project_root
    assert project_root() == target
    # New browser sessions must choose explicitly, and can reopen the same root.
    reopened = AppTest.from_function(startup_app, default_timeout=60).run()
    assert 'session_workspace' not in reopened.session_state
    reopened.button[0].click().run()
    assert not reopened.exception
    assert Path(reopened.session_state['session_workspace']).is_relative_to(target)


def test_invalid_and_conflicting_locations(tmp_path):
    with pytest.raises(ValueError): initialize_workspace('relative/path')
    file = tmp_path / 'file'; file.write_text('data')
    with pytest.raises(ValueError): initialize_workspace(str(file))
    first = initialize_workspace(str(tmp_path / 'first'))
    assert (first / '.pyteck-workspace.json').is_file()
    with pytest.raises(ValueError): initialize_workspace(str(tmp_path / 'second'))
    assert not (tmp_path / 'second').exists()


def test_external_workspace_supports_explicit_save(tmp_path):
    from unittest.mock import patch
    from pyteck.respecth.project_storage import save_project
    root = initialize_workspace(str(tmp_path / 'external'))
    with patch('pyteck.respecth.project_storage.busy_reasons', return_value=[]):
        saved = save_project(root, '测试项目', include_results=False, include_analysis=False)
    assert (saved / 'project.json').is_file()
    assert saved.is_relative_to(root)
