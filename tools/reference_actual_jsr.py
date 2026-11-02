"""Independent direct-Cantera check of a real XML JSR condition."""
from pathlib import Path
import json
import time
import warnings
import sys
import cantera as ct
import numpy as np

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root/'results/actual-audited/full/manifest.json').read_text(encoding='utf8'))
temperature = float(sys.argv[1]) if len(sys.argv) > 1 else 1011.
case = next(c for c in manifest['cases'] if c['kind'] == 'jsr' and c['condition']['temperature'] == temperature)
condition = case['condition']
mapping = case['mechanism']['species_map']
with warnings.catch_warnings(record=True) as captured:
    gas = ct.Solution(yaml=(root.parent/'mech/audited_working.yaml').read_text(encoding='utf8'), name='gas')
inlet_X = {mapping.get(k, k): v for k,v in condition['composition'].items()}
gas.TPX = condition['temperature'], condition['pressure'], inlet_X
feed, exhaust = ct.Reservoir(gas, clone=True), ct.Reservoir(gas, clone=True)
reactor = ct.IdealGasReactor(gas, clone=True, energy='off', volume=condition['volume'])
tau = condition['residence_time']
controller = ct.MassFlowController(feed, reactor, mdot=lambda _:reactor.mass/tau)
ct.PressureController(reactor, exhaust, primary=controller, K=1e-5)
network = ct.ReactorNet([reactor])
network.rtol, network.atol = 1e-10, 1e-16
network.max_time_step = tau/10
old = reactor.phase.X.copy()
consecutive = 0
started = time.monotonic()
for window in range(1,101):
    network.advance(window*tau)
    current = reactor.phase.X.copy()
    residual = float(np.max(abs(current-old)/np.maximum(abs(current), 1e-8)))
    consecutive = consecutive+1 if residual < 1e-6 and abs(reactor.phase.P/condition['pressure']-1) < 1e-6 else 0
    old = current
    if consecutive >= 3:
        break
predicted = {target['key']:float(reactor.phase.X[reactor.phase.species_index(mapping.get(target['species'],target['species']))]) for target in case['targets']}
report = {'case_id':case['id'], 'condition':condition, 'predictions':predicted, 'steady':consecutive>=3,
          'windows':window, 'time':network.time, 'residual':residual, 'elapsed':time.monotonic()-started,
          'source_warnings':[str(w.message) for w in captured]}
(root/f'results/actual-audited/reference-jsr-{temperature:g}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print({k:report[k] for k in ('steady','windows','residual','elapsed')})
