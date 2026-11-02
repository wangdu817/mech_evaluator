from pathlib import Path

import pytest

from pyteck.respecth.reader import discover_experiments


def put(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<experiment/>', encoding='utf-8')
    return path


def test_arbitrary_names_nested_and_direct_xml(tmp_path):
    paths = [put(tmp_path, name) for name in (
        'direct.xml', 'Li_2015/set1.xml', 'Shi_2018/mix/nested.XML',
        'pw/data.xml', 'exp1/old-layout.xml')]
    assert discover_experiments(tmp_path) == sorted(paths)
    assert discover_experiments(tmp_path / 'Li_2015') == [paths[1]]


def test_generated_archive_draft_and_project_files_excluded(tmp_path):
    keep = put(tmp_path, 'Li_2015/current.xml')
    for name in ('.respecth/archive/old.xml', '.respecth/references/reference.xml',
                 '.cache/frozen.xml', 'results/saved/frozen.xml',
                 'archive/old.xml', 'backup_20261030/old.xml', '归档/old.xml',
                 'Li_2015/file.draft.xml', 'Li_2015/file.new.xml', '.hidden.xml'):
        put(tmp_path, name)
    put(tmp_path, 'program/examples/demo.xml')
    (tmp_path / 'program/UPSTREAM.json').write_text('{}')
    put(tmp_path, 'saved/simulation/frozen.xml')
    (tmp_path / 'saved/project.json').write_text('{}')
    assert discover_experiments(tmp_path) == [keep]


def test_missing_or_file_path_is_reported(tmp_path):
    with pytest.raises(NotADirectoryError):
        discover_experiments(tmp_path / 'missing')
    with pytest.raises(NotADirectoryError):
        discover_experiments(put(tmp_path, 'one.xml'))


def data_page(workspace, library):
    import os
    from unittest.mock import patch
    import streamlit as st
    from pyteck.respecth.app import main
    st.session_state['workspace_root'] = workspace
    st.session_state.setdefault('data_root', library)
    with patch.dict(os.environ):
        main()


def test_gui_lists_named_folders_and_shows_count(tmp_path):
    from streamlit.testing.v1 import AppTest
    library = tmp_path / 'literature_data'
    one = put(library, 'Li_2015/mix1.xml')
    two = put(library, 'pw/set/data.xml')
    put(library, '.respecth/archive/old.xml')
    app = AppTest.from_function(data_page, args=(str(tmp_path / 'workspace'), str(library)),
                                default_timeout=60).run()
    assert not app.exception
    widget = app.multiselect(key='input_datasets')
    assert len(widget.options) == 2
    widget.set_value([str(one), str(two)]).run()
    assert not app.exception
    assert any('已找到 2 份' in item.value for item in app.caption)
    assert set(app.session_state['input_datasets']) == {str(one), str(two)}
