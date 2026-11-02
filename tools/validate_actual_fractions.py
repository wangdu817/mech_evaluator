"""User-requested actual-fraction semantics, on real XML/mechanism/history."""
from pathlib import Path
import json
import h5py
from dataclasses import asdict
from pyteck.respecth.runner import project_root,load_run,load_config,prepare_run
from pyteck.respecth.solvers import simulate_case
from pyteck.respecth.models import file_hash
from pyteck.respecth.atomic_io import atomic_json

root=project_root();source=root/'results/actual-audited/full'
manifest,experiments,cases,results=load_run(source)
raw=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
legacy=next(c for c in raw['cases'] if c['config'].get('concentration_basis')=='dry'
    and next(r for r in raw['results'] if r['case_id']==c['id'])['status']=='success')
case=next(c for c in cases if c.id==legacy['id']); result=next(r for r in results if r.case_id==case.id)
before=file_hash(result.history_path)
with h5py.File(result.history_path,'r') as h:
    names=json.loads(h.attrs['species_names'])
    for target in case.targets:
        species=case.mechanism.species_map.get(target['species'],target['species'])
        assert result.predictions[target['key']]==float(h['mole_fractions'][-1,names.index(species)])
assert file_hash(result.history_path)==before
config=load_config(root/'results/ui-run/config.yaml')
config.datasets=[p for p in config.datasets if Path(p).stem in {'Marrodan_2024_Set4','Marrodan_2024_Set5'}]
config.output=str(root/'results/actual-fractions-validation');config.grid={'enabled':False}
_,new_cases,warnings=prepare_run(config)
assert not any('Concentration basis' in i for c in new_cases for i in c.issues)
candidate=min((c for c in new_cases if not c.issues),key=lambda c:abs(c.condition.temperature-1100))
simulation=simulate_case(candidate,config.output)
assert simulation.status=='success',simulation.reason
with h5py.File(simulation.history_path,'r') as h:
    names=json.loads(h.attrs['species_names'])
    for target in candidate.targets:
        species=candidate.mechanism.species_map.get(target['species'],target['species'])
        assert simulation.predictions[target['key']]==float(h['mole_fractions'][-1,names.index(species)])
atomic_json(root/'results/actual-fractions-validation.json',{'legacy_history_unchanged':True,
    'legacy_predictions_recovered_from_actual_history':True,'formerly_blocked_xml':[Path(p).name for p in config.datasets],
    'unblocked_scoring_cases':len(new_cases),'actual_simulation':asdict(simulation),'warnings':warnings})
print('Actual fractions: original history preserved; actual formerly blocked case solved')
