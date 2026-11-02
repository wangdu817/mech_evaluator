import json
import os
import threading
import time
from unittest.mock import patch
import pytest
from PIL import Image
from pyteck.respecth import cache_maintenance as cm
from pyteck.respecth.ui_artifacts import preview_image


def fixture(root):
    folder=root/'results/batch/figures';folder.mkdir(parents=True)
    image=folder/'curve.png';Image.new('RGB',(20,20),'white').save(image)
    old=preview_image(image,1200)
    stamp=image.stat().st_mtime_ns
    os.utime(image,ns=(stamp+1000000,stamp+1000000))
    current=preview_image(image,1200)
    for name in ('cache/case.h5','cache/case.json','manifest.json','prepared/mech.yaml',
                 'inputs/frozen.xml','figures/curve.pdf','results.zip','results.zip.tmp'):
        path=root/'results/batch'/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'preserve')
    temporary=root/'results/batch/results.zip.tmp'
    os.utime(temporary,(time.time()-90000,)*2)
    matrix=root/'results/analysis/job/all_species_sensitivity.h5'
    matrix.parent.mkdir(parents=True);matrix.write_bytes(b'matrix')
    snapshot=root/'results/live-snapshots/token/h/case.h5'
    snapshot.parent.mkdir(parents=True);snapshot.write_bytes(b'history')
    wheel=root/'.cache/wheel-install/test.py';wheel.parent.mkdir(parents=True);wheel.write_text('build cache')
    return old,current,temporary


def test_auto_only_obsolete_and_manual_reusable(tmp_path):
    old,current,temporary=fixture(tmp_path)
    numerical={str(p):p.read_bytes() for p in (tmp_path/'results').rglob('*')
               if p.is_file() and (p.suffix in {'.h5','.json','.xml','.yaml','.pdf'})}
    with patch.object(cm,'busy_reasons',return_value=[]):
        report=cm.cleanup(tmp_path)
        assert report['deleted']==2
        assert not os.path.exists(old) and not temporary.exists()
        assert os.path.exists(current)
        assert (tmp_path/'results/batch/results.zip').exists()
        report=cm.cleanup(tmp_path,['previews','archives','development'])
        assert report['deleted']==3
    assert all(open(p,'rb').read()==value for p,value in numerical.items())


def test_busy_blocks_all_and_changed_files_not_deleted(tmp_path):
    _,current,_=fixture(tmp_path)
    with patch.object(cm,'busy_reasons',return_value=['active']):
        assert cm.cleanup(tmp_path,['previews'])['blocked']==['active']
    before=cm.inventory(tmp_path)
    with open(current,'ab') as stream: stream.write(b'changed')
    with patch.object(cm,'busy_reasons',return_value=[]):
        cm.cleanup(tmp_path,['previews'],snapshot=before)
    assert os.path.exists(current)
    with pytest.raises(ValueError): cm.contained(tmp_path,tmp_path.parent/'outside')
    with pytest.raises(ValueError): cm.cleanup(tmp_path,['simulations'])


def test_actual_live_owner_prevents_cleanup(tmp_path):
    lock=tmp_path/'results/batch/run.lock';lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({'pid':os.getpid(),'thread':threading.get_ident()}))
    assert any('批量' in r for r in cm.busy_reasons(tmp_path))
    assert cm.cleanup(tmp_path)['blocked']


def test_release_only_views_and_keep_task_controls():
    state={'loaded_run':object(),'analysis_cache_plan':[{}],'worker':None,
           'config_text':'saved config','confirmed':True}
    assert cm.release_views(state)==2
    assert state['config_text']=='saved config' and state['worker'] is None
    assert state['result_view_restored']
    class Worker:
        def is_alive(self): return True
    state['worker']=Worker();state['loaded_run']='in use'
    with pytest.raises(ValueError): cm.release_views(state)
    assert state['loaded_run']=='in use'


def cache_app(root):
    import streamlit as st
    from pathlib import Path
    from pyteck.respecth.ui_cache import render_cache_controls
    st.session_state.setdefault('cache_controls',True)
    render_cache_controls(Path(root))


def test_gui_reports_success_and_releases_views(tmp_path):
    from streamlit.testing.v1 import AppTest
    fixture(tmp_path)
    with patch.object(cm,'busy_reasons',return_value=[]):
        app=AppTest.from_function(cache_app,args=(str(tmp_path),),default_timeout=30).run()
        assert not app.exception
        next(b for b in app.button if b.label=='检查缓存占用').click().run()
        assert not app.exception and len(app.dataframe)==1
        next(b for b in app.button if b.label=='清理所选缓存').click().run()
        assert not app.exception and any('清理完成' in s.value for s in app.success)
        app.session_state['loaded_run']='view'
        next(b for b in app.button if b.label=='释放当前载入结果的内存').click().run()
        assert not app.exception
        assert any('已卸载' in s.value for s in app.info)
