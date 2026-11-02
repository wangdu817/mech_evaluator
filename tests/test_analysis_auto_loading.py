"""Switch real saved sensitivity -> ROP -> sensitivity without a worker."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from streamlit.testing.v1 import AppTest


def saved_analysis_app(job_path):
    import streamlit as st
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch
    from pyteck.respecth import analysis_ui as ui
    from pyteck.respecth.models import case_from_dict, result_from_dict
    data=json.loads(Path(job_path).read_text(encoding='utf-8'))
    case=case_from_dict(data['case']);result=result_from_dict(data['result'])
    target=next(t for t in case.targets if t['key']==data['settings']['target_key'])
    st.session_state.setdefault('analysis_mode','仅敏感性')
    st.session_state.setdefault('analysis_reactions',','.join(str(i+1) for i in data['settings']['reaction_indices']))
    st.session_state.setdefault('analysis_species_multi',[target['species']])
    st.session_state.setdefault('analysis_floor',data['settings'].get('zero_floor',1e-20))
    st.session_state['loaded_run']=({},[SimpleNamespace(id=case.experiment_id,path='actual-set.xml')],[case],[result])
    with patch.object(ui,'diagnostic_candidates',return_value=([case],{},[])), \
         patch.object(ui.subprocess,'Popen',side_effect=AssertionError('Cached switch started a solver')):
        ui.render_analysis_page()


def test_real_cache_automatically_restores_after_mode_switch():
    from pyteck.respecth.runner import project_root
    from pyteck.respecth.analysis_cache import reusable_directory
    root=project_root()
    chosen=None
    for path in (root/'results/analysis').glob('*/job.json'):
        payload=json.loads(path.read_text(encoding='utf-8'))
        if payload['case']['kind']!='pfr' or not payload['settings'].get('sensitivity'):
            continue
        if not reusable_directory(payload,component='sensitivity'):
            continue
        rop=json.loads(json.dumps(payload))
        target=next(t for t in payload['case']['targets'] if t['key']==payload['settings']['target_key'])
        rop['settings'].update(sensitivity=False,rop=True,species=target['species'])
        if reusable_directory(rop,component='rop'):
            chosen=path;break
    if chosen is None:
        pytest.skip('No matching real sensitivity/ROP pair available')
    original={p:p.read_bytes() for p in (root/'results/analysis').glob('*/report.json')}
    at=AppTest.from_function(saved_analysis_app,args=(str(chosen),),default_timeout=60).run()
    assert not at.exception
    sensitivity_directory=at.session_state['analysis_directory']
    assert sensitivity_directory
    assert next(b for b in at.button if b.label=='分析选中工况').disabled
    at.radio(key='analysis_mode').set_value('仅 ROP').run()
    assert not at.exception
    assert at.session_state['analysis_directory']!=sensitivity_directory
    assert next(b for b in at.button if b.label=='分析选中工况').disabled
    at.radio(key='analysis_mode').set_value('仅敏感性').run()
    assert not at.exception
    assert at.session_state['analysis_directory']==sensitivity_directory
    assert next(b for b in at.button if b.label=='分析选中工况').disabled
    at.radio(key='analysis_mode').set_value('敏感性与 ROP').run()
    assert not at.exception
    assert len(at.session_state['analysis_directories'])==2
    assert next(b for b in at.button if b.label=='分析选中工况').disabled
    at.radio(key='analysis_mode').set_value('仅敏感性').run()
    target_species=target['species']
    alternate=next(s for s in payload['case']['mechanism']['species'] if s!=target_species)
    at.multiselect(key='analysis_species_multi').set_value([target_species,alternate]).run()
    assert not at.exception
    assert len(at.session_state['analysis_cache_plan'])==1
    assert at.session_state['analysis_directory']==sensitivity_directory
    assert next(b for b in at.button if b.label=='分析选中工况').disabled
    at.multiselect(key='analysis_species_multi').set_value([alternate]).run()
    assert not at.exception
    assert at.session_state['analysis_directory']==sensitivity_directory
    assert next(b for b in at.button if b.label=='分析选中工况').disabled
    assert all(path.read_bytes()==value for path,value in original.items())
