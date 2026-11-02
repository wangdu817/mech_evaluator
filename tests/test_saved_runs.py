from dataclasses import replace
from pathlib import Path
import pytest
from pyteck.respecth.runner import load_run,load_config,prepare_run
from pyteck.respecth.saved_runs import combine_saved_runs
from pyteck.respecth.models import file_hash

ROOT=Path(__file__).resolve().parents[1]

def test_cache_identity_independent_of_result_directory_and_figures(tmp_path):
 config=load_config(ROOT/'examples/respecth/demo.yaml')
 one=replace(config,output=str(tmp_path/'one'))
 two=replace(config,output=str(tmp_path/'two'),figure={'conditions':False,'mechanisms':['gri30']})
 _,a,_=prepare_run(one);_,b,_=prepare_run(two)
 assert [c.id for c in a]==[c.id for c in b]
 changed=replace(config,output=str(tmp_path/'three'),solver={**config.solver,'rtol':1e-8})
 _,c,_=prepare_run(changed)
 assert not set(x.id for x in a)&set(x.id for x in c)

def test_actual_saved_runs_combine_without_touching_histories(tmp_path):
 a=ROOT/'results/actual-audited/full';b=ROOT/'results/multi-mechanism/run'
 if not (b/'manifest.json').exists():pytest.skip('Local actual data not distributed')
 before={p:p.stat().st_mtime_ns for folder in [a,b] for p in (folder/'cache').glob('*')}
 manifest=combine_saved_runs([a,b],tmp_path/'compare')
 assert len(manifest['experiments'])==6
 assert {c['mechanism']['id'] for c in manifest['cases']}=={'audited_working','N_CHO_240725_working'}
 assert len(manifest['cases'])==192
 assert manifest['saved_comparison']['simulations_executed']==0
 assert manifest['saved_comparison']['duplicate_cases_first_source_kept']
 assert before=={p:p.stat().st_mtime_ns for p in before}
 assert len(load_run(tmp_path/'compare')[2])==192

def test_same_label_different_mechanism_rejected(tmp_path,monkeypatch):
 from pyteck.respecth import saved_runs
 a=ROOT/'results/demo'
 if not (a/'manifest.json').exists():pytest.skip('Saved demo not distributed')
 original=load_run(a);count=0
 def fake(directory):
  nonlocal count
  count+=1
  if count==1:return original
  manifest,exps,cases,results=load_run(a)
  for case in cases:case.mechanism.sha256='changed-model'
  return manifest,exps,cases,results
 monkeypatch.setattr(saved_runs,'load_run',fake)
 with pytest.raises(ValueError,match='different inputs'):
  combine_saved_runs([a,a],tmp_path/'conflict')
