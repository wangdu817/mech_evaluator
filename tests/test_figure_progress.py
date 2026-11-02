from pathlib import Path
from unittest.mock import patch
import pytest
from pyteck.respecth.reader import load_experiment
from pyteck.respecth import reporting


def test_actual_datasets_report_stages_and_build_comparison_once(tmp_path):
    root=Path(__file__).resolve().parents[1]
    paths=sorted((root.parent/'exp1').glob('*.xml'))[:2]
    if len(paths)<2: pytest.skip('Actual XML unavailable')
    experiments=[load_experiment(p) for p in paths]
    events=[]
    with patch.object(reporting,'comparison_rows',wraps=reporting.comparison_rows) as compare:
        files=reporting.render_figures(experiments,{'cases':[],'results':[]},
            {'output':str(tmp_path),'formats':['png'],'conditions':False},
            progress=lambda *event:events.append(event))
    assert compare.call_count==1
    assert len(files)==2 and all(Path(f).is_file() for f in files)
    assert events[0][:2]==(0,2) and events[-1][:2]==(2,2)
    assert [e[0] for e in events]==sorted(e[0] for e in events)
    assert all(e[1]==2 for e in events)
    for path in paths:
        assert any(path.name in e[2] and '绘制' in e[2] for e in events)
        assert any(path.name in e[2] and 'PNG' in e[2] for e in events)


def test_macro_progress_counts_figures_not_files_or_datasets(tmp_path):
    root=Path(__file__).resolve().parents[1]
    paths=sorted((root.parent/'exp4').glob('*.xml'))[:2]
    if len(paths)<2: pytest.skip('Actual XML unavailable')
    events=[]
    files=reporting.render_figures([load_experiment(p) for p in paths],{'cases':[],'results':[]},
        {'output':str(tmp_path),'formats':['png','svg'],'conditions':False,'macro_layout':'subplots'},
        progress=lambda *e:events.append(e))
    assert len(files)==2 and events[-1][:2]==(1,1)
    assert all(e[1]==1 for e in events)
    assert all(any(p.name in e[2] for e in events) for p in paths)


def test_export_failure_never_reports_completed(tmp_path):
    root=Path(__file__).resolve().parents[1]
    experiment=load_experiment(root/'examples/respecth/synthetic-pfr.xml')
    events=[]
    with patch.object(reporting,'_save_figure',side_effect=OSError('export failed')):
        with pytest.raises(OSError,match='export failed'):
            reporting.render_figures([experiment],{'cases':[],'results':[]},{'output':str(tmp_path)},
                progress=lambda *e:events.append(e))
    assert not any(e[0]==e[1] for e in events)
    reporting.plt.close('all')
