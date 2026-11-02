"""Exercise prechecks, saved results, scoring and plot controls in Streamlit."""
from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from pyteck.respecth.runner import load_config

ROOT = Path(__file__).resolve().parents[1]
app = AppTest.from_file(str(ROOT/'src/pyteck/respecth/app.py')).run(timeout=60)
assert not app.exception, [e.message for e in app.exception]
assert len(app.tabs) == 5
assert len(app.multiselect[0].options) == 37
app.text_input(key='comparison_output').set_value(str(ROOT/'results/ui-comparison-control')).run(timeout=60)
assert app.text_input(key='comparison_output').value == str(ROOT/'results/ui-comparison-control')
parallel = next(w for w in app.number_input if w.label == '并行进程数')
parallel.set_value(2).run(timeout=60)
assert app.text_input(key='comparison_output').value == str(ROOT/'results/ui-comparison-control')
assert next(w for w in app.number_input if w.label == '并行进程数').value == 2
config = load_config(ROOT/'examples/respecth/demo.yaml')
app.text_area(key='config_text').set_value(json.dumps(config.to_dict(), ensure_ascii=False))
next(b for b in app.button if b.label == '预检查并保存配置').click().run(timeout=60)
assert not app.exception
assert not app.error, [e.value for e in app.error]
assert app.session_state['checked_text'] == app.text_area(key='config_text').value
app.checkbox(key='confirmed').set_value(True).run(timeout=60)
assert not next(b for b in app.button if b.label == '运行 / 恢复').disabled
app.checkbox(key='force_rerun').set_value(True).run(timeout=60)
assert app.text_area(key='run_reuse_directories').disabled
assert app.checkbox(key='retry_failed').disabled
assert not next(b for b in app.button if b.label == '运行 / 恢复').disabled
app.checkbox(key='force_rerun').set_value(False).run(timeout=60)
assert not app.text_area(key='run_reuse_directories').disabled
app.multiselect(key='run_mechanism_ids').set_value(['gri30']).run(timeout=60)
assert next(b for b in app.button if b.label == '运行 / 恢复').disabled
next(b for b in app.button if b.label == '预检查并保存配置').click().run(timeout=60)
assert app.session_state['run_config']['mechanisms'][0]['id']=='gri30'
assert len(app.session_state['run_config']['mechanisms'])==1
assert not next(b for b in app.button if b.label == '运行 / 恢复').disabled
app.multiselect(key='run_mechanism_ids').set_value([]).run(timeout=60)
assert next(b for b in app.button if b.label == '运行 / 恢复').disabled
app.multiselect(key='run_mechanism_ids').set_value(['gri30','h2o2']).run(timeout=60)
next(b for b in app.button if b.label == '预检查并保存配置').click().run(timeout=60)
original_text = app.text_area(key='config_text').value
app.text_area(key='config_text').set_value(original_text+'\n').run(timeout=60)
assert next(b for b in app.button if b.label == '运行 / 恢复').disabled
app.text_area(key='config_text').set_value(original_text).run(timeout=60)
next(w for w in app.text_input if w.label == '已保存结果目录').set_value(config.output)
next(b for b in app.button if b.label == '载入结果').click().run(timeout=60)
assert not app.exception
assert not app.error, [e.value for e in app.error]
assert not app.checkbox(key='figure_specific').value
assert app.multiselect(key='figure_datasets').value
app.multiselect(key='figure_mechanisms').set_value(['gri30'])
app.checkbox(key='figure_conditions').set_value(True)
app.selectbox(key='figure_conditions_position').set_value('top')
app.number_input(key='figure_conditions_fontsize').set_value(9.)
next(b for b in app.button if b.label == '保存新评分（不重新模拟）').click().run(timeout=60)
assert not app.exception
next(w for w in app.selectbox if w.label == '摩尔组成显示单位').set_value('percent')
next(b for b in app.button if b.label == '保存设置并重绘').click().run(timeout=60)
assert not app.exception
assert not app.error, [e.value for e in app.error]
app.selectbox(key='figure_unit').set_value('ppm').run(timeout=60)
next(b for b in app.button if b.label == '载入结果').click().run(timeout=60)
assert app.selectbox(key='figure_unit').value == 'percent'
assert app.checkbox(key='figure_conditions').value
assert app.selectbox(key='figure_conditions_position').value == 'top'
assert app.number_input(key='figure_conditions_fontsize').value == 9.
assert app.multiselect(key='figure_mechanisms').value == ['gri30']
assert not app.exception
report = {'tabs': [t.label for t in app.tabs], 'xml_options': 37,
          'precheck': True, 'saved_result_loading': True, 'rescoring': True,
          'unit_change_and_redraw': True, 'parallel_control': True, 'all_species_default':True,
          'condition_annotation_settings_persist':True,'mechanism_selection_persist':True,
          'single_mechanism_run_precheck':True,'empty_selection_blocks_run':True,'force_rerun_controls':True,'exceptions': []}
(ROOT/'results/ui-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
