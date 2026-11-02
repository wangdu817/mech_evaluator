import json
import h5py
import numpy as np
import matplotlib.pyplot as plt
from streamlit.testing.v1 import AppTest
from pyteck.respecth.analysis_plotting import sensitivity_figure


def report_data():
    return {'status':'completed','case':{'id':'saved-case','mechanism':{'id':'actual-mechanism'},
        'condition':{'temperature':950.,'pressure':101325.}},'settings':{'top_n':2},
        'sensitivity':{'baseline':1.,'zero_floor':1e-20,'target_key':'OH','quantity':'X',
            'method':'saved matrix','reaction_indices':[0,1,2], 'rows':[
            {'reaction_number':i+1,'equation':f'R{i+1} equation','status':'success',
             'coefficient':v,'derivative':v} for i,v in enumerate([.1,-.8,.4])]}}


def test_signed_ranking_and_near_zero_absolute_derivatives():
    report=report_data()
    figure=sensitivity_figure(report)
    axis=figure.axes[0]
    np.testing.assert_allclose([p.get_width() for p in axis.patches],[.4,-.8])
    assert [t.get_text() for t in axis.get_yticklabels()]==['R3  R3 equation','R2  R2 equation']
    assert 'dimensionless' in axis.get_xlabel()
    plt.close(figure)
    report['sensitivity']['baseline']=0.
    for row in report['sensitivity']['rows']: row['coefficient']=None
    figure=sensitivity_figure(report)
    assert 'observable SI unit' in figure.axes[0].get_xlabel()
    plt.close(figure)
    for row in report['sensitivity']['rows']: row['status']='solver_failed'
    assert sensitivity_figure(report) is None


def saved_analysis_app(directory):
    import streamlit as st
    from pyteck.respecth.analysis_ui import _analysis_progress
    st.session_state['analysis_directory']=directory
    _analysis_progress()


def test_saved_all_species_plot_appears_without_export_and_switches(tmp_path):
    report=report_data()
    path=tmp_path/'all_species_sensitivity.h5'
    with h5py.File(path,'w') as stream:
        stream['species']=np.array(['A','B'],dtype=h5py.string_dtype())
        stream['equations']=np.array(['A => B','B => A','A + B => B'],dtype=h5py.string_dtype())
        stream['reaction_indices']=[0,1,2]
        for quantity in ['X','Y','C']:
            stream[quantity+'/baseline']=[.4,.6]
            stream[quantity+'/derivative']=[[.1,-.2,.3],[-.1,.2,-.3]]
    report['sensitivity']['all_species_path']=str(path)
    (tmp_path/'report.json').write_text(json.dumps(report),encoding='utf-8')
    at=AppTest.from_function(saved_analysis_app,args=(str(tmp_path),),default_timeout=30).run()
    assert not at.exception
    assert len(at.image)==1
    assert not (tmp_path/'views').exists()  # Preview does not export or run a solver.
    at.multiselect[0].set_value(['B']).run()
    assert not at.exception
    assert len(at.image)==1
    at.number_input[0].set_value(1).run()
    assert not at.exception
    assert len(at.image)==1
    assert not (tmp_path/'views').exists()
    assert not plt.get_fignums()
