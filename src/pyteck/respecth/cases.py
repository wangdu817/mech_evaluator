"""Mechanism preparation, physical prechecks, and explicit curve grids."""
from __future__ import annotations
from dataclasses import asdict, replace
from pathlib import Path
import contextlib
import io
import math
import platform
import re
import json
import scipy
import yaml

import cantera as ct
import numpy as np

from .models import DEFAULT_SOLVER, Mechanism, SimulationCase, digest, file_hash, clean_obsolete_options
from .reader import validate_experiment, resolve_condition
from .gas_io import load_gas

SUPPORTED_IGNITION = {"max", "d/dt max", "1/2 max", "d/dt max extrapolated"}


def prepare_mechanism(config):
    source = Path(config["path"]).resolve()
    phase = config.get("phase", "")
    inputs = {"path": {"path": str(source), "sha256": file_hash(source)}}
    directory = Path(config.get("prepared_dir", "prepared")).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    log = ""
    conversion_options = {}
    if source.suffix.lower() == ".inp":
        from cantera.ck2yaml import convert
        permissive = config.get('permissive', True)
        if not isinstance(permissive, bool):
            raise ValueError('CHEMKIN permissive must be true or false')
        conversion_options = {'permissive': permissive}
        for key in ("thermo", "transport"):
            if config.get(key):
                p = Path(config[key]).resolve()
                inputs[key] = {"path": str(p), "sha256": file_hash(p)}
        if "thermo" not in inputs:
            raise ValueError("CHEMKIN requires explicit thermo input")
        conversion_id = digest({'inputs': inputs, 'options': conversion_options, 'cantera': ct.__version__})
        converted = directory / f"converted-{conversion_id}.yaml"
        stream = io.StringIO()
        stream.write(f'ck2yaml conversion options: permissive={permissive}, quiet=False\n')
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                convert(input_file=str(source), thermo_file=config["thermo"],
                        transport_file=config.get("transport"), out_name=str(converted),
                        permissive=permissive, quiet=False)
        finally:
            log = stream.getvalue()
            (directory / f"conversion-{conversion_id}.log").write_text(log, encoding="utf-8")
        gas = load_gas(converted, phase)
    else:
        gas = load_gas(source, phase)
    # Resolve external YAML species/reaction references to one self-contained phase.
    # Retain Cantera's YAML 1.2 serialization: a YAML 1.1 parser would turn
    # species names such as NO into booleans and corrupt nitrogen mechanisms.
    serialization_note = ""
    try:
        serialized = gas.write_yaml(precision=17)
    except IndexError:
        # Cantera 3.2 may fail on user annotation strings in a valid mechanism.
        # Its documented option strips only non-model user data; original input
        # remains read-only, hashed and referenced for annotation provenance.
        serialized = gas.write_yaml(precision=17, skip_user_defined=True)
        serialization_note = "Cantera annotation serialization failed; derived YAML omits user annotations only. Original source and hash retained."
    resolved = re.sub(r"^(date|generator|cantera-version|git-commit):[^\n]*\n", "", serialized, flags=re.MULTILINE)
    identity = digest({"inputs": inputs, "resolved": resolved, "phase": gas.name,
                       "cantera": ct.__version__, "map": config.get("species_map", {})})
    destination = directory / f"{identity}.yaml"
    destination.write_text(resolved, encoding="utf-8")
    transport = gas.transport_model not in {"none", "None", ""}
    if transport:
        try:
            gas.TP = 300, 101325
            _ = gas.mix_diff_coeffs
        except ct.CanteraError:
            transport = False
    return Mechanism(config["id"], str(destination), gas.name, identity,
                     config.get("species_map", {}), gas.species_names, transport,
                     {"inputs": inputs, "cantera": ct.__version__, "conversion_log": log,
                      "conversion_options": conversion_options,
                      "serialization_note": serialization_note})


def dataset_config(experiment, config):
    settings = dict(DEFAULT_SOLVER)
    settings.update(config.solver)
    # Keys may be absolute path, basename, or explicit experiment ID.
    for key in (Path(experiment.path).name, experiment.path, experiment.id):
        settings.update(config.dataset_configs.get(key, {}))
    if experiment.kind == "ignition":
        delays = [v for s in experiment.observations for v in s.y if v > 0 and math.isfinite(v)]
        settings.setdefault("time_end", max(10 * max(delays, default=0), .01))
        settings["ignition_type"] = experiment.ignition_type
    if experiment.kind in {'profile', 'burner_profile'}:
        from .profile_inputs import profile_settings
        settings = profile_settings(experiment, settings)
    return clean_obsolete_options(settings)


def _physical_key(condition):
    c = asdict(condition)
    if condition.scan_name in {'time', 'distance'}:
        c['profile_coordinate'] = condition.scan_value
    c.pop("scan_name")
    c.pop("scan_value")
    c.pop("extras")
    c.pop("issues")
    return digest(c)


def _dense(group, options, settings, kind):
    if not options.get("enabled", False) or len(group.conditions) < 2:
        return [], []
    values = np.array([c.scan_value for c in group.conditions])
    if not np.all(np.isfinite(values)) or np.ptp(values) == 0:
        return [], []
    order = np.argsort(values)
    old = [group.conditions[i] for i in order]
    xs = values[order]
    if any(c.issues for c in old):
        return [], [f"{group.id}: dense grid skipped because source conditions have validation issues"]
    for x in np.unique(xs):
        states = {_physical_key(c) for c in old if c.scan_value == x}
        if len(states) > 1:
            return [], [f"{group.id}: dense grid skipped; repeated coordinates have different physical conditions"]
    from .grid_controls import scan_grid
    grid = scan_grid(xs, options, kind, group.scan_name)
    new, warnings = [], []
    rules = settings.get("grid_rules", options.get("rules", {}))
    scan_attr = {"temperature": "temperature", "pressure": "pressure",
                 "residence time": "residence_time", "equivalence ratio": None}.get(group.scan_name)
    for x in grid:
        if any(math.isclose(x, v, rel_tol=1e-12, abs_tol=1e-12) for v in xs):
            continue
        condition = replace(old[0], scan_value=float(x), composition=dict(old[0].composition),
                            extras=dict(old[0].extras), issues=list(old[0].issues))
        if scan_attr:
            setattr(condition, scan_attr, float(x))
        unresolved = []
        for attribute in ("temperature", "pressure", "residence_time", "volume", "composition"):
            if attribute == scan_attr:
                continue
            samples = [getattr(c, attribute) for c in old]
            if all(v == samples[0] for v in samples):
                continue
            rule = rules.get(attribute)
            if attribute == "residence_time" and isinstance(rule, dict) and rule.get("kind") == "inverse_temperature":
                condition.residence_time = float(rule["coefficient"]) / condition.temperature
            elif rule == "linear":
                if attribute == "composition":
                    species = sorted(set().union(*(c.keys() for c in samples)))
                    if any(set(c) != set(species) for c in samples):
                        unresolved.append("composition species differ")
                    else:
                        condition.composition = {s: float(np.interp(x, xs, [v[s] for v in samples])) for s in species}
                else:
                    if any(v is None for v in samples):
                        unresolved.append(attribute)
                    else:
                        setattr(condition, attribute, float(np.interp(x, xs, samples)))
            else:
                unresolved.append(attribute)
        if unresolved:
            warnings.append(f"{group.id}: dense grid skipped; explicit rules needed: {', '.join(unresolved)}")
            return [], list(dict.fromkeys(warnings))
        condition.extras = {**condition.extras, "grid_rules": rules, "scan_generated": True}
        condition.extras["properties"] = {**condition.extras.get("properties", {}), group.scan_name: float(x)}
        new.append(condition)
    return new, warnings


def build_cases(experiments, run_config, mechanisms=None):
    source_dir = Path(__file__).parent
    engine_fingerprint = digest({name: file_hash(source_dir / name) for name in
        ("models.py", "units.py", "reader.py", "cases.py", "solvers.py", "history_io.py", "../gas_io.py", "../detect_peaks.py")})
    # Only explicitly tested, exact storage-only engine revisions can retain
    # a former cache identity. Any other source/config change gets a fresh key.
    compatibility = source_dir/'cache_compatibility.json'
    if compatibility.exists():
        engine_fingerprint = json.loads(compatibility.read_text(encoding='utf-8')).get('aliases', {}).get(engine_fingerprint, engine_fingerprint)
    mechanisms = mechanisms or [prepare_mechanism({**m, "prepared_dir": str(Path(run_config.output) / "prepared")})
                                for m in run_config.mechanisms]
    cases, warnings = [], []
    for experiment in experiments:
        settings = dataset_config(experiment, run_config)
        issues = validate_experiment(experiment, settings)
        for key in ("rtol", "atol", "width", "steady_threshold", "steady_floor", "validation_relative"):
            if not isinstance(settings.get(key), (int, float)) or not math.isfinite(settings[key]) or settings[key] <= 0:
                issues.append(f"Invalid positive solver parameter: {key}")
        for key in ("time_end", "max_time"):
            if key in settings and (not math.isfinite(settings[key]) or settings[key] <= 0):
                issues.append(f"Invalid positive solver parameter: {key}")
        if settings.get("linear_solver", "dense") not in {"dense", "adaptive_preconditioned"}:
            issues.append("Unsupported linear solver")
        if experiment.kind in {"flame", "burner_profile"} and settings.get("linear_solver", "dense") == "adaptive_preconditioned":
            issues.append("Unsupported ReactorNet preconditioner for flame solver")
        if settings.get("initialization") not in {"independent", "continuation"}:
            issues.append("Invalid JSR initialization policy")
        for mechanism in mechanisms:
            from .profile_inputs import ignition_settings
            case_settings = ignition_settings(settings, mechanism) if experiment.kind == 'ignition' else dict(settings)
            if case_settings.get('ignition_substitution'):
                warnings.append(f'{experiment.id} / {mechanism.id}: ignition definition substituted with max dT/dt; ' + case_settings['ignition_substitution']['reason'])
            shared = {}
            for group in experiment.groups:
                group = replace(group, conditions=[resolve_condition(c, settings) for c in group.conditions])
                series = [s for s in experiment.observations if s.group_id == group.id]
                if not series:
                    continue
                dense, notes = _dense(group, run_config.grid, settings, experiment.kind)
                warnings.extend(f"{experiment.id}: {n}" for n in notes)
                for role, conditions in (("scoring", group.conditions), ("plotting", dense)):
                    for index, condition in enumerate(conditions):
                        profile = experiment.kind in {'profile', 'burner_profile'}
                        targets = []
                        for s in series:
                            if role == "scoring" and index not in s.point_indices:
                                continue
                            target = {"key": s.id, "quantity": s.quantity, "species": s.species,
            "units": s.units, "group_id": group.id,
                                            "point_indices": [index] if role == "scoring" else []}
                            if profile:
                                # One prediction per series/coordinate, with raw measurement identity
                                # retained separately. Repeated observations share this prediction.
                                target.update(series_id=s.id, coordinate=condition.scan_value, role=role)
                                target['key'] = digest({'series': s.id, 'coordinate': condition.scan_value, 'role': role})
                            targets.append(target)
                        # Scoped XML/condition failures must not block valid points in another group.
                        case_issues = [message for message in issues
                            if not re.match(r"^[^:]+:(?:\d+|\*): ", message)
                            or message.startswith(f"{group.id}:*: ")
                            or (role == "scoring" and message.startswith(f"{group.id}:{index}: "))]
                        case_issues.extend(condition.issues)
                        required = set(condition.composition)
                        required.update(t["species"] for t in targets if t["species"])
                        ignition = case_settings.get("ignition_type", {})
                        if experiment.kind == "ignition":
                            target = ignition.get("target", "")
                            if target not in {"p", "P", "pressure", "T", "temperature"}:
                                required.add(target)
                            if ignition.get("type") not in SUPPORTED_IGNITION:
                                case_issues.append("Unsupported ignition definition")
                        missing = [s for s in required if mechanism.species_map.get(s, s) not in mechanism.species]
                        if missing:
                            case_issues.append(f"Missing species (no implicit substitution): {sorted(missing)}")
                        if experiment.kind in {"flame", "burner_profile"} and not mechanism.transport:
                            case_issues.append("Flame requires complete transport data")
                        # A time or axial coordinate is an observation location, not a
                        # new initial/boundary condition. Share the complete trajectory
                        # across species, instruments, dataGroups and plotting points.
                        physical = replace(condition, scan_name='', scan_value=0.) if profile else condition
                        key = (_physical_key(physical), 'profile' if profile else role)
                        if key in shared:
                            existing = shared[key]
                            if index not in existing.point_indices:
                                existing.point_indices.append(index)
                            for target in targets:
                                same = next((t for t in existing.targets if t["key"] == target["key"]), None)
                                if same:
                                    same["point_indices"].extend(target["point_indices"])
                                else:
                                    existing.targets.append(target)
                            existing.issues = list(dict.fromkeys(existing.issues + case_issues))
                            if profile:
                                existing.condition = replace(existing.condition,
                                    scan_value=max(existing.condition.scan_value, condition.scan_value))
                                if role == 'scoring': existing.role = 'scoring'
                        else:
                            shared[key] = SimulationCase("", experiment.id, group.id, [index],
                                experiment.kind, condition, mechanism, dict(case_settings), targets,
                                role, list(dict.fromkeys(case_issues)))
            # Assign keys only after merged target identities are known.
            for case in shared.values():
                case.id = digest({"xml": experiment.sha256, "mechanism": {
                    "sha256": mechanism.sha256, "phase": mechanism.phase,
                    "species_map": mechanism.species_map, "species": mechanism.species,
                    "transport": mechanism.transport},
                    "condition": asdict(case.condition), "solver": case.config,
                    "targets": case.targets, "role": case.role, "issues": case.issues,
                    "engine": engine_fingerprint, "cantera": ct.__version__, "numpy": np.__version__,
                    "python": platform.python_version(), "scipy": scipy.__version__})
            if experiment.kind == "jsr" and settings["initialization"] == "continuation":
                # Chains never mix dataGroups or plotting/scoring roles.
                for role in ("scoring", "plotting"):
                    for group in experiment.groups:
                        chain = sorted((c for c in shared.values() if c.role == role and c.group_id == group.id),
                                       key=lambda c: c.condition.scan_value,
                                       reverse=settings.get("scan_direction") == "descending")
                        for previous, case in zip(chain, chain[1:]):
                            case.predecessor = previous.id
                            case.id = digest({"base": case.id, "predecessor": previous.id})
            cases.extend(shared.values())
    return cases, list(dict.fromkeys(warnings))
