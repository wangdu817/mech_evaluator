"""Exercise actual saved runs and selection/precheck UI without recomputing chemistry."""
from pathlib import Path
import json
import yaml
from streamlit.testing.v1 import AppTest
from pyteck.respecth.runner import load_run

ROOT = Path(__file__).resolve().parents[1]
old = json.loads((ROOT/'results/actual-audited/full/manifest.json').read_text(encoding='utf-8'))
config = old['config'].copy()
config['mechanisms'] = [{'id':'clear_26092002', 'path':str(ROOT/'results/clear-26092002/26092002_cantera.yaml'), 'species_map':{'Ar':'AR'}}]
config['output'] = str(ROOT/'results/ui-scope-smoke')
config['grid'] = {'enabled':False}
app = AppTest.from_file(str(ROOT/'src/pyteck/respecth/app.py'))
app.session_state['config_text'] = yaml.safe_dump(config, allow_unicode=True)
app.session_state['output'] = str(ROOT/'results/actual-audited/full')
app.session_state['progress'] = (876,876,'success')
app.session_state['completion'] = 'completed'
app.session_state['loaded_run'] = load_run(ROOT/'results/clear-26092002/comparison')
app.session_state['loaded_output'] = str(ROOT/'results/clear-26092002/comparison')
app.session_state['confirmed'] = True
app.run(timeout=60)
assert not app.exception and not app.error
assert any('历史批次结果' in h.value for h in app.subheader)
assert any('缺少 31 份 XML' in w.value for w in app.warning)
chart_nodes = [e for e in app if 'vega' in e.type]
assert len(chart_nodes) == 5, [(e.type) for e in app if 'chart' in e.type]
assert next(b for b in app.button if b.label=='运行 / 恢复').disabled
next(b for b in app.button if b.label=='预检查本次选择').click().run(timeout=60)
assert not app.exception and not app.error
assert not next(b for b in app.button if b.label=='运行 / 恢复').disabled
next(b for b in app.button if b.label=='选择本批次全部数据集和机理').click().run(timeout=60)
assert len(app.multiselect(key='figure_datasets').value)==6
assert len(app.multiselect(key='figure_mechanisms').value)==3
app.multiselect(key='run_mechanism_ids').set_value([]).run(timeout=60)
assert next(b for b in app.button if b.label=='运行 / 恢复').disabled
assert not app.exception
report = {'historical_batch_separated':True, 'missing_xml_31_visible':True,
          'five_actual_result_charts':True, 'precheck_enables_selected_run':True,
          'all_loaded_xml_and_mechanisms_selectable':True, 'empty_selection_blocked':True,
          'no_simulation_started':True}
(ROOT/'results/ui-scope-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
