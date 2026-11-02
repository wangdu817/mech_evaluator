"""Observe native process memory over actual clear ignition cases and pool recycling."""
from pathlib import Path
import json
import threading
import time
import psutil
from pyteck.respecth.models import RunConfig
from pyteck.respecth.runner import run_project

ROOT=Path(__file__).resolve().parents[1]

def main():
    original=json.loads((ROOT/'results/ui-run/manifest.json').read_text(encoding='utf-8'))
    config=RunConfig.from_dict(original['config'])
    config.datasets=[p for p in config.datasets if Path(p).stem in {'Shin_Yoo_2004_MIX1','Shin_Yoo_2004_MIX5'}]
    config.output=str(ROOT/'results/memory-fix/batch');config.grid={'enabled':False};config.workers=2
    config.reuse_results=[];config.figure={'formats':['png']}
    stop=threading.Event();samples=[]
    owner=psutil.Process()
    def monitor():
        while not stop.wait(.5):
            members=[]
            for process in owner.children(recursive=True):
                try:
                    mem=process.memory_info()
                    members.append({'pid':process.pid,'rss_MiB':round(mem.rss/2**20,1),'private_MiB':round(getattr(mem,'private',mem.vms)/2**20,1)})
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            samples.append({'seconds':round(time.monotonic()-start,2),'owner_rss_MiB':round(owner.memory_info().rss/2**20,1),'children':members})
    start=time.monotonic();thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
        manifest=run_project(config,force_rerun=True)
    finally:
        stop.set();thread.join()
    report={'cases':len(manifest['cases']),'success':sum(r['status']=='success' for r in manifest['results']),
            'elapsed_seconds':round(time.monotonic()-start,2),'worker_pids':sorted({p['pid'] for s in samples for p in s['children']}),
            'max_total_children_rss_MiB':max((sum(p['rss_MiB'] for p in s['children']) for s in samples),default=0),
            'max_total_children_private_MiB':max((sum(p['private_MiB'] for p in s['children']) for s in samples),default=0),
            'owner_rss_first_MiB':samples[0]['owner_rss_MiB'],'owner_rss_last_MiB':samples[-1]['owner_rss_MiB'],
            'progress_bytes':(Path(config.output)/'progress.json').stat().st_size,'samples':samples}
    assert manifest['status']=='completed'
    assert len(report['worker_pids'])>=4, 'Expected drained pool recycling across actual cases'
    assert report['progress_bytes']<100000
    (ROOT/'results/memory-fix/batch-memory-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=False))

if __name__=='__main__':main()
