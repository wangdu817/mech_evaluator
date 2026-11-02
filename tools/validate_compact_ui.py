from streamlit.testing.v1 import AppTest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
at=AppTest.from_file(str(root/'src/pyteck/respecth/app.py'),default_timeout=60)
at.run()
print('first errors:',[x.message for x in at.exception])
print('tabs:',[x.label for x in at.tabs])
print('elements:',len(at.selectbox),len(at.dataframe))
at.session_state['main_page']='5 图表与导出'
at.run()
print('plot errors:',[x.message for x in at.exception])
print('dataset labels:',at.multiselect(key='figure_datasets').options[:3])
at.selectbox(key='figure_coverage_filter').select('有模拟曲线')
at.session_state['main_page']='5 图表与导出'
at.run()
selection=at.multiselect(key='figure_datasets').value
print('filtered:',len(selection))
at.session_state['main_page']='3 运行任务'
at.run()
print('run errors:',[x.message for x in at.exception])
at.session_state['main_page']='5 图表与导出'
at.run()
print('return errors:',[x.message for x in at.exception])
print('selection persisted:',selection==at.multiselect(key='figure_datasets').value)
assert not at.exception
assert selection==at.multiselect(key='figure_datasets').value


for page in ["2 条件检查","4 误差与覆盖率","6 单工况分析"]:
    at.session_state["main_page"]=page
    at.run()
    print(page,"errors:",[x.message for x in at.exception])
    assert not at.exception
