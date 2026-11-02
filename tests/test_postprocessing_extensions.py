from pathlib import Path
from types import SimpleNamespace as NS
import json
import pytest
import cantera as ct
from pyteck.respecth.inlet_properties import inlet_equivalence_ratio


def test_phi_matches_installed_cantera_element_definition():
    gas=ct.Solution('gri30.yaml')
    for feed in ({'CH4':1,'O2':2,'N2':7.52}, {'CH4':.4,'H2':.6,'O2':1.1,'N2':4.,'H2O':.2,'NO':.1}):
        gas.TPX=300,101325,feed
        assert inlet_equivalence_ratio(NS(composition=feed))==pytest.approx(gas.equivalence_ratio())
    assert inlet_equivalence_ratio(NS(composition={'CH3NH2':.00026,'O2':.04,'N2':.95974}))==pytest.approx(.00026*2.25/.04)
    with pytest.raises(ValueError): inlet_equivalence_ratio(NS(composition={'CH3NH2':.01,'N2':.99}))


def test_actual_macro_subplots_and_conditions(tmp_path):
    from pyteck.respecth.reader import load_experiment
    from pyteck.respecth.reporting import render_figures
    root=Path(__file__).resolve().parents[1]
    paths=sorted((root.parent/'exp4').glob('*.xml'))[:2]
    if len(paths)<2: pytest.skip('Local actual XML unavailable')
    experiments=[load_experiment(p) for p in paths]
    output=tmp_path/'figures'
    render_figures(experiments,{'cases':[],'results':[]},{'output':str(output),'macro_layout':'subplots','columns':2})
    records=json.loads((output/'figure_sources.json').read_text())
    # Metadata format is the renderer's public export.
    if isinstance(records,dict): records=records.get('figures',records.get('sources',[]))
    assert len(records)==1
    assert records[0]['macro_layout']=='subplots' and len(records[0]['panels'])==2
    assert all('φ =' in text for text in records[0]['conditions'])


def ignition_picker_app(directory):
    import streamlit as st
    import numpy as np
    from pathlib import Path
    from types import SimpleNamespace as NS
    from unittest.mock import patch
    from pyteck.respecth import analysis_ui as ui
    from pyteck.respecth.models import Condition,SimulationCase,Mechanism,CaseResult
    from pyteck.respecth.cases import prepare_mechanism
    import cantera as ct
    source=Path(directory)/'gas.yaml'
    if not source.exists(): source.write_text(ct.Solution('h2o2.yaml').write_yaml())
    mechanism=prepare_mechanism({'id':'h2','path':str(source),'prepared_dir':str(Path(directory)/'prepared')})
    history=Path(directory)/'history.h5';history.write_bytes(b'test-history')
    case=SimulationCase('ignition-ui','set','dg1',[0],'ignition',Condition('temperature',1100.,1100.,101325.,{'H2':2.,'O2':1.}),mechanism,
        {'time_end':.01},[{'key':'tau','quantity':'ignition delay','species':None,'units':'s'}])
    result=CaseResult(case.id,'success',{'tau':.001},history_path=str(history),validation={'passed':True})
    st.session_state.setdefault('analysis_mode','仅敏感性')
    st.session_state.setdefault('analysis_reactions','1')
    st.session_state['loaded_run']=({},[NS(id='set',path='mix.xml')],[case],[result])
    with patch.object(ui,'diagnostic_candidates',return_value=([case],{},[])), \
         patch.object(ui,'history_coordinates',return_value=('time',np.array([0.,.001,.01]))):
        ui.render_analysis_page()


def test_ignition_temperature_entry_does_not_require_species(tmp_path):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_function(ignition_picker_app,args=(str(tmp_path),),default_timeout=30).run()
    assert not app.exception
    assert not any(w.key=='analysis_species_multi' for w in app.multiselect)
    assert app.number_input(key='analysis_time').value==pytest.approx(.001)
    assert not next(b for b in app.button if b.label=='分析选中工况').disabled
    payload=app.session_state['analysis_cache_plan'][0]['payload']
    assert payload['settings']['target_key']=='temperature_at_fixed_time'
    assert payload['settings']['reference_time']==pytest.approx(.001)
