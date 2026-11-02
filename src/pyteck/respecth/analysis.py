"""Read-only single-case kinetics diagnostics, separate from batch evaluation."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import copy
import gc
import hashlib
import json
import math
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

import cantera as ct
import h5py
import numpy as np
import psutil

from .atomic_io import atomic_json
from .gas_io import load_gas
from .models import case_from_dict, digest, file_hash
from .solvers import SOLVERS, Cancelled
from .history_io import DiskHistory


def history_coordinates(case, result):
    """Small scalar vector only; never load the entire species matrix."""
    if result.case_id != case.id or result.status != 'success' or not result.validation.get('passed'):
        raise ValueError('Analysis requires a matching, numerically verified successful result')
    with h5py.File(result.history_path, 'r') as history:
        if history.attrs['case_id'] != case.id or not history.attrs.get('complete', True):
            raise ValueError('History is incomplete or belongs to a different case')
        if json.loads(history.attrs['species_names']) != case.mechanism.species:
            raise ValueError('History species order differs from the selected mechanism')
        key = 'grid' if case.kind in {'flame', 'burner_profile'} else 'time'
        return key, np.asarray(history[key])


def reaction_contributions(gas, species):
    """Gross formation/destruction include forward and reverse chemistry."""
    index = gas.species_index(species)
    reactants = np.asarray(gas.reactant_stoich_coeffs[index, :]).ravel()
    products = np.asarray(gas.product_stoich_coeffs[index, :]).ravel()
    forward, reverse = gas.forward_rates_of_progress, gas.reverse_rates_of_progress
    formation = (products*forward + reactants*reverse)*1000
    destruction = (reactants*forward + products*reverse)*1000
    net = (products-reactants)*(forward-reverse)*1000
    # Scale the balance check by gross flux, since near-equilibrium net flux cancels.
    scale = max(float(np.sum(formation+destruction)), 1e-30)
    error = abs(float(np.sum(net))-float(gas.net_production_rates[index]*1000))
    if error > scale*1e-10:
        raise ValueError('ROP reaction sum does not reproduce Cantera species production')
    return formation, destruction, net, error


def compute_rop(case, result, species, row, top_n=15, profile_points=200, cancel_file=None, *, _refinement=0):
    key, coordinate = history_coordinates(case, result)
    if not 0 <= row < len(coordinate):
        raise ValueError('Selected history row is outside the stored trajectory')
    if case.kind=='pfr' and (len(coordinate)<2 or np.any(np.diff(coordinate)<=0)
            or abs(coordinate[0])>1e-12 or not math.isclose(coordinate[-1],case.condition.residence_time,rel_tol=1e-8,abs_tol=1e-12)):
        raise ValueError('PFR integration requires the complete inlet-to-outlet time domain')
    gas = load_gas(case.mechanism.path, case.mechanism.phase)
    mapped = case.mechanism.species_map.get(species, species)
    def state(history, index):
        gas.TPY = float(history['temperature'][index]), float(history['pressure'][index]), history['mass_fractions'][index]
    with h5py.File(result.history_path, 'r') as history:
        state(history, row)
        formation, destruction, net, error = reaction_contributions(gas, mapped)
        quadrature = None
        if case.kind == 'pfr':
            # Integrate ALL stored states, not the reduced plotting profile.
            # Only two rate vectors are held at a time, regardless of trajectory length.
            totals = np.zeros((3, gas.n_reactions))
            coarse = np.zeros_like(totals)
            previous = coarse_previous = None
            coarse_time = float(coordinate[0])
            balance_integral = 0.
            inlet_volume = float(history['volume'][0])
            volume_weighted_net = 0.
            previous_weighted = previous_balance = 0.
            for index, current_time in enumerate(coordinate):
                from .native_analysis import guard
                guard(cancel_file)
                state(history, index)
                f, d, n, current_error = reaction_contributions(gas, mapped)
                rates = np.asarray([f, d, n])
                balance = float(gas.net_production_rates[gas.species_index(mapped)]*1000)
                weighted = balance * float(history['volume'][index]) / inlet_volume
                error = max(error, current_error)
                if previous is not None:
                    dt = float(current_time-coordinate[index-1])
                    totals += .5*(previous+rates)*dt
                    balance_integral += .5*(previous_balance+balance)*dt
                    volume_weighted_net += .5*(previous_weighted+weighted)*dt
                if index == 0:
                    coarse_previous = rates.copy()
                elif index % 2 == 0 or index == len(coordinate)-1:
                    coarse += .5*(coarse_previous+rates)*float(current_time-coarse_time)
                    coarse_previous, coarse_time = rates.copy(), float(current_time)
                previous, previous_balance, previous_weighted = rates, balance, weighted
            formation, destruction, net = totals
            scale = max(float(np.sum(formation+destruction)), 1e-30)
            difference = float(np.max(np.abs(totals-coarse)))
            quadrature = {'method': 'trapezoid on every stored time row', 'rows': len(coordinate),
                'interval': [float(coordinate[0]), float(coordinate[-1])],
                'coarsened_absolute_difference': difference,
                'passed': difference <= max(scale*.01, 1e-12),
                'reaction_balance_absolute_error': abs(float(sum(net))-balance_integral),
                'volume_weighted_net_per_inlet_volume': volume_weighted_net}
        equations = gas.reaction_equations()
        order = np.argsort(-(formation+destruction), kind='stable')
        ranked = [int(i) for i in order if formation[i]+destruction[i] > 0]
        selected = ranked[:top_n]
        total_formation, total_destruction = float(sum(formation)), float(sum(destruction))
        rows = [{'reaction_index':i, 'reaction_number':i+1, 'equation':equations[i],
                 'formation':float(formation[i]), 'destruction':float(destruction[i]), 'net':float(net[i]),
                 'formation_fraction':float(formation[i]/total_formation) if total_formation else None,
                 'destruction_fraction':float(destruction[i]/total_destruction) if total_destruction else None}
                for i in ranked]
        profile = []
        # Raw stored states sampled for display only; no interpolated composition.
        sample_indices = sorted(set(np.linspace(0, len(coordinate)-1, min(profile_points, len(coordinate)), dtype=int)) | {row})
        for index in sample_indices:
            if cancel_file and Path(cancel_file).exists():
                raise Cancelled('Analysis cancellation requested')
            state(history, index)
            _, _, current, _ = reaction_contributions(gas, mapped)
            profile.append({'row':int(index), 'coordinate':float(coordinate[index]),
                            'net':[float(current[i]) for i in selected]})
        state(history, row)
        snapshot = {'temperature':float(gas.T), 'pressure':float(gas.P), 'coordinate':float(coordinate[row])}
    if quadrature and not quadrature['passed'] and _refinement<2:
        # Saved output grids can miss sharp entrance chemistry. Reintegrate the
        # same physical case locally with denser output, never overwrite cache.
        import tempfile
        from .runner import project_root
        from .solvers import simulate_case
        local=case_from_dict(copy.deepcopy(asdict(case)))
        intervals=max(len(coordinate)-1,case.config.get('history_min_intervals',100))*10
        local.config.update(history_min_intervals=intervals,verify=True)
        base=project_root()/'results/analysis'
        base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rop-integration-',dir=base) as directory:
            refined=simulate_case(local,directory,cancel_file)
            if refined.status=='cancelled':
                raise Cancelled(refined.reason)
            if refined.status!='success':
                raise ValueError('PFR integral refinement failed: '+refined.reason)
            with h5py.File(refined.history_path,'r') as history:
                for target in case.targets:
                    baseline=result.predictions.get(target['key'])
                    value=refined.predictions.get(target['key'])
                    if baseline is not None and value is not None and abs(value-baseline)>max(abs(baseline)*.01,case.config.get('validation_absolute',1e-10)):
                        raise ValueError('PFR integration refinement changed the cached outlet observable')
                final_row=len(history['time'])-1
            output=compute_rop(local,refined,species,final_row,top_n,profile_points,cancel_file,_refinement=_refinement+1)
        output['quadrature'].setdefault('refinement',[]).insert(0,{'source_rows':len(coordinate),'refined_intervals':intervals,'source_difference':quadrature['coarsened_absolute_difference']})
        output['quadrature']['original_history_unchanged']=True
        return output
    return {'species':species, 'mechanism_species':mapped, 'row':row, 'coordinate_kind':key,
            'rate_unit':'mol/m3' if case.kind == 'pfr' else 'mol/m3/s', 'snapshot':snapshot, 'rows':rows, 'profile':profile,
            'aggregation':'domain_integral' if case.kind == 'pfr' else 'local_state', 'quadrature':quadrature,
            'profile_rate_unit':'mol/m3/s',
            'profile_reaction_indices':selected, 'profile_sampling':'up to 200 original stored states; selected row included',
            'totals':{'formation':total_formation, 'destruction':total_destruction, 'net':float(sum(net))},
            'balance_absolute_error':error,
            'interpretation':'Chemical source only; JSR inlet/outlet transport is excluded. ROP rank is not sensitivity rank.'}


def _solve_observable(case, target_key, workdir, reaction_index=None, multiplier=1., cancel_file=None):
    """Reuse the exact physical solver; apply multipliers AFTER reactor cloning."""
    local = case_from_dict(copy.deepcopy(asdict(case)))
    local.config = {**local.config, 'rtol':local.config['rtol']/10,
                    'atol':local.config['atol']/10, '_cancel_file':str(cancel_file or '')}
    base_class = SOLVERS[local.kind]
    class Perturbed(base_class):
        def check_cancel(self, *args):
            now = time.monotonic()
            if now-getattr(self,'last_memory_check',0)>1:
                self.last_memory_check=now
                if psutil.virtual_memory().available < 1024**3:
                    if cancel_file: Path(cancel_file).touch()
                    raise Cancelled('Memory guard: system available memory below 1 GiB')
            return super().check_cancel(*args)
        def reactor_class(self, constant_pressure=False):
            constructor = super().reactor_class(constant_pressure)
            def create(*args, **kwargs):
                reactor = constructor(*args, **kwargs)
                if reaction_index is not None:
                    reactor.phase.set_multiplier(multiplier, reaction_index)
                return reactor
            return create
    solver = Perturbed(local)
    try:
        solver.setup_case(path=str(workdir))
        if local.kind == 'flame' and reaction_index is not None:
            solver.gas.set_multiplier(multiplier, reaction_index)
        solver.run_case()
        if local.kind == 'flame' and not solver.extra.get('verification_passed'):
            raise ValueError('Perturbed flame did not pass grid/domain verification')
        value = solver.process_results()[target_key]
        if not math.isfinite(value):
            raise ValueError('Perturbed observable is not finite')
        return float(value)
    finally:
        if isinstance(getattr(solver, 'history', None), DiskHistory):
            solver.history.close()
        del solver
        gc.collect()


def sensitivity_coefficients(plus, minus, half_plus, half_minus, baseline, delta, floor=1e-20):
    """Derivative w.r.t. ln(rate multiplier); no normalization at zero."""
    coarse = (plus-minus)/(2*delta)
    derivative = (half_plus-half_minus)/delta
    denominator = baseline if abs(baseline) > floor else None
    coarse_s = coarse/denominator if denominator else None
    coefficient = derivative/denominator if denominator else None
    # Step convergence: 5% relative or 0.01 absolute normalized sensitivity.
    scale = max(abs(coarse), abs(derivative), floor)
    absolute_allowance = abs(baseline)*.01 if denominator else floor
    passed = abs(derivative-coarse) <= max(.05*scale, absolute_allowance)
    return {'derivative':derivative, 'coefficient':coefficient,
            'coarse_coefficient':coarse_s, 'step_check_passed':bool(passed),
            'step_difference':abs(derivative-coarse), 'absolute_allowance':absolute_allowance}




def compute_sensitivity(case, result, target_key, reaction_indices, directory, delta=.01,
                        floor=1e-20, cancel_file=None, progress=None, checkpoint=None, *, isolated=True):
    """Native sensitivities, one default-tolerance solve; no perturbed reactor runs.

    delta is retained only for API compatibility and is not used by this method.
    """
    from .native_analysis import native_reactor, native_flame, guard
    if case.kind == 'burner_profile':
        raise ValueError('Burner species adjoint sensitivity is not implemented; use ROP or profile comparison')
    history_coordinates(case, result)
    if case.kind == 'ignition':
        raise ValueError('Use the native temperature_at_fixed_time ignition proxy; delay derivatives are not available from ReactorNet state sensitivities')
    if case.kind == 'jsr' and case.predecessor:
        raise ValueError('Continuation JSR sensitivity requires branch tracking; use an independent case')
    target = next((t for t in case.targets if t['key'] == target_key), None)
    if target is None or target_key not in result.predictions:
        raise ValueError('Target must be an existing observable of the selected case')
    if not math.isfinite(floor) or floor <= 0:
        raise ValueError('Use a positive finite zero floor')
    gas = load_gas(case.mechanism.path, case.mechanism.phase)
    indices = list(dict.fromkeys(reaction_indices))
    if not indices or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < gas.n_reactions for i in indices):
        raise ValueError('Select valid explicit reaction indices')
    calculated = []
    for scale in (1,):
        guard(cancel_file)
        if progress:
            progress(0, 1, f'Cantera native sensitivity for {len(indices)} reactions; default tolerances, one integration')
        if case.kind == 'flame':
            function, args = native_flame, (case, result, indices, scale, cancel_file)
        else:
            function, args = native_reactor, (case, target, indices, scale, directory, floor, cancel_file)
        if isolated:
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
                from .memory_control import monitored_result
                calculated.append(monitored_result(pool,pool.submit(function,*args),cancel_file))
        else:
            calculated.append(function(*args))
    baseline, derivatives, details = calculated[0]
    original = result.predictions[target_key]
    if abs(baseline-original) > max(abs(original)*case.config.get('validation_relative', .01), case.config.get('validation_absolute', 1e-10)):
        raise ValueError('Native analysis baseline differs from the cached observable')
    rows = []
    equations = gas.reaction_equations()
    for parameter, index in enumerate(indices):
        derivative = derivatives[parameter]
        passed = math.isfinite(derivative)
        rows.append({'reaction_index':index, 'reaction_number':index+1, 'equation':equations[index],
            'derivative':derivative, 'coefficient':derivative/baseline if abs(baseline)>floor else None,
            'tolerance_check_passed':None, 'status':'success' if passed else 'solver_failed'})
    data = {'target_key':target_key, 'baseline':baseline, 'cached_baseline':original,
        'method':'Cantera flame-speed adjoint' if case.kind=='flame' else 'Cantera ReactorNet forward sensitivity equations; exact mass-to-mole observable chain rule',
        'definition':'S=(1/y0)*dy/dln(m); multiplier affects forward and reverse rates',
        'zero_floor':floor, 'reaction_indices':indices, 'rows':rows,
        'planned_perturbed_solves':0, 'native_solves':1, 'validation':details,
        'tolerance_verification':False, 'all_species_path':details.get('all_species_path'),
        'selection_scope':'Explicit subset unless every mechanism reaction is selected'}
    if checkpoint:
        checkpoint(data)
    if progress:
        progress(1, 1, 'Native sensitivity complete; all reactor species saved')
    return data


def analysis_identity(case, result, settings):
    sources = [Path(__file__), Path(__file__).with_name('analysis_job.py'), Path(__file__).with_name('native_analysis.py')]
    return digest({'case':asdict(case), 'result':asdict(result), 'settings':settings,
        'prepared_yaml_sha256':file_hash(case.mechanism.path), 'history_sha256':file_hash(result.history_path),
        'cantera':ct.__version__, 'analysis_sources':{p.name:file_hash(p) for p in sources},
        'solver_source':file_hash(Path(__file__).with_name('solvers.py')),
        'history_source':file_hash(Path(__file__).with_name('history_io.py'))})


def _native_temperature(case, reaction_indices, reference_time, tighten, cancel_file=None, directory=None):
    """Cantera forward sensitivities at one fixed physical time, no history matrix."""
    if case.kind!='ignition' or not 0<reference_time<=case.config['time_end']:
        raise ValueError('Temperature proxy requires ignition and an internal positive fixed time')
    local=case_from_dict(copy.deepcopy(asdict(case)))
    defaults=ct.ReactorNet([])
    local.config={**local.config,'rtol':defaults.rtol,
                  'atol':defaults.atol,'_cancel_file':str(cancel_file or '')}
    solver=SOLVERS['ignition'](local)
    solver.setup_case()
    reactor=solver.reactor_class()(solver.gas,energy='on',clone=True)
    net=solver.network(reactor)
    for index in reaction_indices: reactor.add_sensitivity_reaction(index)
    net.max_time_step=local.config['time_end']/local.config.get('ignition_min_intervals',1000)
    for endpoint in np.linspace(0,reference_time,101)[1:]:
        solver.check_cancel()
        if psutil.virtual_memory().available<1024**3:
            if cancel_file: Path(cancel_file).touch()
            raise Cancelled('Memory guard: system available memory below 1 GiB')
        net.advance(float(endpoint))
    coefficients=[float(net.sensitivity('temperature',i)) for i in range(len(reaction_indices))]
    if not np.all(np.isfinite(coefficients)): raise ValueError('Temperature sensitivities are not finite')
    from .native_analysis import save_species_sensitivities
    saved=save_species_sensitivities(reactor,net,reaction_indices,directory,'ignition',case) if directory else None
    return float(reactor.T),coefficients,{'all_species_path':saved,'rtol':net.rtol,'atol':net.atol,
        'rtol_sensitivity':net.rtol_sensitivity,'atol_sensitivity':net.atol_sensitivity}


def compute_temperature_sensitivity(case,result,reaction_indices,reference_time,cancel_file=None,progress=None,*,isolated=True,directory=None):
    _,times=history_coordinates(case,result)
    indices=list(dict.fromkeys(reaction_indices))
    gas=load_gas(case.mechanism.path,case.mechanism.phase)
    if not indices or any(not isinstance(i,int) or not 0<=i<gas.n_reactions for i in indices):
        raise ValueError('Select valid explicit reaction indices')
    if case.kind!='ignition' or not 0<reference_time<=times[-1]:
        raise ValueError('Fixed analysis time must be inside the original ignition trajectory')
    calculated=[]
    if directory is None:
        directory=Path(result.history_path).parent/'analysis'/analysis_identity(case,result,{'temperature_time':reference_time,'reactions':indices})
    for scale in (1,):
        if progress: progress(0,1,f'Cantera temperature sensitivity at t={reference_time:g} s; default tolerances')
        args=(case,indices,reference_time,scale,cancel_file,directory)
        if isolated:
            with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn')) as pool:
                from .memory_control import monitored_result
                calculated.append(monitored_result(pool,pool.submit(_native_temperature,*args),cancel_file))
        else: calculated.append(_native_temperature(*args))
    baseline,coefficients,details=calculated[0]
    with h5py.File(result.history_path,'r') as history:
        stored=float(np.interp(reference_time,times,history['temperature'][:]))
    if abs(baseline-stored)>max(abs(stored)*.01,1e-6):
        raise ValueError('Temperature baseline differs from the stored physical trajectory')
    equations=gas.reaction_equations();rows=[]
    for parameter,index in enumerate(indices):
        value=coefficients[parameter]
        passed=math.isfinite(value)
        rows.append({'reaction_index':index,'reaction_number':index+1,'equation':equations[index],
            'coefficient':value,'derivative':value*baseline,
            'status':'success' if passed else 'solver_failed','tolerance_check_passed':None})
    if progress: progress(1,1,'Temperature sensitivity complete; all species saved')
    return {'target_key':'temperature_at_fixed_time','baseline':baseline,'stored_temperature':stored,
        'reference_time':reference_time,'reaction_indices':indices,'zero_floor':1e-20,'rows':rows,
        'method':'Cantera forward temperature sensitivity, default tolerances, one integration',
        'native_solves':1,'tolerance_verification':False,'all_species_path':details['all_species_path'],
        'definition':'S_T=(1/T)*dT/dln(m) at a fixed time; proxy, not dln(ignition delay)/dln(m)',
        'is_ignition_delay_proxy':True,'selection_scope':'Explicit selected reactions',
        'tolerance':details}
