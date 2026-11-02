"""Sequential diagnostic queue: one fresh solver process at a time."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

from .atomic_io import atomic_json
from .runner import project_root


def run_batch(path):
    path=Path(path).resolve(); directory=path.parent
    if not directory.is_relative_to(project_root()/'results/analysis-batches'):
        raise ValueError('Analysis batches must stay in project results/analysis-batches')
    jobs=json.loads(path.read_text(encoding='utf-8'))['jobs']
    statuses=[]; cancelled=False
    for i,item in enumerate(jobs):
        job=Path(item['job']).resolve()
        cached_project=job.is_relative_to(project_root()/'results/projects') and (job.parent/'report.json').is_file()
        if not job.is_relative_to(project_root()/'results/analysis') and not cached_project:
            raise ValueError('Analysis job outside project')
        if (directory/'CANCEL').exists(): cancelled=True; break
        report_path=job.parent/'report.json'
        saved=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        if saved.get('status')=='completed':
            statuses.append({'directory':str(job.parent),'status':'completed','cached':True});continue
        if cached_project: raise ValueError('Saved project analysis is read-only; use a new temporary job')
        (job.parent/'CANCEL').unlink(missing_ok=True)
        with (job.parent/'analysis.log').open('wb') as log:
            child=subprocess.Popen([sys.executable,'-m','pyteck.respecth.analysis_job',str(job)],
                cwd=project_root(),stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        cancel_time=None
        try:
            while child.poll() is None:
                active={}
                progress=job.parent/'progress.json'
                if progress.exists():
                    try: active=json.loads(progress.read_text(encoding='utf-8'))
                    except (OSError,ValueError): pass
                fraction=active.get('done',0)/max(active.get('total',1),1)
                atomic_json(directory/'progress.json',{'done':i+min(fraction,.99),'total':len(jobs),
                    'message':f"{i+1}/{len(jobs)} · {item['label']} · {active.get('message','启动分析')}"})
                if (directory/'CANCEL').exists():
                    cancelled=True;(job.parent/'CANCEL').touch()
                    if cancel_time is None: cancel_time=time.monotonic()
                    if time.monotonic()-cancel_time>30:
                        import psutil
                        process=psutil.Process(child.pid)
                        for descendant in process.children(recursive=True):
                            try: descendant.terminate()
                            except psutil.NoSuchProcess: pass
                        child.terminate();child.wait(timeout=10)
                        saved=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
                        saved.update(status='cancelled',reason='Cancelled after graceful shutdown deadline')
                        atomic_json(report_path,saved)
                        break
                time.sleep(.5)
        finally:
            if child.poll() is None: child.terminate();child.wait(timeout=10)
        saved=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        statuses.append({'directory':str(job.parent),'status':saved.get('status','failed'),'cached':False})
        if cancelled: break
    report={'status':'cancelled' if cancelled else 'completed',
            'analysis_directories':[s['directory'] for s in statuses if s['status']=='completed'],
            'jobs':statuses,'total':len(jobs),'pending':len(jobs)-len(statuses)}
    atomic_json(directory/'report.json',report)
    atomic_json(directory/'progress.json',{'done':len(statuses),'total':len(jobs),
        'message':f"完成 {sum(s['status']=='completed' for s in statuses)}/{len(jobs)}；"
                  f"失败/取消 {sum(s['status']!='completed' for s in statuses)}；未开始 {report['pending']}"})
    return report


if __name__=='__main__':
    run_batch(sys.argv[1])
