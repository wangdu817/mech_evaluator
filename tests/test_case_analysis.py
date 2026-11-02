from pathlib import Path
import json
import math
import cantera as ct
import h5py
import numpy as np
import pytest

from pyteck.respecth.analysis import (reaction_contributions,compute_rop,
    compute_sensitivity,sensitivity_coefficients,history_coordinates)
from pyteck.respecth.models import Condition,SimulationCase,DEFAULT_SOLVER
from pyteck.respecth.cases import prepare_mechanism
from pyteck.respecth.solvers import simulate_case,Cancelled


@pytest.fixture()
def first_order(tmp_path):
    species={s.name:s for s in ct.Species.list_from_file('h2o2.yaml')}
    reaction=ct.Reaction({'H2':1},{'H':2},ct.ArrheniusRate(10.,0,0))
    reaction.reversible=False
    gas=ct.Solution(thermo='ideal-gas',kinetics='gas',species=[species['H2'],species['H']],reactions=[reaction])
    source=tmp_path/'simple.yaml';source.write_text(gas.write_yaml(),encoding='utf-8')
    mechanism=prepare_mechanism({'id':'first-order','path':str(source),'prepared_dir':str(tmp_path/'prepared')})
    condition=Condition(scan_name='temperature',scan_value=1000.,temperature=1000.,pressure=101325.,composition={'H2':1.},residence_time=.05)
    case=SimulationCase('first-order-case','synthetic','dg1',[0],'pfr',condition,mechanism,
        {**DEFAULT_SOLVER,'concentration_basis':'wet'},[{'key':'h','quantity':'composition','species':'H','units':'mole fraction'}])
    result=simulate_case(case,tmp_path/'base')
    assert result.status=='success',result.reason
    return case,result,tmp_path


def test_analytic_pfr_observable_sensitivity_and_clone_multiplier(first_order):
    case,result,directory=first_order
    output=compute_sensitivity(case,result,'h',[0],directory,isolated=False)
    row=output['rows'][0]
    a=10*case.condition.residence_time;e=math.exp(-a)
    expected=a*e/((1-e)*(2-e))
    assert row['status']=='success'
    assert row['coefficient']==pytest.approx(expected,rel=1e-5)
    assert output['planned_perturbed_solves']==0
    assert output['native_solves']==1
    from pyteck.respecth.native_analysis import species_sensitivity_view
    default=ct.ReactorNet([])
    assert output['validation']['rtol']==default.rtol
    assert output['validation']['rtol_sensitivity']==default.rtol_sensitivity
    assert output['tolerance_verification'] is False
    saved=output['all_species_path']
    with h5py.File(saved,'r') as stream:
        assert stream['X/derivative'].shape==(2,1)
        np.testing.assert_allclose(stream['X/derivative'][:].sum(axis=0),0,atol=1e-12)
    hydrogen=species_sensitivity_view(saved,'H')
    assert hydrogen['rows'][0]['coefficient']==pytest.approx(row['coefficient'])
    # Switching to another species reads the existing matrix only.
    fuel=species_sensitivity_view(saved,'H2')
    assert fuel['rows'][0]['coefficient']<0
    assert Path(saved).is_file()
    assert not list(directory.glob('.history-*.tmp'))


def test_rop_species_index_zero_and_gross_cantera_balance():
    gas=ct.Solution('h2o2.yaml');gas.TPX=1400,ct.one_atm,'H2:2,O2:1,H:0.002,OH:0.001,H2O:0.1'
    production,destruction,net,error=reaction_contributions(gas,gas.species_names[0])
    assert sum(production)==pytest.approx(gas.creation_rates[0]*1000,rel=1e-12)
    assert sum(destruction)==pytest.approx(gas.destruction_rates[0]*1000,rel=1e-12)
    np.testing.assert_allclose(production-destruction,net,rtol=1e-12,atol=1e-8)
    assert error<1e-5


def test_rop_original_state_profile_and_invalid_history(first_order):
    case,result,_=first_order
    output=compute_rop(case,result,'H',100,top_n=1,profile_points=20)
    assert len(output['rows'])==1 and len(output['profile'])<=21
    assert output['row']==100 and output['coordinate_kind']=='time'
    assert output['totals']['formation']>0 and output['totals']['destruction']==0
    assert output['aggregation']=='domain_integral'
    assert output['rate_unit']=='mol/m3'
    initial=101325/(ct.gas_constant*1000)*1000
    expected=2*initial*math.log(2-math.exp(-.5))
    assert output['totals']['formation']==pytest.approx(expected,rel=1e-4)
    assert output['quadrature']['volume_weighted_net_per_inlet_volume']==pytest.approx(2*initial*(1-math.exp(-.5)),rel=1e-4)
    assert output['quadrature']['passed']
    assert compute_rop(case,result,'H',0)['totals']==pytest.approx(output['totals'])
    with h5py.File(result.history_path,'r+') as history: history.attrs['complete']=False
    with pytest.raises(ValueError,match='incomplete'): history_coordinates(case,result)


def test_zero_target_and_step_instability():
    result=sensitivity_coefficients(1e-25,-1e-25,5e-26,-5e-26,0,.01)
    assert result['coefficient'] is None and result['derivative']>0
    result=sensitivity_coefficients(2.,1.,5.,1.,1.,.01)
    assert not result['step_check_passed']


def test_cancel_preserves_cached_history(first_order):
    case,result,directory=first_order
    before=Path(result.history_path).read_bytes()
    cancel=directory/'CANCEL';cancel.touch()
    with pytest.raises(Cancelled): compute_rop(case,result,'H',0,cancel_file=cancel)
    assert before==Path(result.history_path).read_bytes()


def test_native_jsr_steady_sensitivity(first_order):
    case,_,directory=first_order
    case.kind='jsr';case.id='first-order-jsr'
    case.condition.volume=1e-6
    result=simulate_case(case,directory/'jsr')
    assert result.status=='success',result.reason
    output=compute_sensitivity(case,result,'h',[0],directory,isolated=False)
    assert output['rows'][0]['status']=='success'
    assert output['rows'][0]['coefficient']==pytest.approx(1/(1+2*.5),rel=1e-4)
    assert output['validation']['steady_check']['passed']


def test_native_concentration_chain_rule(first_order):
    case,_,directory=first_order
    case.id='first-order-concentration'
    case.targets[0]['units']='mol/m3'
    result=simulate_case(case,directory/'concentration')
    output=compute_sensitivity(case,result,'h',[0],directory,isolated=False)
    a=.5;e=math.exp(-a)
    assert output['rows'][0]['coefficient']==pytest.approx(a*e/((1-e)*(2-e)),rel=1e-5)


def test_actual_temperature_sensitivity_against_independent_difference():
    root=Path(__file__).resolve().parents[1]
    path=root/'results/case-analysis-actual-validation.json'
    if not path.exists(): pytest.skip('Actual validation artifacts unavailable')
    from pyteck.respecth.models import case_from_dict
    from pyteck.respecth.gas_io import load_gas
    record=next(r for r in json.loads(path.read_text(encoding='utf-8')) if r['kind']=='ignition')
    # Frozen diagnostic payload remains valid while the user's batch is running.
    payload=json.loads((Path(record['directory'])/'job.json').read_text(encoding='utf-8'))
    case=case_from_dict(payload['case'])
    target=record['sensitivity'];index=target['reaction_indices'][0]
    values=[];step=1e-4
    for h in (step,-step):
        gas=load_gas(case.mechanism.path,case.mechanism.phase)
        gas.TPX=case.condition.temperature,case.condition.pressure,{case.mechanism.species_map.get(s,s):v for s,v in case.condition.composition.items()}
        reactor=ct.IdealGasReactor(gas,energy='on',clone=True)
        reactor.phase.set_multiplier(math.exp(h),index)
        net=ct.ReactorNet([reactor]);net.rtol=1e-11;net.atol=1e-17;net.max_steps=100000
        net.advance(target['reference_time'])
        values.append(reactor.T)
    independent=(values[0]-values[1])/(2*step*target['baseline'])
    assert target['rows'][0]['coefficient']==pytest.approx(independent,rel=.01,abs=1e-5)


def test_diagnostic_table_uses_the_displayed_units():
    from pyteck.respecth.analysis_ui import measurement_display
    row={'species':None,'quantity':'ignition delay','instrument':None,'units':'us','status':'success',
         'concentration_basis':'wet','experimental':.0008,'predicted':.0005,'residual':-.0003}
    displayed=measurement_display([row])[0]
    assert displayed['experimental']==pytest.approx(800)
    assert displayed['predicted']==pytest.approx(500)
    assert displayed['residual']==pytest.approx(-300)
    assert row['experimental']==.0008
