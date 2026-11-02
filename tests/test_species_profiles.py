from pathlib import Path
from dataclasses import replace
import json

import cantera as ct
import h5py
import numpy as np
import pytest

from pyteck.respecth.reader import load_experiment
from pyteck.respecth.cases import build_cases, prepare_mechanism
from pyteck.respecth.models import RunConfig
from pyteck.respecth.solvers import simulate_case, extract_ignition
from pyteck.respecth.gas_io import load_gas

ROOT = Path(__file__).resolve().parents[1]


def xml_profile(tmp_path, burner=False):
    kind = 'burner stabilized flame speciation measurement' if burner else 'concentration time profile measurement'
    coordinate, unit = ('distance','mm') if burner else ('time','ms')
    rows = [(0,0), (3 if burner else .1, 1e-5), (8 if burner else 1, 2e-5)]
    common = '''<property name="pressure" units="atm"><value>1</value></property>
    <property name="initial composition"><component><speciesLink preferredKey="H2"/><amount units="mole fraction">0.2</amount></component>
    <component><speciesLink preferredKey="O2"/><amount units="mole fraction">0.1</amount></component>
    <component><speciesLink preferredKey="AR"/><amount units="mole fraction">0.7</amount></component></property>'''
    common += ('<property name="mass flux" units="kg/m2/s"><value>0.05</value></property>' if burner else
               '<property name="temperature" units="K"><value>1100</value></property>')
    data = f'<dataGroup id="species"><property id="x7" name="{coordinate}" units="{unit}"/><property id="x2" name="composition" units="mole fraction"><speciesLink preferredKey="OH"/></property>'
    data += ''.join(f'<dataPoint><x7>{x}</x7><x2>{y}</x2></dataPoint>' for x,y in rows) + '</dataGroup>'
    if burner:
        data += '<dataGroup id="temperature"><property id="z" name="distance" units="mm"/><property id="T" name="temperature" units="K"/>'
        data += ''.join(f'<dataPoint><z>{z}</z><T>{T}</T></dataPoint>' for z,T in [(0,300),(1,800),(3,1600),(6,1800),(10,1800)]) + '</dataGroup>'
    text = f'<experiment><ReSpecThVersion><major>2</major><minor>6</minor></ReSpecThVersion><experimentType>{kind}</experimentType><apparatus><kind>{"burner" if burner else "shock tube"}</kind></apparatus><commonProperties>{common}</commonProperties>{data}<comment>SYNTHETIC software workflow data; not experimental measurements or mechanism validation.</comment></experiment>'
    path = tmp_path / ('burner.xml' if burner else 'time.xml')
    path.write_text(text, encoding='utf-8')
    return load_experiment(path)


def cases_for(experiment, tmp_path, solver=None):
    entry = {'id':'test','path':str(ROOT/'examples/respecth/mechanisms/h2o2.yaml'),'prepared_dir':str(tmp_path/'prepared')}
    mechanism = prepare_mechanism(entry)
    config = RunConfig(datasets=[experiment.path], mechanisms=[entry], output=str(tmp_path), grid={'enabled':False},solver=solver or {})
    cases,notes = build_cases([experiment],config,[mechanism])
    return cases,notes,config,mechanism


def test_time_profile_units_and_exact_cv_reference(tmp_path):
    experiment = xml_profile(tmp_path)
    cases,_,_,_ = cases_for(experiment,tmp_path)
    assert experiment.kind == 'profile' and not experiment.issues
    assert len(cases)==1
    assert [t['coordinate'] for t in cases[0].targets] == pytest.approx([0,1e-4,1e-3])
    assert not any(c.issues for c in cases)
    results=[]
    for case in cases:
        result=simulate_case(case,tmp_path/'simulation')
        results.append(result)
        assert result.status=='success',result.reason
        gas=load_gas(case.mechanism.path)
        gas.TPX=case.condition.temperature,case.condition.pressure,case.condition.composition
        reactor=ct.IdealGasReactor(gas,energy='on',clone=True)
        net=ct.ReactorNet([reactor]);net.rtol=1e-11;net.atol=1e-17
        for target in sorted(case.targets,key=lambda t:t['coordinate']):
            net.advance(target['coordinate'])
            assert result.predictions[target['key']] == pytest.approx(reactor.phase['OH'].X[0],rel=5e-5,abs=1e-10)
        with h5py.File(result.history_path) as history:
            assert history['time'][-1] == pytest.approx(case.condition.scan_value)
    from pyteck.respecth.reporting import render_figures
    from pyteck.respecth.evaluation import evaluate_results
    evaluation=evaluate_results([experiment],results,cases=cases)
    assert evaluation['formal']['mechanisms'][0]['coverage']==1
    paths=render_figures([experiment],{'cases':cases,'results':results},{'output':str(tmp_path/'figures'),'formats':['svg']})
    assert len(paths)==1 and 'Time (s)' in Path(paths[0]).read_text(encoding='utf-8')


def test_burner_profile_inputs_are_not_local_inlet_temperatures(tmp_path):
    experiment=xml_profile(tmp_path,burner=True)
    cases,_,_,mechanism=cases_for(experiment,tmp_path)
    assert len(cases)==1 and not any(c.issues for c in cases)
    assert all(c.kind=='burner_profile' and c.condition.temperature==300 for c in cases)
    assert cases[0].targets[1]['coordinate'] == pytest.approx(.003)
    assert cases[0].config['temperature_profile']['distance'][-1] == .01
    assert cases[0].config['burner_mass_flux']==.05
    config=RunConfig(datasets=[experiment.path],mechanisms=[],output=str(tmp_path))
    invalid,_=build_cases([experiment],config,[replace(mechanism,transport=False)])
    assert all(any('transport' in i for i in c.issues) for c in invalid)


def test_burner_missing_flow_and_temperature_extrapolation_are_blocked(tmp_path):
    experiment=xml_profile(tmp_path,burner=True)
    experiment.common_properties=[p for p in experiment.common_properties if p.name!='mass flux']
    cases,_,_,_=cases_for(experiment,tmp_path)
    assert all(any('burner_mass_flux' in i for i in c.issues) for c in cases)
    cases,_,_,_=cases_for(experiment,tmp_path,{'burner_mass_flux':.05,'burner_width':.02})
    assert all(any('no extrapolation' in i for i in c.issues) for c in cases)


def test_burner_species_prediction_and_imposed_temperature(tmp_path):
    experiment=xml_profile(tmp_path,burner=True)
    cases,_,_,_=cases_for(experiment,tmp_path)
    case=cases[0]
    result=simulate_case(case,tmp_path/'simulation')
    assert result.status=='success',result.reason
    with h5py.File(result.history_path) as history:
        z=history['grid'][:]
        expected=np.interp(z,case.config['temperature_profile']['distance'],case.config['temperature_profile']['temperature'])
        assert history['temperature'][:] == pytest.approx(expected,abs=1e-6)
        for target in case.targets:
            assert result.predictions[target['key']] == pytest.approx(np.interp(target['coordinate'],z,history['mole_fractions'][:,case.mechanism.species.index('OH')]))


def test_ignition_fallback_is_explicit_and_retains_original_definition(tmp_path):
    experiment=load_experiment(ROOT/'examples/respecth/synthetic-ignition.xml')
    experiment.ignition_type={'target':'OH*','type':'baseline min intercept from d/dt'}
    cases,notes,config,mechanism=cases_for(experiment,tmp_path)
    assert not any(c.issues for c in cases)
    assert notes and all(c.config['ignition_type']=={'target':'temperature','type':'d/dt max'} for c in cases)
    assert all(c.config['ignition_substitution']['original']==experiment.ignition_type for c in cases)
    case=next(c for c in cases if c.condition.temperature==1100)
    result=simulate_case(case,tmp_path/'simulation')
    assert result.status=='success',result.reason
    with h5py.File(result.history_path) as history:
        delay=extract_ignition(history['time'][:],history['temperature'][:],'d/dt max',case.config)
    assert next(iter(result.predictions.values())) == pytest.approx(delay)
    assert result.metadata['solver']['ignition_substitution']['original']==experiment.ignition_type
    config.solver['ignition_fallback']='none'
    strict,_=build_cases([experiment],config,[mechanism])
    assert all(any('OH*' in i or 'Unsupported ignition' in i for i in c.issues) for c in strict)


def test_valid_ignition_does_not_change_when_fallback_is_enabled(tmp_path):
    experiment=load_experiment(ROOT/'examples/respecth/synthetic-ignition.xml')
    cases,_,config,mechanism=cases_for(experiment,tmp_path)
    config.solver['ignition_fallback']='none'
    strict,_=build_cases([experiment],config,[mechanism])
    assert {c.id for c in cases}=={c.id for c in strict}
    assert not any(c.config.get('ignition_substitution') for c in cases)


def test_profile_controls_save_and_disable_fallback():
    from streamlit.testing.v1 import AppTest
    from pyteck.respecth.yaml_io import load_yaml
    app=AppTest.from_string('''
from pyteck.respecth.profile_inputs import render_profile_controls
from pyteck.respecth.yaml_io import load_yaml
import streamlit as st
st.session_state.setdefault('config_text', 'solver: {}')
st.session_state.setdefault('expand', True)
render_profile_controls(load_yaml(st.session_state['config_text']))
''',default_timeout=60).run()
    assert not app.exception and app.checkbox(key='ignition_fallback_enabled').value
    app.checkbox(key='ignition_fallback_enabled').uncheck().run()
    next(b for b in app.button if b.label=='应用点火定义设置').click().run()
    assert not app.exception
    assert load_yaml(app.session_state['config_text'])['solver']['ignition_fallback']=='none'


def test_burner_without_reactions_preserves_inlet_species(tmp_path):
    experiment=xml_profile(tmp_path,burner=True)
    gas=load_gas(ROOT/'examples/respecth/mechanisms/h2o2.yaml')
    inert=ct.Solution(thermo='ideal-gas',kinetics='gas',species=gas.species(),reactions=[],transport_model='mixture-averaged')
    path=tmp_path/'inert.yaml';path.write_text(inert.write_yaml(),encoding='utf-8')
    mechanism=prepare_mechanism({'id':'inert','path':str(path),'prepared_dir':str(tmp_path/'prepared')})
    experiment.observations[0].species='H2'
    config=RunConfig(datasets=[experiment.path],mechanisms=[],output=str(tmp_path))
    cases,_=build_cases([experiment],config,[mechanism])
    result=simulate_case(cases[0],tmp_path/'simulation')
    assert result.status=='success',result.reason
    assert next(iter(result.predictions.values()))==pytest.approx(.2,abs=1e-8)


@pytest.mark.parametrize('burner',[False,True])
def test_profile_shares_species_grids_instruments_and_dense_points(tmp_path,monkeypatch,burner):
    experiment=xml_profile(tmp_path,burner=burner)
    path=Path(experiment.path)
    coordinate,units=('distance','mm') if burner else ('time','ms')
    extra=f'''<dataGroup id="second"><property id="x" name="{coordinate}" units="{units}"/>
    <property id="OH2" name="composition" units="ppm"><speciesLink preferredKey="OH"/></property>
    <property id="H2" name="composition" units="percent"><speciesLink preferredKey="H2"/></property>'''
    # A second instrument/series, different grid, reversed order, repeated observations.
    locations=[7,2,2] if burner else [.8,.2,.2]
    extra+=''.join(f'<dataPoint><x>{x}</x><OH2>1</OH2><H2>20</H2></dataPoint>' for x in locations)+'</dataGroup>'
    path.write_text(path.read_text(encoding='utf-8').replace('<comment>',extra+'<comment>'),encoding='utf-8')
    experiment=load_experiment(path)
    _,_,config,mechanism=cases_for(experiment,tmp_path)
    config.grid={'enabled':True,'points':7}
    cases,_=build_cases([experiment],config,[mechanism])
    assert len(cases)==1 and not cases[0].issues
    case=cases[0]
    assert any(t.get('role')=='plotting' for t in case.targets)
    assert any(len(t['point_indices'])==2 for t in case.targets)
    from pyteck.respecth.solvers import SOLVERS
    cls=SOLVERS[case.kind];original=cls.solve;calls=[]
    def solve(self):
        calls.append(self.config['rtol'])
        return original(self)
    monkeypatch.setattr(cls,'solve',solve)
    result=simulate_case(case,tmp_path/'simulation')
    assert result.status=='success',result.reason
    assert len(calls)==(1 if burner else 2) # second CV integration is tolerance validation only
    from pyteck.respecth.evaluation import evaluate_results
    from pyteck.respecth.coverage import dataset_coverage
    from pyteck.respecth.reporting import render_figures
    rows=evaluate_results([experiment],[result],cases=cases)['rows']
    scored=[r for r in rows if r['role']=='scoring']
    assert len(scored)==9 and all(r['predicted'] is not None for r in rows)
    assert [r['scan_value'] for r in scored if r['property_id']=='OH2']==pytest.approx(np.array(locations)*.001)
    assert dataset_coverage([experiment],cases,[result])[0]['覆盖率']==1
    with h5py.File(result.history_path) as history:
        axis='grid' if burner else 'time'
        for target in case.targets:
            field='concentrations' if target['units'] in {'mol/m3','mol/cm3'} else 'mole_fractions'
            expected=np.interp(target['coordinate'],history[axis][:],history[field][:,mechanism.species.index(target['species'])])
            assert result.predictions[target['key']]==pytest.approx(expected)
    from pyteck.respecth.analysis_ui import diagnostic_candidates
    views,_,_=diagnostic_candidates([experiment],cases,[result])
    assert {v.condition.scan_value for v in views}=={t['coordinate'] for t in case.targets if t['role']=='scoring'}
    assert all(v.targets[0]['coordinate']==v.condition.scan_value for v in views)
    from pyteck.respecth.compact_storage import retain_plot_result
    retain_plot_result(result)
    paths=render_figures([experiment],{'cases':cases,'results':[result]},
                         {'output':str(tmp_path/'figures'),'formats':['svg']})
    assert paths and all(Path(p).is_file() for p in paths)
    assert dataset_coverage([experiment],cases,[result])[0]['覆盖率']==1


def test_different_initial_states_are_separate_profile_solves(tmp_path):
    experiment=xml_profile(tmp_path)
    group=experiment.groups[0]
    group.conditions[-1]=replace(group.conditions[-1],temperature=1200)
    cases,_,_,_=cases_for(experiment,tmp_path)
    assert len(cases)==2
    assert sorted(len(c.targets) for c in cases)==[1,2]


def test_native_profile_sensitivity_uses_selected_time(tmp_path):
    experiment=xml_profile(tmp_path)
    cases,_,_,_=cases_for(experiment,tmp_path)
    case=cases[0];target=case.targets[1]
    result=simulate_case(case,tmp_path/'simulation')
    assert result.status=='success',result.reason
    from pyteck.respecth.analysis import compute_sensitivity
    analysis=compute_sensitivity(case,result,target['key'],[10],tmp_path/'sensitivity',isolated=False)
    assert analysis['baseline']==pytest.approx(result.predictions[target['key']],rel=.01)
    with h5py.File(analysis['all_species_path']) as matrix:
        assert matrix.attrs['time']==pytest.approx(target['coordinate'])


def profile_analysis_app(payload_path):
    import json
    from pathlib import Path
    import streamlit as st
    from pyteck.respecth.models import case_from_dict,result_from_dict
    from pyteck.respecth.reader import load_experiment
    from pyteck.respecth.analysis_ui import render_analysis_page
    data=json.loads(Path(payload_path).read_text(encoding='utf-8'))
    st.session_state['loaded_run']=({},[load_experiment(data['xml'])],
        [case_from_dict(data['case'])],[result_from_dict(data['result'])])
    render_analysis_page()


def test_profile_analysis_gui_keeps_time_selection_after_grouping(tmp_path):
    from dataclasses import asdict
    from streamlit.testing.v1 import AppTest
    experiment=xml_profile(tmp_path)
    cases,_,_,_=cases_for(experiment,tmp_path)
    case=cases[0];result=simulate_case(case,tmp_path/'simulation')
    assert result.status=='success',result.reason
    from pyteck.respecth.compact_storage import retain_plot_result
    retain_plot_result(result)
    payload=tmp_path/'payload.json'
    payload.write_text(json.dumps({'xml':experiment.path,'case':asdict(case),'result':asdict(result)}),encoding='utf-8')
    app=AppTest.from_function(profile_analysis_app,args=(str(payload),),default_timeout=60).run()
    assert not app.exception
    app.multiselect(key='analysis_values_multi').set_value([1e-4]).run()
    assert not app.exception
    plan=app.session_state['analysis_cache_plan']
    assert len(plan)==1
    selected=plan[0]['payload']
    assert selected['case']['config']['analysis_coordinate']==pytest.approx(1e-4)
    target=next(t for t in selected['case']['targets'] if t['key']==selected['settings']['target_key'])
    assert target['coordinate']==pytest.approx(1e-4)
    app.radio(key='analysis_mode').set_value('仅 ROP').run()
    assert not app.exception
    assert app.session_state['analysis_cache_plan'][0]['payload']['case']['config']['analysis_coordinate']==pytest.approx(1e-4)
