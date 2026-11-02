import json
from pathlib import Path
from unittest.mock import patch
import pytest
from pyteck.respecth import project_storage as storage


def saved_fixture(root):
    workspace=storage.new_session(root)
    run=workspace/'simulation';run.mkdir()
    (run/'cache').mkdir();history=run/'cache/case.h5';history.write_bytes(b'actual-history-bytes')
    (run/'prepared').mkdir();mechanism=run/'prepared/gas.yaml';mechanism.write_text('phases: []')
    (run/'inputs').mkdir();(run/'inputs/set.xml').write_text('<experiment/>')
    (run/'figures').mkdir();(run/'figures/set.png').write_bytes(b'figure')
    case={'id':'case','mechanism':{'id':'gas','path':str(mechanism),'sha256':'chemistry','species':['OH']}}
    manifest={'status':'completed','cases':[case],'results':[{'history_path':str(history)}],
        'config':{'output':str(run)}}
    (run/'manifest.json').write_text(json.dumps(manifest))
    analysis=storage.analysis_destination(root,{'session_workspace':str(workspace)},'analysis','sample')
    analysis.mkdir(parents=True);matrix=analysis/'all_species_sensitivity.h5';matrix.write_bytes(b'matrix')
    (analysis/'report.json').write_text(json.dumps({'status':'completed','case':case,
        'sensitivity':{'all_species_path':str(matrix)},'source_run':str(run)}))
    (analysis/'job.json').write_text(json.dumps({'case':case,'result':{'history_path':str(history)}}))
    return workspace,run,analysis


def test_new_session_unsaved_and_component_paths_preserve_guard(tmp_path):
    workspace,run,analysis=saved_fixture(tmp_path)
    assert workspace.is_relative_to(tmp_path/'.cache/sessions')
    assert not (tmp_path/'results/projects').exists()
    info=json.loads((workspace/'session.json').read_text())
    assert info['temporary'] and str(analysis) in info['components']
    assert analysis.is_relative_to(tmp_path/'results/analysis')


def test_save_copies_and_rewrites_all_dependencies(tmp_path):
    _,run,analysis=saved_fixture(tmp_path)
    with patch.object(storage,'busy_reasons',return_value=[]):
        saved=storage.save_project(tmp_path,'甲胺项目',run_output=run,analyses=[analysis],config={'output':str(run)})
    manifest=json.loads((saved/'simulation/manifest.json').read_text())
    assert Path(manifest['results'][0]['history_path']).read_bytes()==b'actual-history-bytes'
    assert Path(manifest['cases'][0]['mechanism']['path']).is_relative_to(saved)
    report=json.loads((saved/'analysis/000/report.json').read_text())
    assert Path(report['sensitivity']['all_species_path']).is_relative_to(saved)
    assert (saved/'simulation/figures/set.png').exists()
    assert (run/'cache/case.h5').read_bytes()==b'actual-history-bytes'
    with patch.object(storage,'busy_reasons',return_value=[]):
        with pytest.raises(ValueError,match='已存在'):
            storage.save_project(tmp_path,'甲胺项目')


def test_analysis_only_save_materializes_external_history_and_mechanism(tmp_path):
    _,run,analysis=saved_fixture(tmp_path)
    with patch.object(storage,'busy_reasons',return_value=[]):
        saved=storage.save_project(tmp_path,'分析',run_output=run,analyses=[analysis],
            include_results=False,include_figures=False)
    assert not (saved/'simulation').exists()
    job=json.loads((saved/'analysis/000/job.json').read_text())
    assert Path(job['result']['history_path']).read_bytes()==b'actual-history-bytes'
    assert Path(job['case']['mechanism']['path']).is_relative_to(saved/'dependencies')
    assert not list(saved.rglob('*.png'))
    assert Path(job['case']['mechanism']['path']).read_bytes()==(run/'prepared/gas.yaml').read_bytes()


def test_clear_unsaved_session_keeps_self_contained_saved_analysis(tmp_path):
    workspace,run,analysis=saved_fixture(tmp_path)
    with patch.object(storage,'busy_reasons',return_value=[]):
        saved=storage.save_project(tmp_path,'保留',analyses=[analysis],include_results=False)
        count=storage.discard_sessions(tmp_path,[str(workspace)])
    assert count==2 and not workspace.exists() and not analysis.exists()
    report=json.loads((saved/'analysis/000/report.json').read_text())
    job=json.loads((saved/'analysis/000/job.json').read_text())
    assert Path(report['sensitivity']['all_species_path']).read_bytes()==b'matrix'
    assert Path(job['result']['history_path']).read_bytes()==b'actual-history-bytes'


def test_cleanup_refuses_current_and_other_result_references(tmp_path):
    workspace,run,analysis=saved_fixture(tmp_path)
    with patch.object(storage,'busy_reasons',return_value=[]):
        with pytest.raises(ValueError,match='当前仍在使用'):
            storage.discard_sessions(tmp_path,[str(workspace)],protected=[run])
        other=tmp_path/'results/other';other.mkdir()
        (other/'manifest.json').write_text(json.dumps({'results':[{'history_path':str(run/'cache/case.h5')}]}))
        with pytest.raises(ValueError,match='仍引用'):
            storage.discard_sessions(tmp_path,[str(workspace)])
    assert workspace.exists() and analysis.exists()


def test_failure_leaves_no_half_project_or_source_changes(tmp_path):
    _,run,analysis=saved_fixture(tmp_path)
    (run/'cache/case.h5').unlink()
    with patch.object(storage,'busy_reasons',return_value=[]):
        with pytest.raises(ValueError,match='依赖缺失'):
            storage.save_project(tmp_path,'broken',analyses=[analysis],include_results=False)
    assert not (tmp_path/'results/projects/broken').exists()
    assert not list((tmp_path/'results/projects').glob('.saving-*'))
    with patch.object(storage,'busy_reasons',return_value=['active']):
        with pytest.raises(ValueError,match='运行中'): storage.save_project(tmp_path,'busy')
    with pytest.raises(ValueError): storage.save_project(tmp_path,'../bad')


def project_app(root):
    import streamlit as st
    from pathlib import Path
    from pyteck.respecth.ui_projects import render_project_controls
    st.session_state.setdefault('project_controls',True)
    render_project_controls(Path(root))


def test_gui_explicit_save_and_no_implicit_project(tmp_path):
    from streamlit.testing.v1 import AppTest
    with patch.object(storage,'busy_reasons',return_value=[]):
        app=AppTest.from_function(project_app,args=(str(tmp_path),),default_timeout=30).run()
        assert not app.exception and not (tmp_path/'results/projects').exists()
        app.text_input(key='project_save_name').set_value('GUI项目').run()
        next(b for b in app.button if b.label=='保存项目').click().run()
        assert not app.exception and (tmp_path/'results/projects/GUI项目/project.json').exists()
        assert any('保存成功' in s.value for s in app.success)
        next(b for b in app.button if b.label=='打开所选项目').click().run()
        assert not app.exception and '项目已打开' in app.session_state['project_notice']


def full_app(root):
    import streamlit as st
    st.session_state['workspace_root'] = str(root)
    from pathlib import Path
    from unittest.mock import patch
    from pyteck.respecth import app
    import os
    with patch.dict(os.environ), patch.object(app,'project_root',return_value=Path(root)):
        app.main()


def test_gui_default_session_has_no_saved_results(tmp_path):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_function(full_app,args=(str(tmp_path),),default_timeout=60).run()
    assert not app.exception
    workspace=Path(app.session_state['session_workspace'])
    assert workspace.is_relative_to(tmp_path/'.cache/sessions')
    assert not (tmp_path/'results/projects').exists()
    assert Path(app.session_state['output']).is_relative_to(workspace)
    assert not any(w.label=='结果子目录' for w in app.text_input)


def test_figures_only_keeps_analysis_charts_without_numeric_results(tmp_path):
    _,run,analysis=saved_fixture(tmp_path)
    charts=analysis/'views';charts.mkdir();(charts/'sensitivity.svg').write_text('<svg/>')
    with patch.object(storage,'busy_reasons',return_value=[]):
        saved=storage.save_project(tmp_path,'仅图表',run_output=run,analyses=[analysis],
            include_results=False,include_analysis=False,include_figures=True)
    assert (saved/'figures/set.png').exists()
    assert (saved/'analysis-figures/000/views/sensitivity.svg').exists()
    assert not list(saved.rglob('*.h5')) and not (saved/'simulation').exists()


def figure_project_app(root):
    import streamlit as st
    from pathlib import Path
    from pyteck.respecth.ui_projects import render_project_figures
    st.session_state['opened_project_directory']=str(Path(root)/'results/projects/charts')
    st.session_state['session_workspace']=str(Path(root)/'.cache/sessions/test')
    render_project_figures()


def test_gui_figures_only_project_previews_are_temporary(tmp_path):
    from PIL import Image
    from streamlit.testing.v1 import AppTest
    source=tmp_path/'results/projects/charts/figures';source.mkdir(parents=True)
    Image.new('RGB',(20,20),'white').save(source/'curve.png')
    app=AppTest.from_function(figure_project_app,args=(str(tmp_path),),default_timeout=30).run()
    assert not app.exception
    assert not (source/'.previews').exists()
    assert list((tmp_path/'.cache/sessions/test').rglob('.previews'))


def test_temporary_run_snapshot_stays_inside_session(tmp_path):
    from pyteck.respecth import live_snapshot
    workspace,run,_=saved_fixture(tmp_path)
    data=json.loads((run/'manifest.json').read_text())
    data.update(created_utc='2026-10-19',status='running',results=[{'case_id':'case','status':'invalid_input'}])
    (run/'manifest.json').write_text(json.dumps(data))
    with patch.object(live_snapshot,'project_root',return_value=tmp_path):
        snapshot=live_snapshot.create_completed_snapshot(run)
    assert snapshot.is_relative_to(workspace/'snapshots')
    assert not (tmp_path/'results/live-snapshots').exists()


def test_save_preserves_existing_review_certificate_for_legacy_analysis(tmp_path):
    from pyteck.respecth.models import file_hash
    _,_,analysis=saved_fixture(tmp_path)
    (tmp_path/'results/analysis-reuse-index.json').write_text(json.dumps({file_hash(analysis/'report.json'):'reviewed-signature'}))
    with patch.object(storage,'busy_reasons',return_value=[]):
        saved=storage.save_project(tmp_path,'审计分析',analyses=[analysis],include_results=False)
    report=json.loads((saved/'analysis/000/report.json').read_text())
    assert report['numeric_signature']=='reviewed-signature'
    assert 'numeric_signature' not in json.loads((analysis/'report.json').read_text())
