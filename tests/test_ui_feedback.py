"""Receipts survive reruns and distinguish applied settings from saved files."""
import yaml
from streamlit.testing.v1 import AppTest


def receipt_app():
    import streamlit as st
    from pyteck.respecth.ui_feedback import show_action_notice, action_success, clear_action_notice
    slot = show_action_notice()
    if st.button('保存'):
        clear_action_notice(slot)
        action_success('已保存到文件', slot)
    if st.button('失败'):
        clear_action_notice(slot)
        st.error('写入失败')


def test_receipt_persists_and_failure_clears_success():
    at = AppTest.from_function(receipt_app, default_timeout=30).run()
    at.button[0].click().run()
    assert [x.value for x in at.success] == ['已保存到文件']
    at.run()
    assert [x.value for x in at.success] == ['已保存到文件']
    at.button[1].click().run()
    assert not at.success
    assert at.error[0].value == '写入失败'


def grid_app():
    import streamlit as st
    import yaml
    from pyteck.respecth.runner import project_root
    from pyteck.respecth.ui_feedback import show_action_notice
    from pyteck.respecth.grid_controls import render_grid_controls
    st.session_state.setdefault('config_text', 'grid: {enabled: true, mode: count, points: 100}\n')
    show_action_notice()
    render_grid_controls(yaml.safe_load(st.session_state['config_text']), project_root())


def test_grid_receipt_survives_automatic_rerun():
    at = AppTest.from_function(grid_app).run()
    at.number_input(key='grid_count_input').set_value(59)
    at.button[0].click().run()
    assert not at.exception
    assert '每组总点数 59' in at.success[0].value
    assert '写入文件' in at.success[0].value
    assert yaml.safe_load(at.session_state['config_text'])['grid']['points'] == 59
    at.run()
    assert '每组总点数 59' in at.success[0].value
    assert 'action_notice_toast' not in at.session_state


def test_disabled_grid_receipt_is_accurate():
    at = AppTest.from_function(grid_app).run()
    at.checkbox[0].uncheck().run()
    at.button[0].click().run()
    assert '已关闭绘图加密' in at.success[0].value
    assert yaml.safe_load(at.session_state['config_text'])['grid']['enabled'] is False


def test_generate_configuration_receipt_with_real_xml():
    from pyteck.respecth.runner import project_root
    root = project_root()
    at = AppTest.from_file(str(root / 'src/pyteck/respecth/app.py'), default_timeout=30)
    at.run()
    path = str(next((root.parent / 'exp5').glob('*.xml')))
    at.multiselect(key='input_datasets').set_value([path]).run()
    button = next(b for b in at.button if b.label == '生成运行配置')
    button.click().run()
    assert not at.exception
    count = len(at.session_state['mechanism_entries'])
    assert any(f'运行配置已生成：1 份 XML、{count} 个机理' in s.value for s in at.success)
    at.run()
    assert any('运行配置已生成' in s.value for s in at.success)
    at.multiselect(key='input_datasets').set_value([]).run()
    next(b for b in at.button if b.label == '生成运行配置').click().run()
    assert any('请先选择至少一份实验 XML' in e.value for e in at.error)
    assert not any('运行配置已生成' in s.value for s in at.success)
