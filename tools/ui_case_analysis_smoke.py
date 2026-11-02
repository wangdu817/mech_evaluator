"""Exercise set -> variable -> mechanism -> target flow on actual saved data."""
from pathlib import Path
import json
import yaml
from streamlit.testing.v1 import AppTest
from pyteck.respecth.runner import load_run,project_root

root=project_root();source=root/'results/clear-26092002/comparison'
loaded=load_run(source);manifest,experiments,cases,results=loaded
app=AppTest.from_file(str(root/'src/pyteck/respecth/app.py'))
for key,value in dict(config_text=yaml.safe_dump(manifest['config'],allow_unicode=True),
    output=str(source),loaded_run=loaded,loaded_output=str(source)).items(): app.session_state[key]=value
app.run(timeout=60)
assert not app.exception and not app.error
assert any(t.label=='6 单工况分析' for t in app.tabs)
ignition=next(e for e in experiments if e.kind=='ignition')
app.selectbox(key='analysis_dataset').set_value(ignition.id).run(timeout=60)
assert not app.exception and not app.error
assert app.selectbox(key='analysis_variable').value=='temperature'
selected_value=app.selectbox(key='analysis_value').value
selected_case=next(c for c in cases if c.id==app.selectbox(key='analysis_case').value)
assert selected_case.experiment_id==ignition.id
assert selected_case.condition.scan_value==selected_value
app.radio(key='analysis_mode').set_value('仅敏感性').run(timeout=60)
assert not any(s.key=='analysis_species' for s in app.selectbox)
assert not any(s.key=='analysis_row' for s in app.slider)
assert app.selectbox(key='analysis_target').value=='temperature_at_fixed_time'
assert app.number_input(key='analysis_time').value>0
assert next(b for b in app.button if b.label=='分析选中工况').disabled
app.text_input(key='analysis_reactions').set_value('13').run(timeout=60)
assert not next(b for b in app.button if b.label=='分析选中工况').disabled
assert not app.exception and not app.error
report={'separate_page':True,'set_then_variable_then_mechanism':True,
    'variable_value_matches_case':True,'ignition_defaults_to_temperature_proxy':True,
    'explicit_reaction_selection_required':True,'sensitivity_without_rop':True,'no_simulation_started':True}
(root/'results/case-analysis-ui-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
