import json
import pytest
from pathlib import Path

from pyteck.respecth.ui_summary import scope_summary, score_chart_rows, case_status_rows

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT/"results/actual-audited/full/manifest.json").exists(), reason="Local actual-run artifacts unavailable")
def test_real_old_batch_is_not_selected_clear_batch():
    old = json.loads((ROOT/'results/actual-audited/full/manifest.json').read_text(encoding='utf-8'))
    configured = old['config']
    scope = scope_summary(old, configured, ['clear_26092002'])
    assert not scope['same_scope']
    assert scope['mechanisms'] == ['audited_working']
    assert scope['missing_mechanisms'] == ['clear_26092002']
    counts = case_status_rows(old)
    assert sum(r['工况数'] for r in counts) == 876
    assert sum(r['工况数'] for r in counts if r['状态']=='数值验证通过') == 858


@pytest.mark.skipif(not (ROOT/"results/clear-26092002/comparison/evaluation.json").exists(), reason="Local actual-run artifacts unavailable")
def test_actual_six_xml_comparison_reports_missing_31_and_diagnostic_charts():
    batch = ROOT/'results/clear-26092002/comparison'
    manifest = json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    old = json.loads((ROOT/'results/actual-audited/full/manifest.json').read_text(encoding='utf-8'))
    scope = scope_summary(manifest, old['config'], ['clear_26092002'])
    assert scope['xml_count'] == 6
    assert len(scope['missing_xml']) == 31
    evaluation = json.loads((batch/'evaluation.json').read_text(encoding='utf-8'))
    coverage, scores, types = score_chart_rows(evaluation)
    assert len(coverage) == len(scores) == 3
    assert all(0 <= r['评分覆盖率 (%)'] <= 100 for r in coverage)
    clear = next(r for r in scores if r['机理']=='clear_26092002')
    assert abs(clear['扩展组合指标（越低越好）']-14.2729106856) < 1e-8
    assert {r['实验类型'] for r in types} == {'点火延迟 · E', '管式反应器 · NRMSE²'}


def test_pending_cases_and_missing_scores_are_not_success_or_zero():
    counts = case_status_rows({'cases': [{'id':'new','mechanism':{'id':'m'}}], 'results':[]})
    assert counts == [{'机理':'m','状态':'待完成','工况数':1}]
    _, scores, types = score_chart_rows({'formal': {'mechanisms':[]},
        'common_success': {'mechanisms':[{'mechanism':'m','eligible':False,'score':None,'type_contributions':{}}]}})
    assert scores == types == []
