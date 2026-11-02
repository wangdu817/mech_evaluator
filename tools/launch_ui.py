"""Double-click launcher: detach local Streamlit and reuse this project's service."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'src/pyteck/respecth/app.py'
SOURCE=ROOT/'src'
# Pin both this interpreter and all spawned workers to the launcher's own tree.
sys.path.insert(0,str(SOURCE))
os.environ['PYTHONPATH']=str(SOURCE)+os.pathsep+os.environ.get('PYTHONPATH','')


def source_revision():
    paths=[p for p in (SOURCE/'pyteck').rglob('*') if p.suffix in {'.py','.json'}]
    paths += [Path(__file__), ROOT/'start.ps1']
    checksum=hashlib.sha256()
    for path in sorted(paths):
        checksum.update(str(path.relative_to(ROOT)).encode('utf-8'))
        checksum.update(path.read_bytes())
    return checksum.hexdigest()


def service_needs_reload(pid):
    import psutil
    state_path=ROOT/'results/runtime/server.json'
    try:
        state=json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('pid')==pid and state.get('source_revision'):
            return state['source_revision']!=source_revision()
    except (OSError,ValueError): pass
    started=psutil.Process(pid).create_time()
    return any(p.stat().st_mtime>started for p in SOURCE.rglob('*') if p.suffix in {'.py','.json'})


def restart_blockers(pid):
    import psutil
    from pyteck.respecth.cache_maintenance import busy_reasons
    process=psutil.Process(pid)
    reasons=busy_reasons(ROOT)
    workspace=process.environ().get('PYTECK_WORKSPACE')
    if workspace and Path(workspace).resolve()!=ROOT:
        reasons+=busy_reasons(Path(workspace))
    if process.children(recursive=True): reasons.append('服务仍有计算子进程')
    return reasons


def project_service(port):
    import psutil
    for connection in psutil.net_connections(kind='tcp'):
        if connection.status!='LISTEN' or connection.laddr.port!=port or not connection.pid:continue
        try:
            process=psutil.Process(connection.pid)
            arguments=process.cmdline()
            if 'streamlit' not in arguments or 'run' not in arguments:continue
            index=arguments.index('run')
            target=Path(arguments[index+1])
            if not target.is_absolute():target=Path(process.cwd())/target
            if target.resolve()==APP.resolve():return connection.pid
        except (psutil.Error,IndexError,OSError):continue
    return None


def free_port(port):
    with socket.socket() as stream:
        try:stream.bind(('127.0.0.1',port));return True
        except OSError:return False


def healthy(port):
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/_stcore/health',timeout=1) as response:
            return response.status==200 and response.read().strip()==b'ok'
    except OSError:return False


def launch(port=8502,no_browser=False):
    if not APP.is_file():raise RuntimeError(f'找不到界面文件：{APP}')
    ports=list(dict.fromkeys([port,8502,8503,8501,*range(port,min(port+10,65536))]))
    for candidate in ports:
        pid=project_service(candidate)
        if pid:
            if service_needs_reload(pid):
                blockers=restart_blockers(pid)
                if not blockers:
                    import psutil
                    print('检测到程序代码更新，正在重启空闲服务以加载新版本…')
                    process=psutil.Process(pid)
                    workspace=process.environ().get('PYTECK_WORKSPACE')
                    if workspace: os.environ['PYTECK_WORKSPACE']=workspace
                    process.terminate();process.wait(timeout=15)
                    continue
                print('检测到代码更新，当前任务保留；任务结束后再次一键启动以更新：'+'；'.join(blockers))
            url=f'http://127.0.0.1:{candidate}/'
            print(f'界面已运行，复用现有服务（PID {pid}）：{url}')
            if not no_browser:webbrowser.open(url)
            return {'pid':pid,'port':candidate,'url':url,'reused':True}
    selected=next((p for p in ports if free_port(p)),None)
    if selected is None:raise RuntimeError('可选端口均被占用，请使用 start.ps1 -Port 指定其他端口。')
    runtime=ROOT/'results/runtime';runtime.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    log=runtime/f'streamlit-{stamp}.log'
    arguments=[sys.executable,'-m','streamlit','run',str(APP),'--server.address','127.0.0.1',
               '--server.port',str(selected),'--server.headless','true','--server.fileWatcherType','none',
               '--browser.gatherUsageStats','false']
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
    with log.open('wb') as stream:
        process=subprocess.Popen(arguments,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,
                                 stderr=subprocess.STDOUT,creationflags=flags,start_new_session=os.name!='nt')
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError(f'启动失败，请查看日志：{log}')
        listener=project_service(selected)
        if healthy(selected) and listener:
            import psutil
            owned={process.pid,*[p.pid for p in psutil.Process(process.pid).children(recursive=True)]}
            if listener in owned:break
        time.sleep(.5)
    else:
        # Keep a slow-starting service alive; never terminate a computation.
        raise RuntimeError(f'服务启动尚未就绪（PID {process.pid}），请稍后访问 http://127.0.0.1:{selected}/；日志：{log}')
    state={'pid':listener,'launcher_child_pid':process.pid,'port':selected,'url':f'http://127.0.0.1:{selected}/','log':str(log),'reused':False,
           'source_revision':source_revision(),'source_directory':str(SOURCE),'python':sys.executable}
    (runtime/'server.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"启动成功：{state['url']}")
    print('程序在后台运行；关闭启动窗口不会停止计算。')
    print(f'本次服务日志：{log}')
    if not no_browser:webbrowser.open(state['url'])
    return state


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8502)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('port must be between 1024 and 65535')
    try:
        import streamlit,cantera,psutil
        import pyteck.respecth
        if args.check:
            if not APP.is_file():raise RuntimeError('Missing app.py')
            print(f'启动检查通过：Python {sys.version.split()[0]} / Streamlit {streamlit.__version__} / Cantera {cantera.__version__}')
            print(f'实际程序源码：{Path(pyteck.__file__).resolve()}')
            return 0
        launch(args.port,args.no_browser)
        return 0
    except Exception as error:
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
