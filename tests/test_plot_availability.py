from pathlib import Path
import pytest
from pyteck.respecth.runner import load_run
from pyteck.respecth.reporting import plot_availability,render_figures

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'results/comparison-clear-ncho-restored-20261009-163550'

@pytest.fixture(scope='module')
def actual():
    if not (SOURCE/'manifest.json').exists(): pytest.skip('Actual saved data unavailable')
    return load_run(SOURCE)

def test_selected_sets_have_blocked_clear_and_absent_ncho(actual):
    _,experiments,cases,results=actual
    selected=[e for e in experiments if Path(e.path).stem in {'Marrodan_2024_Set4','Marrodan_2024_Set5'}]
    report=plot_availability(experiments,cases,results,[e.id for e in selected],
        ['clear_26092002','N_CHO_240725_working'],[s.id for e in selected for s in e.observations])
    assert len(report)==4
    assert all(row['可绘制预测点']==row['可连线曲线']==0 for row in report)
    assert all('旧版本输入限制' in r['说明'] for r in report if r['机理']=='clear_26092002')
    assert all('没有这个 XML' in r['说明'] for r in report if r['机理']=='N_CHO_240725_working')

def test_actual_ignition_has_lines_for_both_mechanisms(actual):
    _,experiments,cases,results=actual
    experiment=next(e for e in experiments if Path(e.path).stem=='Shin_Yoo_2004_MIX1')
    report=plot_availability([experiment],cases,results,[experiment.id],
        ['clear_26092002','N_CHO_240725_working'],[s.id for s in experiment.observations])
    assert all(r['可绘制预测点']>1 and r['可连线曲线']>0 for r in report)

def test_experiment_only_export_states_missing_simulations(actual,tmp_path):
    _,experiments,cases,results=actual
    experiment=next(e for e in experiments if Path(e.path).stem=='Marrodan_2024_Set4')
    paths=render_figures(experiments,{'cases':cases,'results':results},
        {'output':str(tmp_path),'experiments':[experiment.id],'formats':['svg'],'conditions':False})
    assert len(paths)==1
    assert 'Experimental data only' in Path(paths[0]).read_text(encoding='utf-8')
