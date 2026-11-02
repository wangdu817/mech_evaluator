import json
import os
import threading
from unittest.mock import patch
from pyteck.respecth.run_ownership import run_owner, restore_run_state, cancel_run


def test_refresh_reconnects_and_can_cancel_without_session_event(tmp_path):
    stop=threading.Event()
    worker=threading.Thread(target=lambda:stop.wait(20),daemon=True)
    worker.start()
    lock=tmp_path/'run.lock'
    lock.write_text(json.dumps({'pid':os.getpid(),'thread':worker.ident}))
    original=lock.read_bytes()
    try:
        fresh={}
        assert restore_run_state(fresh,tmp_path)
        assert fresh['worker'] is worker
        assert 'cancellation' not in fresh
        assert cancel_run(tmp_path)
        assert (tmp_path/'CANCEL').exists()
        assert lock.read_bytes()==original
    finally:
        stop.set();worker.join(2)
    assert not restore_run_state({},tmp_path)
    assert lock.read_bytes()==original


def test_other_process_and_unknown_owner_block_start(tmp_path):
    lock=tmp_path/'run.lock'
    lock.write_text(json.dumps({'pid':999999,'thread':1}))
    with patch('pyteck.respecth.run_ownership.psutil.pid_exists',return_value=True):
        assert restore_run_state({},tmp_path)
    with patch('pyteck.respecth.run_ownership.psutil.pid_exists',return_value=False):
        assert not restore_run_state({},tmp_path)
    lock.write_text('')
    assert run_owner(tmp_path)['unknown'] and restore_run_state({},tmp_path)
    lock.unlink()
    assert not restore_run_state({},tmp_path)


def test_refreshed_gui_disables_start_and_enables_cancel(tmp_path):
    from streamlit.testing.v1 import AppTest
    lock=tmp_path/'run.lock'
    lock.write_text(json.dumps({'pid':os.getpid(),'thread':threading.get_ident()}))
    app=AppTest.from_function(ownership_controls,args=(str(tmp_path),)).run()
    assert not app.exception
    assert app.button[0].disabled and not app.button[1].disabled
    app.button[1].click().run()
    assert not app.exception
    assert (tmp_path/'CANCEL').exists()


def ownership_controls(output):
    import streamlit as st
    from pyteck.respecth.run_ownership import restore_run_state, cancel_run
    active=restore_run_state(st.session_state,output)
    st.button('运行 / 恢复',disabled=active)
    if st.button('取消运行',disabled=not active): cancel_run(output)
