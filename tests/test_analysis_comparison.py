from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import matplotlib.pyplot as plt
import pytest
from pyteck.respecth.analysis_comparison import comparison_series, comparison_figure


def report(sha='mech-one',case_id='case1',temperature=950.):
    return {'status':'completed','case':{'id':case_id,'experiment_id':'source-Set1','group_id':'dg1','kind':'pfr',
        'mechanism':{'id':'mech','sha256':sha},'condition':{'temperature':temperature,'pressure':101325.},
        'targets':[{'key':'oh','species':'OH','quantity':'composition'}]},'settings':{},
        'sensitivity':{'target_key':'oh','baseline':1.,'zero_floor':1e-20,'reaction_indices':[0,1],
            'rows':[{'reaction_number':1,'equation':'A => B','status':'success','coefficient':.5,'derivative':.5},
                    {'reaction_number':2,'equation':'B => C','status':'success','coefficient':-.8,'derivative':-.8}]}}


def test_same_mechanism_grouped_bars_preserve_signs_and_missing():
    first=report();second=report(case_id='case2',temperature=650.)
    second['sensitivity']['rows']=second['sensitivity']['rows'][:1]
    series,omitted=comparison_series([('a.json',first),('b.json',second)],'sensitivity',['OH'])
    figure,rows=comparison_figure(series)
    assert len(figure.axes)==1
    assert len(figure.axes[0].patches)==3
    assert {r['case_id'] for r in rows}=={'case1','case2'}
    missing=[r for r in rows if r['status']=='not_saved']
    assert len(missing)==1 and missing[0]['value'] is None
    assert any(p.get_width()<0 for p in figure.axes[0].patches)
    assert len(figure.axes[0].get_legend().texts)==2
    plt.close(figure)


def test_different_mechanisms_separate_and_same_identity_equation_conflict():
    first=report();second=report(sha='mech-two',case_id='case2')
    second['sensitivity']['rows'][0]['equation']='C => D'
    series,_=comparison_series([('a',first),('b',second)],'sensitivity',['OH'])
    figure,_=comparison_figure(series);assert len(figure.axes)==2;plt.close(figure)
    second['case']['mechanism']['sha256']='mech-one'
    series,_=comparison_series([('a',first),('b',second)],'sensitivity',['OH'])
    with pytest.raises(ValueError,match='冲突'): comparison_figure(series)


def test_near_zero_uses_absolute_derivatives_for_entire_panel():
    first=report();second=report(case_id='case2');second['sensitivity']['baseline']=0.
    for row in second['sensitivity']['rows']:row['coefficient']=None
    series,_=comparison_series([('a',first),('b',second)],'sensitivity',['OH'])
    figure,rows=comparison_figure(series)
    assert all(r['metric']=='derivative' for r in rows)
    assert 'observable SI unit' in figure.axes[0].get_xlabel()
    plt.close(figure)


def test_rop_aggregation_species_and_units_stay_separate():
    first=report();second=report(case_id='case2')
    for r in [first,second]:
        r['rop']={'species':'OH','aggregation':'domain_integral','rate_unit':'mol/m3',
            'rows':[{'reaction_number':1,'equation':'A => B','formation':.5,'destruction':.8,'net':-.3}]}
    second['rop'].update(aggregation='local_state',rate_unit='mol/m3/s')
    series,omitted=comparison_series([('a',first),('b',second)],'rop',['OH','NO'],rop_metric='destruction')
    assert len(omitted)==2
    figure,rows=comparison_figure(series)
    assert len(figure.axes)==2
    assert all(r['value']==-.8 for r in rows)
    assert {r['unit'] for r in rows}=={'mol/m3','mol/m3/s'}
    plt.close(figure)

def combined_app(directories):
    from pyteck.respecth.analysis_comparison_ui import render_combined_analysis
    render_combined_analysis(directories)


def test_combined_view_multiselect_stays_on_existing_page_without_solves(tmp_path):
    from streamlit.testing.v1 import AppTest
    directories=[]
    for index in range(2):
        data=report(sha=f'mech{index}',case_id=f'case{index}')
        if index: data['case']['targets'][0]['species']='NO'
        directory=tmp_path/str(index);directory.mkdir()
        (directory/'report.json').write_text(json.dumps(data),encoding='utf-8')
        directories.append(str(directory))
    at=AppTest.from_function(combined_app,args=(directories,),default_timeout=30).run()
    assert not at.exception and len(at.image)==1
    at.multiselect[0].set_value(['OH','NO']).run()
    assert not at.exception and len(at.image)==1
    assert len(at.warning)==2  # Missing saved species disclosed for each mechanism.
    assert len(at.dataframe[0].value['case_id'].unique())==2
    assert not list(tmp_path.rglob('comparison.png'))
    assert not plt.get_fignums()
