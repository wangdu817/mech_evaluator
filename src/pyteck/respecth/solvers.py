"""ReSpecTh solvers extending PyTeCK's BaseSimulation contract."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
import time
import math

import cantera as ct
import h5py
import numpy as np

from ..simulation import BaseSimulation
from ..detect_peaks import detect_peaks
from .models import CaseResult, case_from_dict
from .gas_io import load_gas
from .history_io import DiskHistory


class NoIgnition(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    def finite_json(item):
        if isinstance(item, float) and not math.isfinite(item):
            return None
        if isinstance(item, dict):
            return {key: finite_json(v) for key, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [finite_json(v) for v in item]
        return item
    temp.write_text(json.dumps(finite_json(data), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _save_history(path, history, case, validation):
    path = Path(path)
    attrs = {'case_id': case.id, 'case': json.dumps(asdict(case), ensure_ascii=False),
             'validation': json.dumps(validation), 'species_names': json.dumps(case.mechanism.species),
             'units': json.dumps({'time':'s', 'temperature':'K', 'pressure':'Pa', 'volume':'m3',
                'grid':'m', 'velocity':'m/s', 'mole_fractions':'mole fraction',
                'mass_fractions':'mass fraction', 'concentrations':'mol/m3'})}
    if isinstance(history, DiskHistory):
        history.finish(path, attrs)
        return
    temporary = path.with_suffix(".h5.tmp")
    with h5py.File(temporary, "w") as store:
        store.attrs["case_id"] = case.id
        store.attrs["case"] = json.dumps(asdict(case), ensure_ascii=False)
        store.attrs["validation"] = json.dumps(validation, ensure_ascii=False)
        store.attrs["species_names"] = json.dumps(case.mechanism.species)
        for name, values in history.items():
            store.create_dataset(name, data=np.asarray(values), compression="gzip")
        store.attrs["units"] = json.dumps({"time": "s", "temperature": "K", "pressure": "Pa",
            "volume": "m3", "grid": "m", "velocity": "m/s", "mole_fractions": "mole fraction",
            "mass_fractions": "mass fraction", "concentrations": "mol/m3"})
    temporary.replace(path)




def _record(history, reactor, elapsed):
    if isinstance(history, DiskHistory):
        history.record(reactor, elapsed)
        return
    history["time"].append(float(elapsed))
    history["temperature"].append(float(reactor.T))
    history["pressure"].append(float(reactor.phase.P))
    history["volume"].append(float(reactor.volume))
    history["mole_fractions"].append(reactor.phase.X.copy())
    history["mass_fractions"].append(reactor.phase.Y.copy())
    history["concentrations"].append(reactor.phase.concentrations.copy() * 1000)


def extract_ignition(time_values, target_values, definition, config):
    t, y = np.asarray(time_values), np.asarray(target_values)
    if len(t) < 5 or not np.all(np.isfinite(y)) or np.any(np.diff(t) <= 0):
        raise NoIgnition("Insufficient finite monotonic ignition history")
    floor = config.get("ignition_absolute_signal", 1e-12)
    required = max(floor, abs(y[0]) * config.get("ignition_relative_signal", 1e-6))
    if np.ptp(y) <= required:
        raise NoIgnition("Ignition target has no resolved signal change")
    derivative = np.gradient(y, t, edge_order=2)
    signal = derivative if definition in {"d/dt max", "d/dt max extrapolated"} else y
    peaks = detect_peaks(signal, edge=None, mph=1e-9 * np.max(signal))
    if len(peaks) == 0:
        raise NoIgnition("No interior ignition peak; extend time window explicitly")
    peak = int(peaks[np.argmax(signal[peaks])])
    if peak <= 1 or peak >= len(t) - 2 or signal[peak] <= 0:
        raise NoIgnition("Ignition peak is unresolved or on the window boundary")
    if definition in {"max", "d/dt max"}:
        # Quadratic interpolation on a locally scaled time axis improves adaptive-step resolution.
        local_t = t[peak-1:peak+2] - t[peak]
        coeff = np.polyfit(local_t, signal[peak-1:peak+2], 2)
        offset = -coeff[1] / (2 * coeff[0]) if coeff[0] < 0 else 0.
        delay = t[peak] + np.clip(offset, local_t[0], local_t[-1])
    elif definition == "1/2 max":
        half = .5 * np.max(y)
        crossings = np.flatnonzero((y[:peak] < half) & (y[1:peak+1] >= half))
        if not len(crossings):
            raise NoIgnition("No rising half-maximum crossing")
        i = crossings[-1]
        delay = t[i] + (half - y[i]) * (t[i+1] - t[i]) / (y[i+1] - y[i])
    elif definition == "d/dt max extrapolated":
        delay = t[peak] - y[peak] / derivative[peak]
    else:
        raise ValueError(f"Unsupported ignition definition: {definition}")
    if not np.isfinite(delay) or delay <= 0 or delay >= t[-1]:
        raise NoIgnition("Nonpositive or truncated ignition delay")
    return float(delay)


class RKDSimulation(BaseSimulation):
    def __init__(self, case):
        super().__init__(case.kind, case.kind, {"id": case.id}, case.condition)
        self.case = case

    def setup_case(self, model_file=None, species_key=None, path=""):
        case = self.case
        self.gas = load_gas(model_file or case.mechanism.path, case.mechanism.phase)
        self.mapping = species_key or case.mechanism.species_map
        composition = {}
        for species, value in case.condition.composition.items():
            mapped = self.mapping.get(species, species)
            composition[mapped] = composition.get(mapped, 0.) + value
        self.gas.TPX = case.condition.temperature, case.condition.pressure, composition
        self.config = case.config
        self.path = Path(path)

    def run_case(self, restart=False):
        self.history, self.extra = self.solve()

    def new_history(self):
        self.history = DiskHistory(self.path, self.gas.n_species)
        return self.history

    def process_results(self):
        predictions = {}
        for target in self.case.targets:
            if target["quantity"] == "ignition delay":
                value = self.extra["ignition_delay"]
            elif target["quantity"] == "laminar burning velocity":
                value = self.extra["flame_speed"]
            else:
                species = self.mapping.get(target["species"], target["species"])
                index = self.gas.species_index(species)
                if target["units"] in {"mol/m3", "mol/cm3"}:
                    value = self.history["concentrations"][-1][index]
                else:
                    value = self.history["mole_fractions"][-1][index]
            if not np.isfinite(value) or value < -1e-12:
                raise ValueError("Nonfinite or negative predicted observable")
            predictions[target["key"]] = float(value)
        return predictions

    def network(self, reactor):
        net = ct.ReactorNet([reactor])
        net.rtol, net.atol = self.config["rtol"], self.config["atol"]
        backend = self.config.get("linear_solver", "dense")
        if backend == "adaptive_preconditioned":
            net.preconditioner = ct.AdaptivePreconditioner()
            net.derivative_settings = {"skip-third-bodies": True, "skip-falloff": True}
        elif backend != "dense":
            raise ValueError(f"Unsupported linear solver: {backend}")
        self.reactor_net = net
        return net

    def reactor_class(self, constant_pressure=False):
        if self.config.get("linear_solver", "dense") == "adaptive_preconditioned":
            return ct.IdealGasConstPressureMoleReactor if constant_pressure else ct.IdealGasMoleReactor
        return ct.IdealGasConstPressureReactor if constant_pressure else ct.IdealGasReactor

    def check_cancel(self, *_):
        marker = self.config.get("_cancel_file")
        if marker and Path(marker).exists():
            raise Cancelled("Cancellation requested")
        from .memory_control import pressure_reason
        if not hasattr(self,'_memory_checked') or time.monotonic()-self._memory_checked>1:
            self._memory_checked=time.monotonic()
            reason=pressure_reason()
            if reason: raise Cancelled(reason)
        return 0.


class PFRSimulation(RKDSimulation):
    def solve(self):
        reactor = self.reactor_class(constant_pressure=True)(self.gas, energy="off", clone=True)
        net = self.network(reactor)
        end = self.case.condition.residence_time
        net.max_time_step = end / self.config.get("history_min_intervals", 100)
        history = self.new_history()
        _record(history, reactor, 0)
        # ReactorNet.step() can overshoot even after max_time_step is changed
        # because CVODE retains its internal next step. advance() interpolates
        # the physical state at each requested time, including the exact outlet.
        for endpoint in np.linspace(0, end, self.config.get("history_min_intervals", 100)+1)[1:]:
            self.check_cancel()
            net.advance(float(endpoint))
            _record(history, reactor, net.time)
        if abs(net.time-end) > max(1e-12, end*1e-8):
            raise RuntimeError("PFR did not reach the residence-time endpoint")
        return history, {"endpoint": float(net.time)}


class JSRSimulation(RKDSimulation):
    def solve(self):
        inlet = ct.Reservoir(self.gas, clone=True)
        sink = ct.Reservoir(self.gas, clone=True)
        if self.config.get("initial_X"):
            self.gas.TPX = self.case.condition.temperature, self.case.condition.pressure, self.config["initial_X"]
        reactor = self.reactor_class()(self.gas, energy="off", clone=True,
                                    volume=self.case.condition.volume)
        tau = self.case.condition.residence_time
        flow = ct.MassFlowController(inlet, reactor, mdot=lambda _: reactor.mass / tau)
        ct.PressureController(reactor, sink, primary=flow, K=self.config.get("pressure_K", 1e-5))
        net = self.network(reactor)
        history = self.new_history()
        _record(history, reactor, 0)
        previous = reactor.phase.X.copy()
        threshold = self.config["steady_threshold"]
        floor = self.config["steady_floor"]
        consecutive, residual = 0, float("inf")
        end = self.config.get("max_time", max(100*tau, 10.))
        while net.time < end:
            self.check_cancel()
            next_check = min(net.time + tau, end)
            # Preserve adaptive solver history rather than only convergence checkpoints.
            net.max_time_step = min(tau / 10, next_check-net.time)
            while net.time < next_check - 1e-13 * max(1, next_check):
                self.check_cancel()
                net.max_time_step = min(tau/10, next_check-net.time)
                net.step()
                _record(history, reactor, net.time)
            current = reactor.phase.X.copy()
            residual = float(np.max(np.abs(current-previous) / np.maximum(np.abs(current), floor)))
            pressure_error = abs(reactor.phase.P / self.case.condition.pressure - 1)
            consecutive = consecutive+1 if residual < threshold and pressure_error < threshold else 0
            if consecutive >= 3:
                return history, {"steady_residual": residual, "pressure_error": float(pressure_error),
                                 "residence_time_definition": "reactor_mass/mdot", "mdot": reactor.mass/tau}
            previous = current
        raise RuntimeError(f"JSR not steady before {end:g} s; residual={residual:g}")


class IgnitionSimulation(RKDSimulation):
    def solve(self):
        reactor = self.reactor_class()(self.gas, energy="on", clone=True)
        net = self.network(reactor)
        end = self.config["time_end"]
        net.max_time_step = end / self.config.get("ignition_min_intervals", 1000)
        history = self.new_history()
        _record(history, reactor, 0)
        while net.time < end - max(1e-15, end*1e-13):
            self.check_cancel()
            net.max_time_step = min(net.max_time_step, end-net.time)
            net.step()
            _record(history, reactor, net.time)
        definition = self.config["ignition_type"]
        name = definition["target"]
        if name in {"p", "P", "pressure"}:
            target = history["pressure"]
        elif name in {"T", "temperature"}:
            target = history["temperature"]
        else:
            species = self.mapping.get(name, name)
            index = self.gas.species_index(species)
            # Read only the target column, not the entire species/time matrix.
            target = history["mass_fractions"][:, index]
        try:
            delay = extract_ignition(history["time"], target, definition["type"], self.config)
        except NoIgnition:
            self.history = history
            raise
        return history, {"ignition_delay": delay, "ignition_definition_used": dict(definition),
                         "ignition_substitution": self.config.get('ignition_substitution')}


class TimeProfileSimulation(RKDSimulation):
    """Post-reflected-shock, adiabatic constant-volume species at the recorded time."""
    def solve(self):
        reactor = self.reactor_class()(self.gas, energy='on', clone=True)
        net = self.network(reactor)
        net.initialize()
        coordinates = [t.get('coordinate', self.case.condition.scan_value) for t in self.case.targets]
        end = max(coordinates, default=self.case.condition.scan_value)
        history = self.new_history()
        _record(history, reactor, 0.)
        if end > 0:
            net.max_time_step = end / self.config.get('history_min_intervals', 100)
            # Include exact measurement times in a single, monotonically advancing
            # integration; never restart from the inlet for each observation.
            endpoints = np.unique(np.r_[coordinates, np.linspace(0, end,
                self.config.get('history_min_intervals', 100)+1)])
            for endpoint in endpoints[endpoints > 0]:
                self.check_cancel()
                net.advance(float(endpoint))
                _record(history, reactor, net.time)
        return history, {'endpoint': float(net.time), 'profile_model': 'adiabatic_constant_volume',
                         'shared_profile': True, 'observation_targets': len(self.case.targets)}

    def process_results(self):
        times = np.asarray(self.history['time'])
        predictions = {}
        for target in self.case.targets:
            coordinate = target.get('coordinate', self.case.condition.scan_value)
            index = self.gas.species_index(self.mapping.get(target['species'], target['species']))
            field = 'concentrations' if target['units'] in {'mol/m3', 'mol/cm3'} else 'mole_fractions'
            row = int(np.searchsorted(times, coordinate))
            if row >= len(times) or not np.isclose(times[row], coordinate, rtol=1e-12, atol=1e-15):
                raise ValueError('Profile observation time was not sampled by the integration')
            value = float(self.history[field][row, index])
            if not np.isfinite(value) or value < -1e-12:
                raise ValueError('Invalid predicted profile species')
            predictions[target['key']] = value
        return predictions


class BurnerProfileSimulation(RKDSimulation):
    """Fixed measured T(z), prescribed inlet mass flux, species transport and chemistry."""
    def _predictions(self, flame):
        return {target['key']: float(np.interp(target.get('coordinate', self.case.condition.scan_value), flame.grid,
            (flame.concentrations[index]*1000 if target['units'] in {'mol/m3', 'mol/cm3'} else flame.X[index])))
            for target in self.case.targets
            for index in [self.gas.species_index(self.mapping.get(target['species'], target['species']))]}

    def solve(self):
        width = self.config['burner_width']
        profile = self.config['temperature_profile']
        flame = ct.BurnerFlame(self.gas, width=width)
        flame.P = self.case.condition.pressure
        flame.burner.T = self.case.condition.temperature
        flame.burner.X = self.gas.X
        mdot = self.config.get('burner_mass_flux', self.gas.density*self.config.get('burner_inlet_velocity', 0))
        flame.burner.mdot = mdot
        flame.transport_model = self.config['transport_model']
        flame.soret_enabled = self.config['soret']
        positions = np.asarray(profile['distance'])
        # Crop to the specified domain; its boundaries must already be covered by T(z).
        points = np.unique(np.r_[positions[positions < width], width])
        flame.flame.set_fixed_temp_profile(points/width, np.interp(points, positions, profile['temperature']))
        flame.energy_enabled = False
        flame.set_interrupt(self.check_cancel)
        flame.set_refine_criteria(ratio=3, slope=.1, curve=.15)
        flame.solve(loglevel=0, auto=False)
        previous = self._predictions(flame)
        checks = []
        passed = False
        if self.config['verify']:
            for iteration in range(self.config['flame_max_rounds']):
                flame.set_refine_criteria(ratio=2, slope=.05/(2**iteration), curve=.075/(2**iteration))
                flame.solve(loglevel=0, auto=False)
                current = self._predictions(flame)
                errors = {key: abs(value-previous[key]) for key,value in current.items()}
                passed = all(error <= max(self.config['validation_absolute'], abs(current[key])*self.config['validation_relative']) for key,error in errors.items())
                checks.append({'differences': errors, 'nodes': len(flame.grid), 'passed': passed})
                previous = current
                if passed: break
        self.profile_predictions = previous
        history = {'grid': flame.grid, 'velocity': flame.velocity, 'temperature': flame.T,
                   'pressure': np.full_like(flame.T, flame.P), 'mole_fractions': flame.X.T,
                   'mass_fractions': flame.Y.T, 'concentrations': flame.concentrations.T*1000}
        return history, {'profile_model': 'burner_imposed_temperature', 'burner_mass_flux': mdot,
                         'shared_profile': True, 'observation_targets': len(self.case.targets),
                         'verification_passed': passed, 'profile_checks': checks,
                         'temperature_profile_source': self.config['temperature_profile_source'],
                         'domain_note': 'Domain fixed by measured T(z); no domain expansion or temperature extrapolation'}

    def process_results(self):
        values = self.profile_predictions
        if any(not np.isfinite(v) or v < -1e-12 for v in values.values()):
            raise ValueError('Invalid predicted burner species')
        return values


class FlameSimulation(RKDSimulation):
    def solve(self):
        inlet_state = self.gas.TPX
        flame = ct.FreeFlame(self.gas, width=self.config["width"])
        flame.set_interrupt(self.check_cancel)
        flame.transport_model = self.config["transport_model"]
        flame.soret_enabled = self.config["soret"]
        flame.set_refine_criteria(ratio=3, slope=.06, curve=.1)
        flame.solve(loglevel=0, auto=True)
        speed = float(flame.velocity[0])
        checks = []
        verified = False
        if self.config["verify"]:
            for iteration in range(self.config["flame_max_rounds"]):
                old_speed = float(flame.velocity[0])
                flame.set_refine_criteria(ratio=2, slope=.03 / (2**iteration), curve=.05 / (2**iteration))
                flame.solve(loglevel=0, auto=False)
                refined = float(flame.velocity[0])
                grid_error = abs(refined-old_speed) / max(abs(refined), 1e-30)
                self.gas.TPX = inlet_state
                expanded = ct.FreeFlame(self.gas, width=float(flame.grid[-1]) * 2)
                expanded.set_interrupt(self.check_cancel)
                expanded.transport_model = self.config["transport_model"]
                expanded.soret_enabled = self.config["soret"]
                expanded.set_initial_guess(data=flame.to_array())
                expanded.set_refine_criteria(ratio=2, slope=.03 / (2**iteration), curve=.05 / (2**iteration))
                expanded.solve(loglevel=0, auto=False)
                domain_error = abs(float(expanded.velocity[0])-refined) / max(abs(refined), 1e-30)
                checks.append({"grid_error": grid_error, "domain_error": domain_error,
                               "nodes": len(expanded.grid), "width": float(expanded.grid[-1])})
                flame = expanded
                if max(grid_error, domain_error) < self.config["validation_relative"]:
                    verified = True
                    break
        else:
            verified = False
        history = {"grid": flame.grid, "velocity": flame.velocity, "temperature": flame.T,
                   "pressure": np.full_like(flame.T, flame.P), "mole_fractions": flame.X.T,
                   "mass_fractions": flame.Y.T, "concentrations": flame.concentrations.T * 1000}
        return history, {"flame_speed": float(flame.velocity[0]), "verification_passed": verified,
                         "flame_checks": checks, "initial_speed": speed}


SOLVERS = {"pfr": PFRSimulation, "jsr": JSRSimulation,
           "ignition": IgnitionSimulation, "flame": FlameSimulation,
           "profile": TimeProfileSimulation, "burner_profile": BurnerProfileSimulation}


def simulate_case(case, output=None, cancel_file=None):
    if isinstance(case, dict):
        case = case_from_dict(case)
    from .runner import project_root
    directory = Path(output or case.config.get("output", project_root()/"results/standalone")) / "cache"
    directory.mkdir(parents=True, exist_ok=True)
    if cancel_file and Path(cancel_file).exists():
        return CaseResult(case.id, "cancelled", reason="Cancellation requested before start")
    if case.issues:
        unsupported = case.kind not in SOLVERS or any("Unsupported" in i for i in case.issues)
        return CaseResult(case.id, "unsupported" if unsupported else "invalid_input", reason="; ".join(case.issues))
    if case.kind not in SOLVERS:
        return CaseResult(case.id, "unsupported", reason=f"Unknown solver {case.kind}")
    start = time.monotonic()
    if cancel_file:
        case.config = {**case.config, "_cancel_file": str(cancel_file)}
    solver = SOLVERS[case.kind](case)
    tighter = None
    try:
        solver.setup_case(path=str(directory))
        solver.run_case()
        predictions = solver.process_results()
        if hasattr(solver, "reactor_net"):
            solver.extra.update(linear_solver=case.config.get("linear_solver", "dense"),
                                solver_stats=dict(solver.reactor_net.solver_stats))
        validation = {"requested": bool(case.config["verify"]), "passed": False}
        if case.kind == "flame":
            validation.update(passed=solver.extra["verification_passed"], checks=solver.extra["flame_checks"])
        elif case.kind == 'burner_profile':
            validation.update(passed=solver.extra['verification_passed'], checks=solver.extra['profile_checks'],
                              method='Species grid refinement on the measured-temperature domain')
        elif case.config["verify"]:
            tightened_case = case_from_dict(asdict(case))
            tightened_case.config = dict(case.config, rtol=case.config["rtol"]/10, atol=case.config["atol"]/10)
            if case.kind == "ignition":
                tightened_case.config["ignition_min_intervals"] = 2 * case.config.get("ignition_min_intervals", 1000)
            tighter = SOLVERS[case.kind](tightened_case)
            tighter.setup_case(path=str(directory))
            tighter.run_case()
            checked = tighter.process_results()
            differences = {k: abs(v-checked[k]) for k, v in predictions.items()}
            accepted = {k: differences[k] <= max(case.config["validation_absolute"],
                        abs(checked[k])*case.config["validation_relative"]) for k in predictions}
            validation.update(passed=all(accepted.values()), differences=differences, accepted=accepted,
                              rtol_tight=tightened_case.config["rtol"], atol_tight=tightened_case.config["atol"])
        history_path = directory / f"{case.id}.h5"
        _save_history(history_path, solver.history, case, validation)
        status = "success" if validation["passed"] else "unverified"
        return CaseResult(case.id, status, predictions,
                          "" if status == "success" else "Numerical validation disabled or not passed",
                          str(history_path), validation,
                          {"elapsed_seconds": time.monotonic()-start, "solver": solver.extra,
                           "config": case.config, "predecessor": case.predecessor})
    except Cancelled as exc:
        return CaseResult(case.id, "cancelled", reason=str(exc))
    except NoIgnition as exc:
        history_path = directory / f"{case.id}.h5"
        _save_history(history_path, solver.history, case, {"passed": False})
        return CaseResult(case.id, "no_ignition", reason=str(exc), history_path=str(history_path))
    except (ValueError, ct.CanteraError, RuntimeError) as exc:
        if cancel_file and Path(cancel_file).exists():
            return CaseResult(case.id, "cancelled", reason="Cancellation requested during solve")
        return CaseResult(case.id, "solver_failed", reason=str(exc),
                          metadata={"elapsed_seconds": time.monotonic()-start, "linear_solver": case.config.get("linear_solver","dense")})
    finally:
        for simulation in (solver, tighter):
            history = getattr(simulation, 'history', None)
            if isinstance(history, DiskHistory):
                history.close()
