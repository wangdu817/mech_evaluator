"""Find the exact prior source fingerprint by reproducing a saved case ID."""
import hashlib
import itertools
import json
import platform
from pathlib import Path
import cantera as ct
import numpy as np
import scipy
from pyteck.respecth.models import digest,file_hash
from pyteck.respecth.atomic_io import atomic_json

root=Path(__file__).resolve().parents[1]; source=root/'src/pyteck/respecth'
names=('models.py','units.py','reader.py','cases.py','solvers.py','history_io.py','../gas_io.py','../detect_peaks.py')
current={name:file_hash(source/name) for name in names}
models=(source/'models.py').read_text(encoding='utf-8')
start=models.index('    checksum = hashlib.sha256()',models.index('def file_hash'))
end=models.index('\n\n',start)
models=models[:start]+"    return hashlib.sha256(Path(path).read_bytes()).hexdigest()"+models[end:]
solvers=(source/'solvers.py').read_text(encoding='utf-8')
start=solvers.index('        from .memory_control import pressure_reason',solvers.index('    def check_cancel'))
end=solvers.index('        return 0.',start)
solvers=solvers[:start]+solvers[end:]
possibilities=[]
for endings in itertools.product(('\n','\r\n'),repeat=2):
    hashes=dict(current)
    for name,text,ending in zip(('models.py','solvers.py'),(models,solvers),endings):
        hashes[name]=hashlib.sha256(text.replace('\n',ending).encode()).hexdigest()
    possibilities.append((digest(hashes),hashes))
records=json.loads((root/'results/case-analysis-actual-validation.json').read_text(encoding='utf-8'))
latest=json.loads((root/'results/ui-run/manifest.json').read_text(encoding='utf-8'))
payloads=[{'case':latest['cases'][0],'source_run':str(root/'results/ui-run')}]
payloads += [json.loads((Path(record['directory'])/'job.json').read_text(encoding='utf-8')) for record in records]
matched=None
for payload in payloads:
    case=payload['case']; mechanism=case['mechanism']
    original=json.loads((Path(payload['source_run'])/'manifest.json').read_text(encoding='utf-8'))
    experiment=next(e for e in original['experiments'] if e['id']==case['experiment_id'])
    for engine,hashes in possibilities:
        identity=digest({'xml':experiment['sha256'],'mechanism':{k:mechanism[k] for k in
            ('sha256','phase','species_map','species','transport')},'condition':case['condition'],'solver':case['config'],
            'targets':case['targets'],'role':case['role'],'issues':case['issues'],'engine':engine,
            'cantera':ct.__version__,'numpy':np.__version__,'python':platform.python_version(),'scipy':scipy.__version__})
        if identity==case['id']: matched=(engine,hashes,case['id'])
    if matched: break
report={'current_engine':digest(current),'prior_identity_reproduced':bool(matched)}
if matched:
    prior,hashes,identity=matched
    report.update(prior_engine=prior,verified_case_id=identity,prior_source_hashes=hashes)
    path=source/'cache_compatibility.json'; compatibility=json.loads(path.read_text(encoding='utf-8'))
    compatibility['aliases'][digest(current)]=compatibility['aliases'].get(prior,prior)
    compatibility['memory_control_revision']={'reason':'Only streamed hashing and execution memory guard changed; numerical equations and tolerances unchanged',
        'verified_prior_case':identity,'evidence':'results/memory-review/cache-compatibility.json'}
    atomic_json(path,compatibility)
atomic_json(root/'results/memory-review/cache-compatibility.json',report)
print(json.dumps(report,ensure_ascii=False))
