"""Read-only memory/storage snapshot restricted to this project's run owner."""
from pathlib import Path
from collections import Counter
import json
import psutil

ROOT = Path(__file__).resolve().parents[1]
v = psutil.virtual_memory()
report = {'memory': {'total_GiB': round(v.total/2**30, 3), 'available_GiB':round(v.available/2**30,3), 'percent':v.percent}, 'runs':[]}
report['python_processes'] = []
for proc in psutil.process_iter(['name']):
    if 'python' in (proc.info['name'] or '').lower():
        try:
            mem=proc.memory_info()
            report['python_processes'].append({'pid':proc.pid,'parent':proc.ppid(),'RSS_MiB':round(mem.rss/2**20,1), 'private_MiB':round(getattr(mem,'private',mem.vms)/2**20,1)})
        except (psutil.NoSuchProcess,psutil.AccessDenied):
            pass
for lock in (ROOT/'results').rglob('run.lock'):
    owner = json.loads(lock.read_text(encoding='utf-8'))
    entry = {'output':str(lock.parent), 'owner':owner, 'processes':[]}
    try:
        parent = psutil.Process(owner['pid'])
        for proc in [parent]+parent.children(recursive=True):
            mem = proc.memory_info()
            entry['processes'].append({'pid':proc.pid, 'parent':proc.ppid(), 'RSS_MiB':round(mem.rss/2**20,1), 'private_MiB':round(getattr(mem,'private',mem.vms)/2**20,1)})
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        entry['process_error'] = str(exc)
    manifest = lock.parent/'manifest.json'
    if manifest.exists():
        m=json.loads(manifest.read_text(encoding='utf-8'))
        active=set(m.get('active_cases', []))
        entry.update(status=m['status'], total=len(m['cases']), completed=len(m['results']), statuses=dict(Counter(r['status'] for r in m['results'])), workers=m.get('workers'),
                     active=[{'id':c['id'],'kind':c['kind'],'T':c['condition']['temperature']} for c in m['cases'] if c['id'] in active])
    caches=list((lock.parent/'cache').glob('*.h5'))
    entry['h5_count']=len(caches)
    entry['h5_GiB']=round(sum(p.stat().st_size for p in caches)/2**30,4)
    report['runs'].append(entry)
print(json.dumps(report, ensure_ascii=False, indent=2))
(ROOT/'results/memory-current.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
