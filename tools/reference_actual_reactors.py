"""Direct Cantera checks using the untouched user YAML and real XML cases."""
from pathlib import Path
import json
import warnings
import cantera as ct
import numpy as np

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root/'results/actual-audited/full/manifest.json').read_text(encoding='utf8'))
source = (root.parent/'mech/audited_working.yaml').read_text(encoding='utf8')
checks = {}
for kind in ('pfr','ignition'):
    case = (max((c for c in manifest['cases'] if c['kind'] == 'pfr' and 'Marrodan_2024_Set1' in c['experiment_id']), key=lambda c:c['condition']['temperature'])
            if kind == 'pfr' else next(c for c in manifest['cases'] if c['kind'] == kind))
    condition = case['condition']
    mapping = case['mechanism']['species_map']
    with warnings.catch_warnings(record=True):
        gas = ct.Solution(yaml=source,name='gas')
    gas.TPX = condition['temperature'],condition['pressure'],{mapping.get(k,k):v for k,v in condition['composition'].items()}
    if kind == 'pfr':
        reactor = ct.IdealGasConstPressureReactor(gas,energy='off',clone=True)
        network = ct.ReactorNet([reactor])
        network.rtol,network.atol = 1e-10,1e-16
        network.advance(condition['residence_time'])
        values = {}
        for target in case['targets']:
            species = mapping.get(target['species'],target['species'])
            value = float(reactor.phase.X[reactor.phase.species_index(species)])
            if case['config']['concentration_basis'] == 'dry':
                value /= 1-reactor.phase.X[reactor.phase.species_index('H2O')]
            values[target['key']] = value
        checks[kind] = {'case_id':case['id'],'predictions':values}
    else:
        assert case['config']['ignition_type'] == {'target':'p','type':'d/dt max'}
        reactor = ct.IdealGasReactor(gas,energy='on',clone=True)
        network = ct.ReactorNet([reactor])
        network.rtol,network.atol = 1e-10,1e-16
        times = np.linspace(0,case['config']['time_end'],20001)
        pressures = [reactor.phase.P]
        for time in times[1:]:
            network.advance(float(time))
            pressures.append(reactor.phase.P)
        derivatives = np.gradient(pressures,times)
        index = int(np.argmax(derivatives))
        assert 0 < index < len(times)-1
        coefficients = np.polyfit(times[index-1:index+2]-times[index],derivatives[index-1:index+2],2)
        peak = float(times[index]-coefficients[1]/(2*coefficients[0]))
        checks[kind] = {'case_id':case['id'],'predictions':{t['key']:peak for t in case['targets']},'definition':'maximum pressure time derivative','samples':len(times)}
(root/'results/actual-audited/reference-reactors.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
print({k:v['predictions'] for k,v in checks.items()})
