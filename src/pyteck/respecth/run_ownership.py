"""Read persistent writer ownership without changing locks or saved results."""
import json
import os
from pathlib import Path
import threading
import psutil


def run_owner(output):
    if not output:
        return {'active': False, 'thread': None, 'unknown': False}
    lock=Path(output)/'run.lock'
    try:
        data=json.loads(lock.read_text(encoding='utf-8'))
        pid=int(data['pid']);identity=int(data['thread'])
        if pid==os.getpid():
            thread=next((t for t in threading.enumerate() if t.ident==identity and t.is_alive()),None)
            return {'active':thread is not None,'thread':thread,'unknown':False}
        return {'active':psutil.pid_exists(pid),'thread':None,'unknown':False}
    except FileNotFoundError:
        return {'active':False,'thread':None,'unknown':False}
    except (OSError,ValueError,KeyError,TypeError):
        # A lock can be observed between exclusive creation and writing its owner.
        return {'active':True,'thread':None,'unknown':True}


def restore_run_state(state, output):
    """Reconnect a refreshed session to its existing background writer."""
    owner=run_owner(output)
    worker=state.get('worker')
    active=owner['active'] or bool(worker and worker.is_alive())
    if owner['active']:
        state['output']=str(Path(output).resolve())
        if owner['thread'] is not None:
            state['worker']=owner['thread']
    return active


def cancel_run(output):
    if not output or not run_owner(output)['active']:
        return False
    (Path(output)/'CANCEL').touch()
    return True
