"""Verify friendly mechanism selection, paired CHEMKIN input and list management."""
from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from pyteck.respecth.yaml_io import load_yaml
ROOT=Path(__file__).resolve().parents[1]
app=AppTest.from_file(str(ROOT/'src/pyteck/respecth/app.py')).run(timeout=60)
assert not app.exception
converted=str((ROOT/'results/clear-26092002/26092002_cantera.yaml').resolve())
app.selectbox(key='mechanism_file').set_value(converted).run(timeout=60)
next(b for b in app.button if b.label=='添加到机理列表').click().run(timeout=60)
assert not app.exception and not app.error
assert len(app.session_state['mechanism_entries'])==1
next(b for b in app.button if b.label=='添加到机理列表').click().run(timeout=60)
assert any('名称已存在' in e.value for e in app.error)
app.radio(key='mechanism_source').set_value('填写文件路径').run(timeout=60)
inp=str(ROOT/'results/clear-26092002/inputs/26092002_syntax.inp')
app.text_input(key='mechanism_path').set_value(inp).run(timeout=60)
next(b for b in app.button if b.label=='添加到机理列表').click().run(timeout=60)
assert any('热力学' in e.value for e in app.error)
app.text_input(key='manual_thermo').set_value(str(ROOT/'results/clear-26092002/inputs/thermo_selected.dat'))
app.text_input(key='mechanism_name').set_value('clear_chemkin')
next(b for b in app.button if b.label=='添加到机理列表').click().run(timeout=60)
assert not app.exception and not app.error
assert len(app.session_state['mechanism_entries'])==2
app.multiselect[0].set_value([str(ROOT.parent/'exp5/Hjuler_1995_Set13.xml')])
next(b for b in app.button if b.label=='生成运行配置').click().run(timeout=60)
config=load_yaml(app.text_area(key='config_text').value)
assert len(config['mechanisms'])==2 and config['mechanisms'][1]['thermo'].endswith('thermo_selected.dat')
app.multiselect(key='mechanisms_remove').set_value(['clear_chemkin']).run(timeout=60)
next(b for b in app.button if b.label=='移除选中机理').click().run(timeout=60)
assert len(app.session_state['mechanism_entries'])==1
assert not app.exception
report={'local_yaml_selection':True,'manual_chemkin_with_thermo':True,'missing_thermo_blocked':True,
        'duplicate_names_blocked':True,'multiple_mechanisms_configured':True,'remove_and_preserve':True}
(ROOT/'results/ui-mechanism-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
