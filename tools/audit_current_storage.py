from pathlib import Path
from collections import Counter
import json
import h5py

root=Path(__file__).resolve().parents[1]
directory=root/'results/ui-run'
path=directory/'manifest.json'
manifest=json.loads(path.read_text(encoding='utf-8'))
cached=list((directory/'cache').glob('*.h5'))
result={'status':manifest['status'],'total':len(manifest['cases']),'processed':len(manifest['results']),
 'statuses':dict(Counter(r['status'] for r in manifest['results'])), 'manifest_MiB':round(path.stat().st_size/2**20,2),
 'h5_count':len(cached), 'disk_GiB':round(sum(p.stat().st_size for p in cached)/2**30,3), 'largest_histories':[]}
for p in sorted(cached,key=lambda p:p.stat().st_size,reverse=True)[:8]:
 with h5py.File(p,'r') as f:
  result['largest_histories'].append({'file':p.name,'disk_MiB':round(p.stat().st_size/2**20,2),
   'datasets':{k:list(v.shape) for k,v in f.items()}, 'uncompressed_MiB':round(sum(v.size*v.dtype.itemsize for v in f.values())/2**20,2)})
bad=[]
for r in manifest['results']:
 if r['status']=='success':
  history=Path(r['history_path'])
  cache=directory/'cache'/f"{r['case_id']}.json"
  if not history.is_file() or not cache.is_file():bad.append(r['case_id'])
result['success_missing_files']=bad
(root/'results/storage-memory-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
