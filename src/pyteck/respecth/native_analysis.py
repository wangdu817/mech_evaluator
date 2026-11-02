"""Cantera native forward reactor and adjoint flame sensitivities."""
from dataclasses import asdict
from pathlib import Path
import copy
import math
import tempfile

import cantera as ct
import h5py
import numpy as np
import psutil

from .models import case_from_dict
from .solvers import SOLVERS, Cancelled
from .history_io import DiskHistory


def guard(cancel_file):
    if cancel_file and Path(cancel_file).exists():
        raise Cancelled('Analysis cancellation requested')
    from .memory_control import pressure_reason
    reason=pressure_reason()
    if reason: raise Cancelled(reason)


def save_species_sensitivities(reactor, net, indices, directory, kind, case):
    """Persist the final state matrix once, without rerunning for another species."""
    gas = reactor.phase
    matrix = net.sensitivities()
    sy = matrix[[reactor.component_index(s) for s in gas.species_names], :]
    dy = gas.Y[:, None] * sy
    denominator = np.sum(gas.Y / gas.molecular_weights)
    dd = np.sum(dy / gas.molecular_weights[:, None], axis=0)
    dx = (dy / gas.molecular_weights[:, None] - gas.X[:, None]*dd) / denominator
    st = matrix[reactor.component_index('temperature'), :]
    sp = np.zeros_like(st)
    if kind == 'jsr':
        sp = matrix[reactor.component_index('mass'), :] - matrix[reactor.component_index('volume'), :] + st + dd/denominator
    elif kind in {'ignition', 'profile'}:
        # Constant volume: pressure responds to temperature and total mole number.
        sp = st + dd/denominator
    dc = gas.density_mole*1000*dx + gas.concentrations[:, None]*1000*(sp-st)
    if not all(np.all(np.isfinite(values)) for values in (dy,dx,dc,st)):
        raise ValueError('All-species sensitivity matrix contains non-finite values')
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory/'all_species_sensitivity.h5'
    temporary = path.with_suffix('.h5.tmp')
    with h5py.File(temporary, 'w') as stream:
        stream.attrs.update(schema_version=1, case_id=case.id, mechanism_id=case.mechanism.id,
                            mechanism_sha256=case.mechanism.sha256, time=net.time,
                            tolerance_verification=False, rtol=net.rtol, atol=net.atol,
                            rtol_sensitivity=net.rtol_sensitivity, atol_sensitivity=net.atol_sensitivity)
        strings = h5py.string_dtype('utf-8')
        stream.create_dataset('species', data=gas.species_names, dtype=strings)
        equations=gas.reaction_equations()
        stream.create_dataset('equations', data=[equations[i] for i in indices], dtype=strings)
        stream.create_dataset('reaction_indices', data=indices)
        for quantity, values, derivatives in [('Y', gas.Y, dy), ('X', gas.X, dx), ('C', gas.concentrations*1000, dc)]:
            stream.create_dataset(quantity+'/baseline', data=values)
            stream.create_dataset(quantity+'/derivative', data=derivatives, compression='gzip', shuffle=True)
        stream.create_dataset('temperature/coefficient', data=st)
    temporary.replace(path)
    return str(path.resolve())


def species_sensitivity_view(path, species, quantity='X', floor=1e-20):
    if quantity not in {'X', 'Y', 'C'}:
        raise ValueError('Choose X, Y or C')
    with h5py.File(path, 'r') as stream:
        names = stream['species'].asstr()[:].tolist()
        index = names.index(species)
        baseline = float(stream[quantity+'/baseline'][index])
        derivatives = stream[quantity+'/derivative'][index, :]
        indices = stream['reaction_indices'][:]
        equations = stream['equations'].asstr()[:]
    rows = [{'reaction_index':int(i), 'reaction_number':int(i)+1, 'equation':str(eq),
             'derivative':float(d), 'coefficient':float(d/baseline) if abs(baseline)>floor else None,
             'status':'success' if np.isfinite(d) else 'solver_failed'} for i, eq, d in zip(indices, equations, derivatives)]
    return {'target_key':species, 'quantity':quantity, 'baseline':baseline, 'zero_floor':floor,
            'rows':rows, 'reaction_indices':indices.tolist(), 'method':'Saved Cantera native matrix; no new integration',
            'tolerance_verification':False, 'all_species_path':str(path)}


def observable_derivatives(reactor, net, target, mapping, kind):
    """Cantera returns Y sensitivities; apply the exact Y -> X -> C chain rule."""
    gas = reactor.phase
    matrix = net.sensitivities()
    sy = matrix[[reactor.component_index(s) for s in gas.species_names], :]
    dy = gas.Y[:, None] * sy
    weights = gas.molecular_weights
    denominator = np.sum(gas.Y / weights)
    dd = np.sum(dy / weights[:, None], axis=0)
    index = gas.species_index(mapping.get(target['species'], target['species']))
    dx = (dy[index] / weights[index] - gas.X[index] * dd) / denominator
    value = float(gas.X[index])
    derivative = dx
    if target['units'] in {'mol/m3', 'mol/cm3'}:
        st = matrix[reactor.component_index('temperature'), :]
        sp = np.zeros_like(st)
        if kind == 'jsr':
            sp = (matrix[reactor.component_index('mass'), :]
                  - matrix[reactor.component_index('volume'), :] + st + dd / denominator)
        elif kind in {'ignition', 'profile'}:
            sp = st + dd / denominator
        total = gas.density_mole * 1000
        value = float(gas.concentrations[index] * 1000)
        derivative = total * dx + value * (sp - st)
    return value, np.asarray(derivative)


def native_reactor(case, target, indices, tighten, workdir, floor, cancel_file=None):
    local = case_from_dict(copy.deepcopy(asdict(case)))
    if case.kind == 'profile':
        # Diagnostics request one time on the shared batch trajectory. Integrate
        # sensitivities only to that time, rather than to the curve's last point.
        local.condition.scan_value = target.get('coordinate', case.condition.scan_value)
        local.targets = [target]
    # Mass-fraction reactor coordinates are required for the observable chain rule.
    # Same physical model; dense linear solve also supports native sensitivities.
    defaults = ct.ReactorNet([])
    local.config.update(rtol=defaults.rtol, atol=defaults.atol,
                        linear_solver='dense', _cancel_file=str(cancel_file or ''))
    base = SOLVERS[case.kind]
    class Native(base):
        def network(self, reactor):
            self.reactor = reactor
            net = super().network(reactor)
            for index in indices:
                reactor.add_sensitivity_reaction(index)
            return net

        def check_cancel(self, *args):
            guard(cancel_file)
            return super().check_cancel(*args)

    solver = Native(local)
    try:
        solver.setup_case(path=str(workdir))
        solver.run_case()
        reactor, net = solver.reactor, solver.reactor_net
        value, derivative = observable_derivatives(reactor, net, target, solver.mapping, case.kind)
        steady_check = None
        if case.kind == 'jsr':
            # State convergence alone does not establish sensitivity convergence.
            previous = derivative.copy()
            previous_x = reactor.phase.X.copy()
            consecutive = 0
            tau = case.condition.residence_time
            end = case.config.get('max_time', max(100*tau, 10.))
            while net.time + tau <= end:
                guard(cancel_file)
                net.advance(net.time + tau)
                value, derivative = observable_derivatives(reactor, net, target, solver.mapping, case.kind)
                scaled = np.max(np.abs(derivative-previous) / np.maximum(np.maximum(np.abs(derivative), np.abs(previous)), floor))
                absolute = np.max(np.abs(derivative-previous))
                state_error = np.max(np.abs(reactor.phase.X-previous_x)/np.maximum(np.abs(reactor.phase.X), case.config['steady_floor']))
                stable = (scaled < 1e-5 or absolute < max(abs(value)*1e-8, floor)) and state_error < case.config['steady_threshold'] and abs(reactor.phase.P/case.condition.pressure-1) < case.config['steady_threshold']
                consecutive = consecutive+1 if stable else 0
                if consecutive >= 3:
                    steady_check = {'passed': True, 'windows': 3, 'time': net.time, 'relative_change': float(scaled)}
                    break
                previous, previous_x = derivative.copy(), reactor.phase.X.copy()
            if steady_check is None:
                raise ValueError('JSR native sensitivities did not reach steady state before the configured time limit')
        if not math.isfinite(value) or not np.all(np.isfinite(derivative)):
            raise ValueError('Native sensitivities are not finite')
        saved = save_species_sensitivities(reactor, net, indices, workdir, case.kind, case)
        return value, derivative.tolist(), {'steady_check': steady_check, 'linear_solver': 'dense',
            'all_species_path': saved, 'rtol': net.rtol, 'atol': net.atol,
            'rtol_sensitivity': net.rtol_sensitivity, 'atol_sensitivity': net.atol_sensitivity}
    finally:
        if isinstance(getattr(solver, 'history', None), DiskHistory):
            solver.history.close()


def native_flame(case, result, indices, tighten, cancel_file=None):
    from .gas_io import load_gas
    guard(cancel_file)
    gas = load_gas(case.mechanism.path, case.mechanism.phase)
    composition = {case.mechanism.species_map.get(s, s): x for s, x in case.condition.composition.items()}
    gas.TPX = case.condition.temperature, case.condition.pressure, composition
    with h5py.File(result.history_path, 'r') as history:
        grid = history['grid'][:]
        data = ct.SolutionArray(gas, shape=len(grid), extra={'grid': grid, 'velocity': history['velocity'][:]})
        data.TPY = history['temperature'][:], history['pressure'][:], history['mass_fractions'][:]
    # SolutionArray assignment changed gas state; restore the unburned inlet.
    gas.TPX = case.condition.temperature, case.condition.pressure, composition
    flame = ct.FreeFlame(gas, grid=grid)
    flame.transport_model = case.config['transport_model']
    flame.soret_enabled = case.config['soret']
    flame.set_interrupt(lambda _: guard(cancel_file) or 0.)
    flame.set_initial_guess(data=data)
    flame.set_refine_criteria(ratio=2, slope=.03/tighten**.3, curve=.05/tighten**.3)
    flame.solve(loglevel=0, auto=False, refine_grid=True)
    speed = float(flame.velocity[0])
    coefficients = flame.get_flame_speed_reaction_sensitivities()[indices]
    if not np.all(np.isfinite(coefficients)):
        raise ValueError('Flame adjoint sensitivities are not finite')
    return speed, (coefficients*speed).tolist(), {'nodes': len(flame.grid), 'width': float(flame.grid[-1]),
        'refinement_scale': tighten, 'method': 'FreeFlame.get_flame_speed_reaction_sensitivities (adjoint)'}
