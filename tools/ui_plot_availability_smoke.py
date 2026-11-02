from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from pyteck.respecth.runner import project_root

root=project_root()
app=AppTest.from_file(str(root/'src/pyteck/respecth/app.py')).run(timeout=90)
experiments=app.session_state['loaded_run'][1]
ids=[e.id for e in experiments if Path(e.path).stem in {'Marrodan_2024_Set4','Marrodan_2024_Set5'}]
app.multiselect(key='figure_datasets').set_value(ids).run(timeout=90)
assert not app.exception and not app.error
assert any('对应图片只有实验点' in w.value for w in app.warning)
assert any('旧版本输入限制已移除' in w.value for w in app.info)
assert not any('干湿' in e.value or '湿基' in e.value or '干基' in e.value for e in list(app.info)+list(app.caption))
(root/'results/ui-plot-availability-smoke.json').write_text(json.dumps({'actual_selected_sets':ids,
    'warns_no_simulation':True,'explains_pending_basis':True,'no_simulation_started':True},ensure_ascii=False,indent=2),encoding='utf-8')
print('Actual-set plot availability UI passed')
