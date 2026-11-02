"""Bounded cleanup of reproducible artifacts; numerical results are never targets."""
from pathlib import Path
import gc
import hashlib
import os
import re
import time

LABELS={'obsolete':'失效预览与过期下载临时文件（自动）',
        'previews':'可复用图片预览（下次查看重新生成）',
        'archives':'下载 ZIP 副本（原结果不变，下次下载重新打包）',
        'development':'开发与测试缓存（测试临时目录、wheel 检查副本）'}


def contained(root,path):
    root=Path(root).resolve();path=Path(path)
    if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
        raise ValueError(f'Cache path escapes project or is a link: {path}')
    for parent in path.parents:
        if parent==root: break
        if parent.is_symlink() or parent.is_junction(): raise ValueError('Linked cache parent')
    return path


def files_under(root):
    root=Path(root)
    if not root.exists() or root.is_symlink() or root.is_junction(): return
    for folder,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(folder)/d).is_symlink() and not (Path(folder)/d).is_junction()]
        for name in files:
            path=Path(folder)/name
            if not path.is_symlink(): yield path


def inventory(root):
    root=Path(root).resolve();items=[];errors=[];now=time.time()
    def add(path,category):
        try:
            contained(root,path)
            stat=path.stat()
            items.append({'path':str(path),'category':category,'bytes':stat.st_size,
                          'mtime_ns':stat.st_mtime_ns,'links':stat.st_nlink})
        except (OSError,ValueError) as error: errors.append(str(error))
    # Never scan environments, input mechanisms or numerical histories as caches.
    preview_valid={}
    import itertools
    for path in itertools.chain(files_under(root/'results'),files_under(root/'.cache/sessions')):
        try:
            if path.parent.name=='.previews' and re.fullmatch(r'[0-9a-f]{64}\.png',path.name):
                directory=path.parent
                if directory not in preview_valid:
                    valid=set()
                    for original in directory.parent.glob('*.png'):
                        stat=original.stat()
                        for side in (1200,1400):
                            key=f'{original.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{side}'
                            valid.add(hashlib.sha256(key.encode()).hexdigest()+'.png')
                    preview_valid[directory]=valid
                add(path,'previews' if path.name in preview_valid[directory] else 'obsolete')
            elif path.name in {'results.zip','download.zip','case-analysis.zip'}:
                add(path,'archives')
            elif path.name in {'results.zip.tmp','download.zip.tmp','case-analysis.zip.tmp'} and now-path.stat().st_mtime>86400:
                add(path,'obsolete')
        except OSError as error: errors.append(str(error))
    for name in ('tmp','wheel-install','analysis-trajectories'):
        try:
            for path in files_under(root/'.cache'/name): add(path,'development')
        except OSError as error: errors.append(str(error))
    return {'items':items,'errors':errors}


def busy_reasons(root):
    import psutil
    from .run_ownership import run_owner
    root=Path(root).resolve();reasons=[]
    for base in (root/'results',root/'.cache/sessions'):
        for lock in base.rglob('run.lock'):
            if run_owner(lock.parent)['active']: reasons.append(f'批量计算：{lock.parent.name}')
    for process in psutil.process_iter(['pid','cmdline','cwd']):
        try:
            args=process.info['cmdline'] or []
            if not any(a in {'pyteck.respecth.analysis_job','pyteck.respecth.analysis_batch_job','pytest','build'} or a.endswith('package_smoke.py') for a in args): continue
            if Path(process.info['cwd'] or '.').resolve()==root or any(str(root).lower() in a.lower() for a in args):
                reasons.append(f'分析 / 开发任务 PID {process.pid}')
        except (psutil.Error,OSError): pass
    return reasons


def cleanup(root,categories=('obsolete',),*,snapshot=None):
    root=Path(root).resolve();categories=set(categories)
    if categories-set(LABELS): raise ValueError('Unknown cache category')
    reasons=busy_reasons(root)
    if reasons: return {'deleted':0,'bytes':0,'blocked':reasons,'errors':[]}
    report={'deleted':0,'bytes':0,'blocked':[],'errors':[]}
    # Re-scan at action time. An old GUI inventory never authorizes a new target.
    current=inventory(root)
    expected={i['path']:i for i in (snapshot or current)['items']}
    report['errors'].extend(current['errors'])
    for item in current['items']:
        if item['category'] not in categories or item['path'] not in expected: continue
        prior=expected[item['path']]
        if (item['mtime_ns'],item['bytes'],item['category'])!=(prior['mtime_ns'],prior['bytes'],prior['category']): continue
        try:
            path=contained(root,item['path']);stat=path.stat()
            if (stat.st_mtime_ns,stat.st_size)!=(item['mtime_ns'],item['bytes']): continue
            path.unlink()
            report['deleted']+=1
            # Hard links need not release their apparent file size.
            if stat.st_nlink==1: report['bytes']+=stat.st_size
        except (OSError,ValueError) as error: report['errors'].append(str(error))
    return report


MEMORY_KEYS=('loaded_run','progress_manifest','progress_manifest_stamp','latest_case_result',
    'prepared_cases','analysis_cache_plan','analysis_cache_plan_signature','analysis_auto_selection',
    'workload','workload_plan','workload_signature','precheck_report','run_config','checked_text',
    'loaded_output','loaded_work_output','result_load_notice','result_load_directory','analysis_directories',
    'analysis_directory','analysis_comparison_view','pending_result_output','opened_project_directory')


def release_views(state):
    worker=state.get('worker');analysis=state.get('analysis_process')
    if (worker and worker.is_alive()) or (analysis and analysis.poll() is None):
        raise ValueError('计算中不能释放当前任务视图')
    removed=[key for key in MEMORY_KEYS if key in state]
    for key in removed: state.pop(key,None)
    state['result_view_restored']=True
    from .inlet_properties import _atoms
    _atoms.cache_clear()
    gc.collect()
    return len(removed)
