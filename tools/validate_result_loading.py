from pathlib import Path
from streamlit.testing.v1 import AppTest
import json
from collections import Counter
root=Path(__file__).resolve().parents[1]
at=AppTest.from_file(str(root/'src/pyteck/respecth/app.py'),default_timeout=120).run()
at.session_state['main_page']='3 运行任务'
at.run()
button=next(b for b in at.button if b.label=='载入最近运行批次用于评分与绘图')
button.click()
at.session_state['main_page']='3 运行任务'
at.run()
assert not at.exception,[x.message for x in at.exception]
assert at.session_state['loaded_output']==at.session_state['output']
assert 'pending_result_output' not in at.session_state
assert any('载入成功' in x.value for x in at.success)
manifest,experiments,cases,results=at.session_state['loaded_run']
print('Immediate loading: OK',len(experiments),len(cases))
print('Visible confirmation:',at.session_state['result_load_notice'])
assert any('未成功 3387' in x.value for x in at.warning)
at.session_state['main_page']='5 图表与导出'
at.run()
at.selectbox(key='figure_coverage_filter').select('有模拟曲线')
at.session_state['main_page']='5 图表与导出'
at.run()
assert not at.exception
options=at.multiselect(key='figure_datasets').options
print('Available XML:',options)
assert len(options)==5
# Invalid loading must retain the previous results and show an error.
at.session_state['main_page']='4 误差与覆盖率'
at.run()
before=at.session_state['loaded_output']
at.text_input(key='saved_result_output').set_value(str(root/'results/nonexistent-ui-test'))
next(b for b in at.button if b.label=='载入结果').click()
at.session_state['main_page']='4 误差与覆盖率'
at.run()
assert at.error and at.session_state['loaded_output']==before
print('Failed load retains previous results: OK')
from pyteck.respecth.coverage import dataset_coverage
coverage=dataset_coverage(experiments,cases,results)
report={'source':before,'cases':len(cases),'statuses':dict(Counter(r.status for r in results)),
        'available_xml':options,'coverage':coverage,
        'pickle_failures':sum('pickle' in r.reason for r in results if r.reason),
        'gui_checks':['immediate run-page load','visible success notice','coverage filter','failed-load retention']}
(root/'results/gui-result-loading-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
