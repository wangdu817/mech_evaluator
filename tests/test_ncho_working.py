"""Independent raw-Arrhenius checks for the authorized real mechanism revision."""
from pathlib import Path
import json
import cantera as ct
import numpy as np
import pytest
from pyteck.respecth.yaml_io import load_yaml

ROOT=Path(__file__).resolve().parents[1]
INPUTS=ROOT/'results/multi-mechanism/inputs'

def working():
 path=INPUTS/'N_CHO_240725_working.yaml'
 if not path.exists():pytest.skip('Authorized local mechanism not distributed')
 return load_yaml(path.read_text(encoding='utf8'))

def test_other_reactions_and_thermo_preserved():
 revised=working();source=load_yaml(next((INPUTS.parent/'prepared').glob('converted-991d*.yaml')).read_text(encoding='utf8'))
 assert revised['species']==source['species']
 equation='HCCO + OH <=> CO2 + CH2'
 assert [r for r in revised['reactions'] if r['equation']!=equation]==[r for r in source['reactions'] if r['equation']!=equation]
 audit=json.loads((INPUTS/'audit.json').read_text(encoding='utf8'))
 assert audit['thermo_policy']=='first'
 assert all(x['selected_line']==min(x['alternative_lines']) for x in audit['thermo_selected'].values())

@pytest.mark.parametrize('pressure',[.1,1,1.3,1.12345,3.45678,10])
def test_raw_rate_sum_matches_working(pressure):
 revised=working();gas=ct.Solution(yaml=(INPUTS/'N_CHO_240725_working.yaml').read_text(encoding='utf8'))
 index=next(i for i,r in enumerate(gas.reactions()) if r.equation=='HCCO + OH <=> CH2 + CO2')
 audit=json.loads((INPUTS/'plog-audit.json').read_text(encoding='utf8'))
 def rate(e,T):return .001*e['A']*T**e['b']*np.exp(-e['Ea']/(1.98720425864083*T))
 for T in [300,650,1000,1600,2500,5000,10000]:
  expected=0
  for r in audit['original_reactions']:
   entries=r['rate-constants']
   if pressure in [.1,1,10]: expected+=rate(next(e for e in entries if float(e['P'].split()[0])==pressure),T)
   else:
    low=rate(next(e for e in entries if float(e['P'].split()[0])==1),T);high=rate(next(e for e in entries if float(e['P'].split()[0])==10),T)
    a=np.log(pressure)/np.log(10);expected+=np.exp((1-a)*np.log(low)+a*np.log(high))
  gas.TP=T,pressure*ct.one_atm
  assert expected>0
  assert abs(gas.forward_rate_constants[index]/expected-1)<1e-3
