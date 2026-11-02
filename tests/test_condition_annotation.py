from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
import pytest
from pyteck.respecth.reader import load_experiment
from pyteck.respecth.reporting import condition_annotation


def actual_inputs():
    path = Path(__file__).resolve().parents[2]/'exp5/Hjuler_1995_Set13.xml'
    if not path.exists():
        pytest.skip('Local actual XML is not distributed with the package')
    experiment = load_experiment(path)
    cases = [SimpleNamespace(experiment_id=experiment.id, role='scoring', condition=c,
             config={'grid_rules':{'residence_time':{'kind':'inverse_temperature','coefficient':203}},
                     'concentration_basis':'dry'}) for group in experiment.groups for c in group.conditions]
    return experiment, cases


def test_actual_conditions_keep_source_values_and_trace_assumption():
    experiment, cases = actual_inputs()
    text = condition_annotation(experiment, cases)
    assert 'P = 1 atm' in text and '203 / T(K)' in text
    assert '261 ppm CH3NH2' in text and '4 % O2' in text
    assert 'balance N2' in text and '0 ppm H2O (XML represents trace as zero)' in text
    assert 'Comparison basis' not in text and 'H2O excluded' not in text
    assert '1.05 atm' not in text and '202 / T(K)' not in text


def test_formula_is_not_displayed_when_actual_tau_does_not_match():
    experiment, cases = actual_inputs()
    cases[0].condition = replace(cases[0].condition, residence_time=1.234)
    text = condition_annotation(experiment,cases)
    assert '203 / T(K)' not in text
    assert 'τ = ' in text


def test_pointwise_feed_is_reported_as_variable():
    experiment, cases = actual_inputs()
    feed = dict(cases[0].condition.composition)
    feed['O2'] = .02
    cases[0].condition = replace(cases[0].condition,composition=feed)
    text = condition_annotation(experiment,cases)
    assert '(varies across points)' in text and '2–4 % O2' in text
