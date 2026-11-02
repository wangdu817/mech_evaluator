"""Physical, preservation, provenance and ranking regression tests."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import math
import shutil
import xml.etree.ElementTree as ET

import cantera as ct
import h5py
import numpy as np
import pytest

from pyteck.respecth import (load_experiment, discover_experiments, RunConfig,
    prepare_mechanism, build_cases, simulate_case, evaluate_results, validate_experiment)
from pyteck.respecth.models import CaseResult, file_hash
from pyteck.respecth.runner import load_config, prepare_run, run_project, load_run
from pyteck.respecth.solvers import extract_ignition, NoIgnition
from pyteck.respecth.units import to_si
from pyteck.respecth.gas_io import load_gas
from pyteck.eval_model import estimate_std_dev

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "respecth"


@pytest.fixture(scope="session")
def demo():
    config = load_config(DEMO / "demo.yaml")
    return prepare_run(config)


def test_real_library_value_preservation():
    files = discover_experiments(ROOT.parent)
    assert len(files) == 37
    total = 0
    raw_total = 0
    measurement_values = 0
    for path in files:
        before = file_hash(path)
        parsed = load_experiment(path)
        assert not parsed.issues
        xml = ET.parse(path)
        raw_total += len(xml.findall('dataGroup/dataPoint'))
        total += sum(len(g.points) for g in parsed.groups)
        for group in parsed.groups:
            raw_group = next(g for g in xml.findall("dataGroup") if g.get("id") == group.id)
            raw_rows = [{n.tag: float(n.text) for n in point} for point in raw_group.findall("dataPoint")]
            assert group.points == raw_rows
            for series in [s for s in parsed.observations if s.group_id == group.id]:
                assert series.raw_values == [r[series.property_id] for r in raw_rows]
                property_xml = next(p for p in raw_group.findall("property") if p.get("id") == series.property_id)
                assert series.units == property_xml.get("units")
                assert series.source_type == property_xml.get("sourcetype")
                measurement_values += len(series.y)
        assert before == file_hash(path) == parsed.sha256
    # The source library may be updated; the parser must preserve the current
    # XML point count, rather than an obsolete historical count of 1000.
    assert total == raw_total and total > 0
    assert measurement_values > total


def test_instruments_and_zero_values():
    experiment = load_experiment(ROOT.parent / "exp1" / "Marrodan_2024_Set1.xml")
    species = [s for s in experiment.observations if s.species == "CH3NH2"]
    assert len(species) == 2
    assert {s.instrument for s in species} == {"FTIR", "microGC"}
    assert any(0 in s.y for s in species)
    assert not any("Concentration basis" in i for i in validate_experiment(experiment))


@pytest.mark.parametrize("name", ["x00003001.xml", "x10000008.xml", "x20000028.xml"])
def test_v23_examples_parse(name):
    experiment = load_experiment(ROOT.parent / name)
    assert experiment.version == "2.3"
    assert experiment.groups and experiment.observations
    assert experiment.xml_text


def test_units():
    assert to_si(200, "ppm", "composition") == pytest.approx(.0002)
    assert to_si(1, "mol/cm3", "concentration") == 1e6
    with pytest.raises(ValueError):
        to_si(1, "mol/m3", "composition")


def test_dense_rule_never_guesses(demo):
    experiments, cases, _ = demo
    pfr = next(e for e in experiments if e.kind == "pfr")
    group = pfr.groups[0]
    group.conditions[0].residence_time = .1
    group.conditions[1].residence_time = .07
    config = load_config(DEMO / "demo.yaml")
    config.grid = {"enabled": True, "points": 5}
    mechanisms = [cases[0].mechanism]
    generated, warnings = build_cases([pfr], config, mechanisms)
    assert not any(c.role == "plotting" for c in generated)
    assert warnings
    config.dataset_configs[pfr.path] = {"grid_rules": {"residence_time": {"kind": "inverse_temperature", "coefficient": 70}}}
    generated, _ = build_cases([pfr], config, mechanisms)
    for case in generated:
        if case.role == "plotting":
            assert case.condition.residence_time == pytest.approx(70/case.condition.temperature)
            assert 700 < case.condition.temperature < 1000
    # Restore session fixture.
    group.conditions[0].residence_time = group.conditions[1].residence_time = .05


def test_pfr_independent_cantera(demo):
    _, cases, _ = demo
    case = next(c for c in cases if c.kind == "pfr" and c.condition.temperature == 1000)
    result = simulate_case(case, ROOT / "results" / "test-physics")
    assert result.status == "success", result.reason
    gas = load_gas(case.mechanism.path, case.mechanism.phase)
    gas.TPX = case.condition.temperature, case.condition.pressure, case.condition.composition
    reactor = ct.IdealGasConstPressureReactor(gas, energy="off", clone=True)
    network = ct.ReactorNet([reactor])
    network.rtol, network.atol = 1e-11, 1e-17
    network.advance(case.condition.residence_time)
    for target in case.targets:
        expected = reactor.phase.X[gas.species_index(target["species"])]
        assert result.predictions[target["key"]] == pytest.approx(expected, rel=1e-6, abs=1e-10)


@pytest.mark.parametrize("kind", ["pfr", "jsr"])
def test_nonreactive_inlet_conservation(kind, demo):
    _, cases, _ = demo
    case = replace(next(c for c in cases if c.kind == kind), id=f"inert-{kind}")
    case.condition = replace(case.condition, composition={"AR": 1.}, temperature=500.)
    case.targets = [{"key": "argon", "quantity": "composition", "species": "AR", "units": "mole fraction"}]
    result = simulate_case(case, ROOT / "results" / "test-physics")
    assert result.status == "success", result.reason
    assert result.predictions["argon"] == pytest.approx(1, abs=1e-10)


def test_jsr_independent_reference(demo):
    _, cases, _ = demo
    case = next(c for c in cases if c.kind == "jsr" and c.condition.temperature == 1000)
    result = simulate_case(case, ROOT / "results" / "test-physics")
    assert result.status == "success", result.reason
    gas = load_gas(case.mechanism.path)
    gas.TPX = case.condition.temperature, case.condition.pressure, case.condition.composition
    inlet, outlet = ct.Reservoir(gas, clone=True), ct.Reservoir(gas, clone=True)
    reactor = ct.IdealGasReactor(gas, energy="off", clone=True, volume=case.condition.volume)
    flow = ct.MassFlowController(inlet, reactor, mdot=lambda _: reactor.mass/case.condition.residence_time)
    regulator = ct.PressureController(reactor, outlet, primary=flow, K=1e-5)
    net = ct.ReactorNet([reactor])
    net.rtol, net.atol = 1e-11, 1e-17
    net.advance_to_steady_state(max_steps=50000, residual_threshold=1e-8)
    for target in case.targets:
        predicted = result.predictions[target["key"]]
        assert predicted == pytest.approx(reactor.phase.X[gas.species_index(target["species"])], rel=2e-5, abs=1e-9)
    assert regulator.pressure_coeff > 0


def test_ignition_zero_target_and_no_proxy(demo):
    experiments, cases, _ = demo
    experiment = next(e for e in experiments if e.kind == "ignition")
    config = load_config(DEMO / "demo.yaml")
    config.solver['ignition_fallback'] = 'none'
    experiment.ignition_type = {"target": cases[0].mechanism.species[0], "type": "d/dt max"}
    generated, _ = build_cases([experiment], config, [cases[0].mechanism])
    assert not any(c.issues for c in generated)
    experiment.ignition_type = {"target": "OH*", "type": "d/dt max"}
    generated, _ = build_cases([experiment], config, [cases[0].mechanism])
    assert all(any("OH*" in i for i in c.issues) for c in generated)
    experiment.ignition_type = {"target": "p", "type": "d/dt max"}


def test_no_ignition_history_and_boundary(demo):
    _, cases, _ = demo
    case = replace(next(c for c in cases if c.kind == "ignition"), id="no-ignition")
    case.condition = replace(case.condition, temperature=300.)
    result = simulate_case(case, ROOT / "results" / "test-physics")
    assert result.status == "no_ignition"
    assert not result.predictions
    assert Path(result.history_path).exists()
    with pytest.raises(NoIgnition):
        extract_ignition(np.linspace(0, 1, 100), np.linspace(0, 1, 100)**3, "d/dt max", {})


def test_upstream_score_and_failure_coverage(demo):
    experiments, cases, _ = demo
    experiment = next(e for e in experiments if e.kind == "ignition")
    ignition_cases = [c for c in cases if c.experiment_id == experiment.id]
    series = experiment.observations[0]
    results = []
    for c in ignition_cases:
        target = c.targets[0]
        index = target["point_indices"][0]
        results.append(CaseResult(c.id, "success", {series.id: 2*series.y[index]}, validation={'passed': True}))
    report = evaluate_results([experiment], results, {}, ignition_cases)
    scale = estimate_std_dev(np.array(series.x), np.log(np.array(series.y)))
    for curve in report["formal"]["curves"]:
        assert curve["E"] == pytest.approx((np.log(2)/scale)**2)
        assert curve["D"] == pytest.approx(np.log(2)/scale)
    results[0] = CaseResult(results[0].case_id, "no_ignition")
    failed = evaluate_results([experiment], results, {}, ignition_cases)
    assert len(failed["formal"]["ranking"]) == 1
    assert failed["excluded_points"] == 1
    assert all(c["selected_points"] == 2 for c in failed["common_success"]["curves"])


def test_zero_curve_needs_explicit_scale(demo):
    experiments, cases, _ = demo
    experiment = next(e for e in experiments if e.kind == "pfr")
    series = experiment.observations[0]
    saved = series.y
    series.y = [0.] * len(series.y)
    selected = [c for c in cases if c.kind == "pfr"]
    results = [CaseResult(c.id, "success", {t["key"]: 0. for t in c.targets}, validation={'passed': True}) for c in selected]
    report = evaluate_results([experiment], results, {}, selected)
    assert not report["formal"]["ranking"]
    report = evaluate_results([experiment], results, {"scales": {series.species: 1e-6}}, selected)
    assert len(report["formal"]["ranking"]) == 2
    series.y = saved


def test_fingerprint_tracks_mechanism_and_solver(demo):
    experiments, cases, _ = demo
    config = load_config(DEMO / "demo.yaml")
    mechanism = cases[0].mechanism
    original, _ = build_cases(experiments, config, [mechanism])
    config.figure = {"linewidth": 2}
    config.scoring = {"type_weights": {"ignition": 2}}
    unchanged, _ = build_cases(experiments, config, [mechanism])
    assert [c.id for c in original] == [c.id for c in unchanged]
    config.solver["rtol"] = 1e-10
    changed, _ = build_cases(experiments, config, [mechanism])
    assert {c.id for c in original}.isdisjoint({c.id for c in changed})


def test_prepared_identity_is_stable():
    settings = {"id": "stable", "path": str(DEMO / "mechanisms" / "h2o2.yaml"),
                "prepared_dir": str(ROOT / "results" / "test-prepared")}
    first = prepare_mechanism(settings)
    second = prepare_mechanism(settings)
    assert first.sha256 == second.sha256
    assert first.path == second.path


def test_obsolete_normalization_does_not_change_actual_fractions(demo):
    _, cases, _ = demo
    base = next(c for c in cases if c.kind == "pfr" and c.condition.temperature == 1000)
    wet = simulate_case(base, ROOT / "results" / "test-physics")
    dry_case = replace(base, id="dry-conversion", config={**base.config, "concentration_basis": "dry"})
    dry = simulate_case(dry_case, ROOT / "results" / "test-physics")
    assert dry.status == wet.status == "success"
    with h5py.File(wet.history_path, "r") as h:
        water = h["mole_fractions"][-1][base.mechanism.species.index("H2O")]
    for key in wet.predictions:
        assert dry.predictions[key] == pytest.approx(wet.predictions[key], rel=1e-7)


def test_conflict_and_unknown_unit_are_explicit(tmp_path):
    content = (DEMO / "synthetic-pfr.xml").read_text(encoding="utf-8")
    root = ET.fromstring(content)
    prop = ET.SubElement(root.find("commonProperties"), "property", name="temperature", units="K")
    ET.SubElement(prop, "value").text = "300"
    path = tmp_path / "conflict.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    parsed = load_experiment(path)
    assert any("Conflicting" in issue for issue in validate_experiment(parsed, {"concentration_basis": "wet"}))
    root.find("dataGroup/property").set("units", "unknown-unit")
    ET.ElementTree(root).write(path, encoding="utf-8")
    parsed = load_experiment(path)
    assert any("Unsupported unit" in issue for issue in validate_experiment(parsed, {"concentration_basis": "wet"}))


def test_missing_transport_blocks_flame(demo):
    experiments, cases, _ = demo
    mechanism = replace(cases[0].mechanism, transport=False)
    config = load_config(DEMO / "demo.yaml")
    generated, _ = build_cases([next(e for e in experiments if e.kind == "flame")], config, [mechanism])
    assert all(any("transport" in issue for issue in c.issues) for c in generated)


def test_cancel_before_start(demo, tmp_path):
    _, cases, _ = demo
    marker = tmp_path / "CANCEL"
    marker.touch()
    result = simulate_case(cases[0], ROOT / "results" / "test-physics", marker)
    assert result.status == "cancelled"


def test_chemkin_roundtrip(tmp_path):
    from cantera.yaml2ck import convert
    gas = load_gas(DEMO / "mechanisms" / "h2o2.yaml")
    reaction, thermo, transport = tmp_path / "mech.inp", tmp_path / "thermo.dat", tmp_path / "trans.dat"
    convert(gas, mechanism_path=reaction, thermo_path=thermo, transport_path=transport, overwrite=True)
    mechanism = prepare_mechanism({"id": "ck", "path": str(reaction), "thermo": str(thermo),
                                   "transport": str(transport), "prepared_dir": str(tmp_path / "prepared")})
    loaded = load_gas(mechanism.path)
    assert loaded.n_species == gas.n_species
    assert loaded.n_reactions == gas.n_reactions
    assert mechanism.transport
    assert (tmp_path / "prepared").glob("conversion-*.log")


@pytest.mark.parametrize("kind", ["pfr", "jsr"])
def test_first_order_analytic_model(kind, demo, tmp_path):
    _, cases, _ = demo
    species = []
    for name, composition in (("A", {"H": 2}), ("B", {"H": 2}), ("AR", {"Ar": 1})):
        component = ct.Species(name, composition)
        component.thermo = ct.ConstantCp(200, 5000, 101325, [298.15, 0., 0., 2.5*ct.gas_constant])
        species.append(component)
    reaction = ct.Reaction(reactants={"A": 1}, products={"B": 1}, rate=ct.ArrheniusRate(5, 0, 0))
    reaction.reversible = False
    gas = ct.Solution(thermo="ideal-gas", kinetics="gas", species=species, reactions=[reaction])
    path = tmp_path / "first-order.yaml"
    path.write_text(gas.write_yaml(), encoding="utf-8")
    mechanism = prepare_mechanism({"id": "analytic", "path": str(path), "prepared_dir": str(tmp_path/"prepared")})
    base = next(c for c in cases if c.kind == kind)
    case = replace(base, id=f"analytic-{kind}", mechanism=mechanism,
                   condition=replace(base.condition, composition={"A": .1, "AR": .9},
                                     residence_time=.2, temperature=800.),
                   targets=[{"key": "A", "quantity": "composition", "species": "A", "units": "mole fraction"}])
    result = simulate_case(case, ROOT/"results"/"test-physics")
    assert result.status == "success", result.reason
    exact = .1*np.exp(-1) if kind == "pfr" else .1/2
    assert result.predictions["A"] == pytest.approx(exact, rel=1e-6)


def test_actual_species_index_zero(demo):
    _, cases, _ = demo
    from pyteck.respecth.solvers import IgnitionSimulation
    original = next(c for c in cases if c.kind == "ignition")
    case = replace(original, config={**original.config, "ignition_type": {"target": "H2", "type": "max"}})
    solver = IgnitionSimulation(case)
    solver.setup_case()
    assert solver.gas.species_index("H2") == 0
    assert solver.mapping.get("H2", "H2") == "H2"


def test_no_species_survives_yaml_serialization(demo):
    _, cases, _ = demo
    nitrogen = next(c.mechanism for c in cases if c.mechanism.id == "gri30")
    gas = load_gas(nitrogen.path, nitrogen.phase)
    assert "NO" in gas.species_names
    assert gas.n_species == 53


def test_ignition_independent_reference(demo):
    _, cases, _ = demo
    case = next(c for c in cases if c.kind == "ignition" and c.condition.temperature == 1100)
    result = simulate_case(case, ROOT/"results"/"test-physics")
    assert result.status == "success", result.reason
    gas = load_gas(case.mechanism.path)
    gas.TPX = case.condition.temperature, case.condition.pressure, case.condition.composition
    reactor = ct.IdealGasReactor(gas, energy="on", clone=True)
    net = ct.ReactorNet([reactor])
    net.rtol, net.atol = 1e-11, 1e-17
    times = np.linspace(0, .002, 20001)
    pressure = []
    for value in times:
        net.advance(float(value))
        pressure.append(reactor.phase.P)
    independent = times[np.argmax(np.gradient(pressure, times))]
    assert next(iter(result.predictions.values())) == pytest.approx(independent, rel=.005)


def test_flame_independent_reference(demo):
    _, cases, _ = demo
    case = next(c for c in cases if c.kind == "flame" and c.condition.scan_value == 1)
    result = simulate_case(case, ROOT/"results"/"test-physics")
    assert result.status == "success", result.reason
    gas = load_gas(case.mechanism.path)
    gas.TPX = case.condition.temperature, case.condition.pressure, case.condition.composition
    reference = ct.FreeFlame(gas, width=.12)
    reference.transport_model = "mixture-averaged"
    reference.soret_enabled = False
    reference.set_refine_criteria(ratio=2, slope=.015, curve=.025)
    reference.solve(loglevel=0, auto=True)
    assert next(iter(result.predictions.values())) == pytest.approx(reference.velocity[0], rel=.01)


def test_invalid_point_does_not_block_valid_point(demo, tmp_path):
    _, cases, _ = demo
    tree = ET.parse(DEMO/'synthetic-pfr.xml')
    tree.find('dataGroup/dataPoint/T_column').text = '0'
    path = tmp_path/'partial.xml'
    tree.write(path, encoding='utf-8')
    experiment = load_experiment(path)
    generated, _ = build_cases([experiment], load_config(DEMO/'demo.yaml'), [cases[0].mechanism])
    assert generated[0].issues
    assert not generated[1].issues
    assert simulate_case(generated[0], ROOT/'results/test-physics').status == 'invalid_input'


def test_duplicate_measurements_share_solve(demo, tmp_path):
    _, cases, _ = demo
    tree = ET.parse(DEMO/'synthetic-pfr.xml')
    import copy
    group = tree.find('dataGroup')
    duplicate = copy.deepcopy(group.find('dataPoint'))
    duplicate.find('obs0').text = '.11'
    group.append(duplicate)
    path = tmp_path/'duplicates.xml'
    tree.write(path, encoding='utf-8')
    experiment = load_experiment(path)
    generated, _ = build_cases([experiment], load_config(DEMO/'demo.yaml'), [cases[0].mechanism])
    assert len(generated) == 2
    assert len(experiment.observations[0].y) == 3
    assert generated[0].targets[0]['point_indices'] == [0, 2]


def test_species_no_is_not_a_config_boolean():
    from pyteck.respecth.yaml_io import load_yaml
    data = load_yaml('species_map: {NO: NO, OH: OH}\nverify: true\nsoret: false')
    assert data['species_map'] == {'NO': 'NO', 'OH': 'OH'}
    assert data['verify'] is True and data['soret'] is False


def test_explicit_missing_condition_supplement(demo):
    from pyteck.respecth.reader import resolve_condition
    _, cases, _ = demo
    original = next(c for c in cases if c.kind == 'jsr').condition
    missing = replace(original, volume=None)
    resolved = resolve_condition(missing, {'conditions': {'volume': {'value': 30, 'units': 'cm3'}}})
    assert resolved.volume == pytest.approx(30e-6)
    assert original.volume == pytest.approx(30e-6)
    conflict = resolve_condition(original, {'conditions': {'pressure': {'value': 2, 'units': 'atm'}}})
    assert conflict.pressure == original.pressure
    assert any('Conflicting' in issue for issue in conflict.issues)


def test_nonfinite_missing_or_unverified_predictions_never_rank(demo):
    experiments, all_cases, _ = demo
    experiment = next(e for e in experiments if e.kind == 'pfr')
    cases = [c for c in all_cases if c.experiment_id == experiment.id]
    results = [CaseResult(c.id, 'success', {t['key']: .01 for t in c.targets},
                          validation={'passed': True}) for c in cases]
    results[0].predictions[cases[0].targets[0]['key']] = float('nan')
    report = evaluate_results([experiment], results, {}, cases)
    assert len(report['formal']['ranking']) == 1
    assert report['excluded_points'] == 1
    results[0].predictions = {}
    report = evaluate_results([experiment], results, {}, cases)
    assert len(report['formal']['ranking']) == 1
    results[0].validation = {}
    report = evaluate_results([experiment], results, {}, cases)
    assert len(report['formal']['ranking']) == 1


def test_same_named_xml_does_not_collide(demo, tmp_path):
    _, original, _ = demo
    paths = []
    for index, pressure in enumerate([1, 2]):
        folder = tmp_path/str(index)
        folder.mkdir()
        tree = ET.parse(DEMO/'synthetic-pfr.xml')
        tree.find("commonProperties/property[@name='pressure']/value").text = str(pressure)
        path = folder/'same.xml'
        tree.write(path, encoding='utf8')
        paths.append(path)
    experiments = [load_experiment(p) for p in paths]
    cases, _ = build_cases(experiments, load_config(DEMO/'demo.yaml'), [original[0].mechanism])
    assert len({e.id for e in experiments}) == 2
    assert len({c.id for c in cases}) == 4


def test_redraw_removes_only_previous_exported_figures(demo, tmp_path):
    from pyteck.respecth.reporting import render_figures
    experiments, cases, _ = demo
    results = [CaseResult(c.id, 'success', {t['key']: .01 for t in c.targets}, validation={'passed': True}) for c in cases]
    bundle = {'cases': cases, 'results': results}
    render_figures(experiments, bundle, {'output': str(tmp_path), 'formats': ['png']})
    user_file = tmp_path/'user-figure.png'
    user_file.write_bytes(b'user file')
    wanted = experiments[0].observations[0].id
    paths = render_figures(experiments, bundle, {'output': str(tmp_path), 'formats': ['svg'], 'series': [wanted]})
    assert len(paths) == 1
    assert list(tmp_path.glob('*.png')) == [user_file]
    assert len(json.loads((tmp_path/'figure_sources.json').read_text())) == 1


def test_obsolete_measurement_confirmation_does_not_block_scoring(demo):
    from pyteck.respecth.evaluation import comparison_rows
    experiments, all_cases, _ = demo
    experiment = next(e for e in experiments if e.kind == 'pfr')
    cases = [replace(c, config={**c.config, 'measurement_basis_confirmed': False}) for c in all_cases if c.experiment_id == experiment.id]
    results = [CaseResult(c.id, 'success', {t['key']: .01 for t in c.targets}, validation={'passed': True}) for c in cases]
    report = evaluate_results([experiment], results, {}, cases)
    assert report['formal']['ranking']
    rows = comparison_rows([experiment], cases, results)
    assert all(r['status'] == 'success' and r['residual'] is not None and r['predicted'] == .01 for r in rows)


def test_audited_working_serialization_preserves_physical_model(tmp_path):
    source = ROOT.parent/'mech/audited_working.yaml'
    if not source.exists():
        pytest.skip('Local user mechanism unavailable')
    original_hash = file_hash(source)
    mechanism = prepare_mechanism({'id': 'audited', 'path': str(source), 'phase': 'gas', 'prepared_dir': str(tmp_path)})
    reference = ct.Solution(yaml=source.read_text(encoding='utf8'), name='gas')
    prepared = ct.Solution(yaml=Path(mechanism.path).read_text(encoding='utf8'), name='gas')
    assert reference.species_names == prepared.species_names
    assert reference.n_reactions == prepared.n_reactions
    for temperature in (800, 1400, 2000):
        reference.TPX = prepared.TPX = temperature, 101325, 'CH3NH2:1,O2:2,N2:7.52'
        np.testing.assert_allclose(reference.standard_cp_R, prepared.standard_cp_R, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(reference.net_production_rates, prepared.net_production_rates, rtol=1e-10, atol=1e-20)
    assert file_hash(source) == original_hash
