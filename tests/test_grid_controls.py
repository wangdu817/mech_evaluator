import numpy as np
import pytest
from pyteck.respecth.grid_controls import scan_grid


def test_total_preserves_irregular_originals():
    xs = [800., 913., 1000.]
    grid = scan_grid(xs, {'mode': 'count', 'points': 9}, 'pfr', 'temperature')
    assert len(grid) == 9
    assert set(xs) <= set(grid)
    assert np.all(np.diff(grid) > 0)
    assert list(scan_grid(xs, {'mode': 'count', 'points': 2}, 'pfr', 'temperature')) == xs


def test_steps_preserve_originals_and_endpoints():
    grid = scan_grid([800., 853., 905.], {'mode': 'step', 'steps': {'temperature': 20}}, 'pfr', 'temperature')
    assert list(grid) == [800, 820, 840, 853, 860, 880, 900, 905]
    phi = scan_grid([.5, .73, .95], {'mode': 'step', 'steps': {'equivalence ratio': .1}}, 'flame', 'equivalence ratio')
    assert phi == pytest.approx([.5, .6, .7, .73, .8, .9, .95])


@pytest.mark.parametrize('step', [0, -1, float('nan'), float('inf'), 1e-9, None, True])
def test_bad_steps_rejected(step):
    with pytest.raises(ValueError):
        scan_grid([800., 1000.], {'mode': 'step', 'step': step}, 'pfr', 'temperature')


def test_gui_applies_count_and_step():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from pathlib import Path
from pyteck.respecth.grid_controls import render_grid_controls
from pyteck.respecth.yaml_io import load_yaml
st.session_state.setdefault('config_text', 'datasets: []\\ngrid: {enabled: true}\\n')
render_grid_controls(load_yaml(st.session_state['config_text']), Path('.'))
st.text_area('完整配置', key='config_text')
''').run(timeout=30)
    app.number_input(key='grid_count_input').set_value(30)
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert 'points: 30' in app.session_state['config_text']
    app.radio(key='grid_mode_input').set_value('变量间隔').run(timeout=30)
    app.number_input(key='grid_step_temperature').set_value(20.)
    app.number_input(key='grid_step_equivalence ratio').set_value(.1)
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert 'mode: step' in app.session_state['config_text']
    assert 'temperature: 20.0' in app.session_state['config_text']


def test_gui_independent_mechanism_grid():
    from streamlit.testing.v1 import AppTest
    from pyteck.respecth.yaml_io import load_yaml
    app = AppTest.from_string('''
import streamlit as st
from pathlib import Path
from pyteck.respecth.grid_controls import render_grid_controls
from pyteck.respecth.yaml_io import load_yaml
st.session_state.setdefault('config_text', 'mechanisms: [{id: old}, {id: new}]\\ngrid: {enabled: true, mode: count, points: 59}\\n')
render_grid_controls(load_yaml(st.session_state['config_text']), Path('.'))
''').run(timeout=30)
    app.selectbox(key='grid_mechanism_target').set_value('new').run()
    app.number_input(key='grid_count_input').set_value(80)
    app.button[0].click().run()
    assert not app.exception
    data = load_yaml(app.session_state['config_text'])
    assert data['grid']['points']==59 and 'grid' not in data['mechanisms'][0]
    assert data['mechanisms'][1]['grid']['points']==80


def test_default_and_disabled_only_build_experiment_cases():
    from pathlib import Path
    from pyteck.respecth.runner import load_config, prepare_run
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / 'examples/respecth/demo.yaml')
    config.grid = {}
    _, original, _ = prepare_run(config)
    assert original and all(c.role == 'scoring' for c in original)
    config.grid = {'enabled': False, 'mode': 'count', 'points': 100}
    _, disabled, _ = prepare_run(config)
    assert {c.id for c in disabled} == {c.id for c in original}
    config.grid = {'enabled': True, 'mode': 'count', 'points': 8}
    _, dense, _ = prepare_run(config)
    assert len(dense) > len(original)
    assert {c.id for c in dense if c.role == 'scoring'} == {c.id for c in original}


def test_gui_defaults_to_no_grid_and_can_disable_existing_grid():
    from streamlit.testing.v1 import AppTest
    from pyteck.respecth.yaml_io import load_yaml
    app = AppTest.from_string('''
import streamlit as st
from pathlib import Path
from pyteck.respecth.grid_controls import render_grid_controls
from pyteck.respecth.yaml_io import load_yaml
st.session_state.setdefault('config_text', 'datasets: []')
render_grid_controls(load_yaml(st.session_state['config_text']), Path('.'))
''', default_timeout=60).run()
    assert not app.exception
    assert app.checkbox(key='grid_enabled_input').value is False
    assert app.number_input(key='grid_count_input').disabled
    app.checkbox(key='grid_enabled_input').check().run()
    app.button[0].click().run()
    assert load_yaml(app.session_state['config_text'])['grid']['enabled'] is True
    app.checkbox(key='grid_enabled_input').uncheck().run()
    app.button[0].click().run()
    assert not app.exception
    assert load_yaml(app.session_state['config_text'])['grid']['enabled'] is False
    assert '仅使用原始实验工况' in app.session_state['action_notice']
