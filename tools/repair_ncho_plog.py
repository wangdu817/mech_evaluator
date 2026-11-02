"""Authorized working-mechanism revision: combine signed duplicate PLOG channels."""
from pathlib import Path
import copy,json,hashlib
import numpy as np
import yaml,cantera as ct
from pyteck.respecth.yaml_io import load_yaml

def main():
 root=Path(__file__).resolve().parents[1];out=root/'results/multi-mechanism/inputs'
 source=next((out.parent/'prepared').glob('converted-991d*.yaml'));data=load_yaml(source.read_text(encoding='utf8'))
 indices=[i for i,r in enumerate(data['reactions']) if r['equation']=='HCCO + OH <=> CO2 + CH2']
 assert len(indices)==3
 original=[copy.deepcopy(data['reactions'][i]) for i in indices]
 original_nodes=sorted({float(e['P'].split()[0]) for r in original for e in r['rate-constants']})
 nodes=sorted(set(original_nodes+np.geomspace(1,10,513).tolist()+[1.05,1.3,2,5]))
 merged=copy.deepcopy(original[0]);merged.pop('duplicate',None);merged['rate-constants']=[]
 for pressure in nodes:
  for reaction in original:
   entries=reaction['rate-constants'];node=next((e for e in entries if float(e['P'].split()[0])==pressure),None)
   if node is None and pressure<1:
    node=min(entries,key=lambda e:float(e['P'].split()[0]))
   if node is None:
    low=next(e for e in entries if float(e['P'].split()[0])==1);high=next(e for e in entries if float(e['P'].split()[0])==10)
    alpha=np.log(pressure)/np.log(10)
    node={'A':float(np.exp((1-alpha)*np.log(low['A'])+alpha*np.log(high['A']))),'b':float((1-alpha)*low['b']+alpha*high['b']),'Ea':float((1-alpha)*low['Ea']+alpha*high['Ea'])}
   entry=copy.deepcopy(node);entry['P']=f'{pressure:.17g} atm';merged['rate-constants'].append(entry)
 merged['note']='User-authorized working revision: original three signed duplicate PLOG contributions combined before logarithmic pressure interpolation. Original node A, b, Ea retained. Additional 1--10 atm nodes encode the original positive separate-channel interpolation before summing; other off-node interpolation changes. Missing low-pressure nodes use original endpoint clamping. See plog-audit.json.'
 data['reactions']=[merged if i==indices[0] else r for i,r in enumerate(data['reactions']) if i not in indices[1:]]
 destination=out/'N_CHO_240725_working.yaml';destination.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True,width=120),encoding='utf8')
 gas=ct.Solution(yaml=destination.read_text(encoding="utf8"));idx=next(i for i,r in enumerate(gas.reactions()) if r.equation=='HCCO + OH <=> CH2 + CO2')
 Tgrid=np.geomspace(200,10000,501);node_errors=[];mins=[]
 def arr(e,T):return e['A']*T**e['b']*np.exp(-e['Ea']/(1.98720425864083*T))*.001
 for P in original_nodes:
  expected=np.zeros_like(Tgrid)
  for r in original:
   entry=next((e for e in r['rate-constants'] if float(e['P'].split()[0])==P),None)
   if entry is None:entry=min(r['rate-constants'],key=lambda e:float(e['P'].split()[0]))
   expected+=arr(entry,Tgrid)
  actual=[]
  for T in Tgrid:
   gas.TP=float(T),P*ct.one_atm;actual.append(gas.forward_rate_constants[idx])
  assert np.all(expected>0)
  node_errors.append(float(np.max(abs(np.array(actual)/expected-1))));mins.append(float(expected.min()))
 assert max(node_errors)<1e-9
 # Original separate logarithmic PLOGs are evaluable on the positive 1--10 atm interval.
 errors={}
 for P in [1.05,1.3,2,5,1.12345,3.45678,7.89123]:
  alpha=np.log(P)/np.log(10);old=sum(np.exp((1-alpha)*np.log(arr(next(e for e in r['rate-constants'] if float(e['P'].split()[0])==1),Tgrid))+alpha*np.log(arr(next(e for e in r['rate-constants'] if float(e['P'].split()[0])==10),Tgrid))) for r in original)
  new=[]
  for T in Tgrid:gas.TP=float(T),P*ct.one_atm;new.append(gas.forward_rate_constants[idx])
  errors[str(P)]={'max_relative_change_200_10000K':float(np.max(abs(np.array(new)/old-1)))}
 assert max(x['max_relative_change_200_10000K'] for x in errors.values())<.01
 # Dense positivity check includes every pressure interval, endpoints and original validation temperatures.
 for P in np.geomspace(.001,100,101):
  for T in np.geomspace(200,10000,61):
   gas.TP=float(T),float(P)*ct.one_atm;assert np.isfinite(gas.forward_rate_constants[idx]) and gas.forward_rate_constants[idx]>0
 report={'source_yaml_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'working_yaml_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'original_indices_1based':[i+1 for i in indices],'original_reactions':original,'revised_reaction':merged,'method':'sum signed contributions at shared pressure nodes, then logarithmic interpolation','not_equivalent_between_nodes':True,'pressure_nodes':len(nodes),'node_max_relative_errors':node_errors,'node_min_rates_SI':mins,'off_node_changes':errors,'validation_T_K':[200,10000],'positivity_pressure_atm':[.001,100],'species':gas.n_species,'reactions':gas.n_reactions,'transport':gas.transport_model,'all_other_reaction_entries_unchanged':True,'limitation':'Working revision, not recovered original author intent or experimentally optimized fit.'}
 (out/'plog-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({k:v for k,v in report.items() if k not in ['original_reactions','revised_reaction']},ensure_ascii=False))
if __name__=='__main__':main()

