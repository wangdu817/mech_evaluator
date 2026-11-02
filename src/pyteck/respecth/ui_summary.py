"""Presentation data, kept independent of simulation and cache identity."""
from pathlib import Path
from collections import Counter


def scope_summary(manifest, configured, selected):
    actual = sorted({c['mechanism']['id'] for c in manifest['cases']})
    loaded = {str(Path(e['path']).resolve()).casefold() for e in manifest['experiments']}
    requested = {str(Path(p).resolve()).casefold() for p in configured.get('datasets', [])}
    return {'mechanisms': actual, 'xml_count': len(loaded),
            'missing_xml': sorted(requested-loaded),
            'missing_mechanisms': sorted(set(selected)-set(actual)),
            'same_scope': set(actual) == set(selected) and loaded == requested}


def score_chart_rows(evaluation):
    coverage = [{'机理': r['mechanism'], '评分覆盖率 (%)': r['coverage']*100}
                for r in evaluation['formal']['mechanisms']]
    scores = [{'机理': r['mechanism'], '扩展组合指标（越低越好）': r['score']}
              for r in evaluation['common_success']['mechanisms']
              if r['score'] is not None]
    kinds = {'pfr': '管式反应器 · NRMSE²', 'jsr': 'JSR · NRMSE²',
             'ignition': '点火延迟 · E', 'flame': '火焰速度 · NRMSE²'}
    types = [{'机理': r['mechanism'], '实验类型': kinds.get(k, k), '类型误差（越低越好）': value}
             for r in evaluation['common_success']['mechanisms'] if r['score'] is not None
             for k, value in r['type_contributions'].items()]
    return coverage, scores, types


def case_status_rows(manifest):
    completed = {r['case_id']: r['status'] for r in manifest.get('results', [])}
    counts = Counter((c['mechanism']['id'], completed.get(c['id'], 'pending')) for c in manifest['cases'])
    labels = {'success': '数值验证通过', 'invalid_input': '输入不完整',
              'solver_failed': '求解失败', 'unverified': '未通过验证',
              'cancelled': '已取消', 'no_ignition': '未点火', 'unsupported': '不支持', 'pending': '待完成'}
    return [{'机理': mechanism, '状态': labels.get(status, status), '工况数': n}
            for (mechanism, status), n in sorted(counts.items())]
