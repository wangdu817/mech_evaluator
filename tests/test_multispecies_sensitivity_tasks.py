"""Species selection is a view, not a second reactor sensitivity integration."""
import pytest
from streamlit.testing.v1 import AppTest


def reactor_picker_app(directory, kind):
    import streamlit as st
    import numpy as np
    import cantera as ct
    from pathlib import Path
    from types import SimpleNamespace as NS
    from unittest.mock import patch
    from pyteck.respecth import analysis_ui as ui
    from pyteck.respecth.models import Condition, SimulationCase, CaseResult
    from pyteck.respecth.cases import prepare_mechanism
    source=Path(directory)/'gas.yaml'
    if not source.exists(): source.write_text(ct.Solution('h2o2.yaml').write_yaml())
    mechanism=prepare_mechanism({'id':'h2','path':str(source),'prepared_dir':str(Path(directory)/'prepared')})
    history=Path(directory)/'history.h5';history.write_bytes(b'fixture-history')
    targets=[{'key':s,'quantity':'composition','species':s,'units':'mole fraction'} for s in ['H2','O2']]
    case=SimulationCase('reactor-ui','set','dg1',[0],kind,
        Condition('temperature',1000.,1000.,101325.,{'H2':2.,'O2':1.}),mechanism,{},targets)
    result=CaseResult(case.id,'success',{'H2':.2,'O2':.1},history_path=str(history),validation={'passed':True})
    st.session_state.setdefault('analysis_mode','仅敏感性')
    st.session_state['loaded_run']=({},[NS(id='set',path='set.xml')],[case],[result])
    with patch.object(ui,'diagnostic_candidates',return_value=([case],{},[])), \
         patch.object(ui,'history_coordinates',return_value=('time',np.array([0.,1.]))), \
         patch('pyteck.respecth.analysis_cache.reusable_directory',return_value=None), \
         patch.object(ui.subprocess,'Popen',side_effect=AssertionError('Selection started an integration')):
        ui.render_analysis_page()


@pytest.mark.parametrize('kind',['pfr','jsr'])
def test_default_all_and_one_job_independent_of_display_species(tmp_path, kind):
    from pyteck.respecth.analysis_cache import payload_identity
    app=AppTest.from_function(reactor_picker_app,args=(str(tmp_path),kind),default_timeout=30).run()
    assert not app.exception
    assert app.text_input(key='analysis_reactions').value=='all'
    original=app.session_state['analysis_cache_plan']
    assert len(original)==1
    identity=payload_identity(original[0]['payload'],component='sensitivity')
    assert len(original[0]['payload']['settings']['reaction_indices'])==29
    for species in (['O2'],['H2','O2'],['H2']):
        app.multiselect(key='analysis_species_multi').set_value(species).run()
        assert not app.exception
        plan=app.session_state['analysis_cache_plan']
        assert len(plan)==1
        assert plan[0]['payload']['settings']['target_key']=='H2'
        assert payload_identity(plan[0]['payload'],component='sensitivity')==identity
    app.text_input(key='analysis_reactions').set_value('1,2').run()
    app.multiselect(key='analysis_species_multi').set_value(['H2','O2']).run()
    assert app.text_input(key='analysis_reactions').value=='1,2'
    assert app.session_state['analysis_cache_plan'][0]['payload']['settings']['reaction_indices']==[0,1]
