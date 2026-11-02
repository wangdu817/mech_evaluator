"""Choose the data workspace before the GUI writes any user files."""
import json
import os
from pathlib import Path
import uuid

import streamlit as st

WORKSPACE_ENV = 'PYTECK_WORKSPACE'


def initialize_workspace(value):
    if not value.strip():
        raise ValueError('请填写项目保存位置的完整路径。')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('请使用完整的绝对路径。')
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ValueError('所选路径是文件，请选择文件夹。')
    # One local service owns one workspace; inherited by all calculation processes.
    active = os.environ.get(WORKSPACE_ENV)
    if active and Path(active).resolve() != path:
        raise ValueError('当前服务已使用另一项目位置，请关闭此服务并重新启动后切换。')
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ('.write-check-' + uuid.uuid4().hex)
    try:
        with probe.open('x', encoding='utf-8') as stream:
            stream.write('ok')
    finally:
        probe.unlink(missing_ok=True)
    marker = path / '.pyteck-workspace.json'
    if not marker.exists():
        with marker.open('x', encoding='utf-8') as stream:
            json.dump({'schema_version': 1, 'application': 'pyteck-respecth'}, stream)
    os.environ[WORKSPACE_ENV] = str(path)
    return path


def select_workspace():
    if not st.session_state.get('workspace_root'):
        st.subheader('开始工作：选择项目保存位置')
        st.caption('先选择本次工作的根目录。上传文件、机理转换、临时计算、分析、图表及保存项目均放在此目录内；程序安装目录与实验原文件保持独立。')
        default = os.environ.get(WORKSPACE_ENV, str(Path.home() / 'PyTeCK-projects'))
        value = st.text_input('整个项目的保存位置（完整文件夹路径）', default, key='workspace_path_input')
        st.caption('可使用新的空文件夹，也可填写之前的工作目录以载入已有项目。临时结果仍需通过“保存项目”明确保留。')
        if st.button('使用此位置，开始工作', type='primary'):
            try:
                root = initialize_workspace(value)
                st.session_state['workspace_root'] = str(root)
                st.session_state['workspace_notice'] = f'项目保存位置已设置：{root}'
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(f'无法使用该位置：{error}')
        st.stop()
    root = Path(st.session_state['workspace_root'])
    os.environ[WORKSPACE_ENV] = str(root)
    st.sidebar.caption(f'项目保存位置：{root}')
    if st.session_state.get('workspace_notice'):
        st.success(st.session_state['workspace_notice'])
    return root
