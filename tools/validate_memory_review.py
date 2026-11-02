"""Actual clear mechanism batch with bounded worker monitoring, separate output."""
import json
import threading
import time
from pathlib import Path
import psutil
from pyteck.respecth.models import RunConfig,file_hash
from pyteck.respecth.runner import run_project,load_run
from pyteck.respecth.coverage import dataset_coverage
from pyteck.respecth.atomic_io import atomic_json

ROOT=Path(__file__).resolve().parents[1]

def main():
    manifest_path=ROOT/'results/ui-run/manifest.json'; source_hash=file_hash(manifest_path)
    original=json.loads(manifest_path.read_text(encoding='utf-8'))
    config=RunConfig.from_dict(original['config'])
    config.datasets=[p for p in config.datasets if Path(p).stem in {'Shin_Yoo_2004_MIX1','Shin_Yoo_2004_MIX5'}]
    config.mechanisms=[m for m in config.mechanisms if m['id']=='clear_26092002']
    config.output=str(ROOT/'results/memory-review/batch'); config.grid={'enabled':False}; config.workers=2
    config.reuse_results=[]; config.figure={'formats':['png']}
    before={p:file_hash(p) for p in config.datasets}
    stop=threading.Event(); owner=psutil.Process(); samples=[]; start=time.monotonic()
    def monitor():
        while not stop.wait(.5):
            processes=[]
            for process in owner.children(recursive=True):
                try:
                    info=process.memory_info()
                    processes.append({'pid':process.pid,'rss_MiB':info.rss/2**20,'private_MiB':getattr(info,'private',info.rss)/2**20})
                except (psutil.NoSuchProcess,psutil.AccessDenied): pass
            samples.append({'seconds':time.monotonic()-start,'owner_rss_MiB':owner.memory_info().rss/2**20,'children':processes})
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try: manifest=run_project(config,force_rerun=True)
    finally: stop.set();thread.join()
    assert manifest['status']=='completed'
    assert all(result['status']=='success' for result in manifest['results'])
    assert all(file_hash(p)==value for p,value in before.items()) and file_hash(manifest_path)==source_hash
    _,experiments,cases,results=load_run(config.output)
    report={'cases':len(cases),'success':len(results),'workers':2,'elapsed_seconds':time.monotonic()-start,
        'peak_children_rss_MiB':max(sum(p['rss_MiB'] for p in sample['children']) for sample in samples),
        'owner_first_rss_MiB':samples[0]['owner_rss_MiB'],'owner_last_rss_MiB':samples[-1]['owner_rss_MiB'],
        'coverage':dataset_coverage(experiments,cases,results),'original_xml_and_batch_unchanged':True,'samples':samples}
    atomic_json(ROOT/'results/memory-review/actual-batch-validation.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=False))

if __name__=='__main__':main()
