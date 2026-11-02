"""Short idle observation of this project's 8502 UI only."""
import json
import time
from pathlib import Path
import psutil
from pyteck.respecth.atomic_io import atomic_json

root=Path(__file__).resolve().parents[1]
def main():
    processes=[]
    for process in psutil.process_iter(['cmdline']):
        command=' '.join(process.info['cmdline'] or [])
        if 'streamlit' in command and '8502' in command and str(root).lower() in command.lower():
            processes.append(process)
    process=max(processes,key=lambda p:p.memory_info().rss)
    samples=[]
    for index in range(121):
        info=process.memory_info()
        samples.append({'seconds':index*.5,'rss_MiB':info.rss/2**20,'private_MiB':getattr(info,'private',info.rss)/2**20})
        if index<120: time.sleep(.5)
    report={'pid':process.pid,'duration_seconds':60,'first_rss_MiB':samples[0]['rss_MiB'],
        'last_rss_MiB':samples[-1]['rss_MiB'],'peak_rss_MiB':max(s['rss_MiB'] for s in samples),'samples':samples}
    atomic_json(root/'results/memory-review/ui-memory-observation.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='samples'}))
if __name__=='__main__':main()
