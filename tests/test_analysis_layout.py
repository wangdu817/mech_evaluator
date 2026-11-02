import json
from streamlit.testing.v1 import AppTest


def analysis_layout_app(directory, loaded=True, multiple=False):
    from pathlib import Path
    from types import SimpleNamespace as NS
    from unittest.mock import patch
    import numpy as np
    import streamlit as st
    from pyteck.respecth import analysis_ui as ui

    class Running:
        def poll(self): return None

    st.session_state['analysis_directory']=directory
    st.session_state['analysis_process']=Running()
    st.session_state['analysis_mode']='仅 ROP'
    case=NS(id='case1',experiment_id='set1',group_id='g1',point_indices=[0],
            condition=NS(scan_name='temperature',scan_value=1000.,temperature=1000.,pressure=101325.),
            mechanism=NS(id='mech1',species=['OH']),kind='pfr',role='scoring',config={},targets=[{'key':'oh','species':'OH','quantity':'composition'}])
    result=NS(case_id='case1',history_path='unused',predictions={'OH':0.1})
    cases=[case];results=[result]
    if multiple:
        from copy import deepcopy
        second=deepcopy(case);second.id='case2';second.mechanism.id='mech2'
        second.condition.scan_value=1100.;second.condition.temperature=1100.
        second_result=deepcopy(result);second_result.case_id='case2'
        cases.append(second);results.append(second_result)
    if loaded:
        st.session_state['loaded_run']=({},[NS(id='set1',path='set1.xml')],cases,results)
    with patch.object(ui,'asdict',side_effect=vars), \
         patch.object(ui,'diagnostic_candidates',return_value=(cases,{},[])), \
         patch.object(ui,'history_coordinates',return_value=('time',np.array([0.,1.]))):
        ui.render_analysis_page()


def test_running_controls_share_start_panel_and_cancel(tmp_path):
    (tmp_path/'progress.json').write_text(json.dumps({'done':2,'total':5,'message':'积分中'}),encoding='utf-8')
    at=AppTest.from_function(analysis_layout_app,args=(str(tmp_path),),default_timeout=30).run()
    assert not at.exception
    start=next(b for b in at.button if b.label=='分析选中工况')
    cancel=next(b for b in at.button if b.label=='取消单工况分析')
    assert start.disabled
    # Only run controls and their live fragment belong to this bordered panel.
    panels=[b for b in at.main if b.type=='flex_container' and b.proto.flex_container.border]
    assert len(panels)==1
    assert [b.label for b in panels[0].button]==['分析选中工况','取消单工况分析']
    assert len(at.get('progress'))==1
    cancel.click().run()
    assert not at.exception
    assert (tmp_path/'CANCEL').exists()


def test_running_job_remains_cancellable_without_loaded_batch(tmp_path):
    (tmp_path/'progress.json').write_text('{"done":0,"total":5}',encoding='utf-8')
    at=AppTest.from_function(analysis_layout_app,args=(str(tmp_path),False),default_timeout=30).run()
    assert not at.exception
    assert any(b.label=='取消单工况分析' for b in at.button)



def test_multiple_values_and_mechanisms_select_all_matching_cases(tmp_path):
    (tmp_path/'progress.json').write_text('{"done":0,"total":5}',encoding='utf-8')
    at=AppTest.from_function(analysis_layout_app,args=(str(tmp_path),True,True),default_timeout=30).run()
    assert not at.exception
    at.multiselect(key='analysis_values_multi').set_value([1000.,1100.]).run()
    at.multiselect(key='analysis_mechanisms_multi').set_value(['mech1','mech2']).run()
    assert not at.exception
    assert at.multiselect(key='analysis_cases_multi').value==['case1','case2']
    assert at.multiselect(key='analysis_species_multi').value==['OH']
