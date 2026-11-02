from pathlib import Path
import json
from types import SimpleNamespace
import h5py
import numpy as np
import pytest
from pyteck.respecth.history_io import DiskHistory
from pyteck.respecth.recovery import recover_interrupted_run


def test_history_keeps_every_step_with_bounded_buffer(tmp_path):
    n=199
    phase=SimpleNamespace(X=np.full(n,1/n),Y=np.full(n,1/n),concentrations=np.arange(n,dtype=float),P=101325.)
    reactor=SimpleNamespace(phase=phase,T=1000.,volume=.0001)
    history=DiskHistory(tmp_path,n,buffer_rows=64)
    for i in range(12000):
        history.record(reactor,i*.001)
        assert len(history.buffer)<64
        assert history.buffered_bytes<=63*(32+3*n*8)
    assert history['time'][-1]==pytest.approx(11.999)
    assert history['mole_fractions'].shape==(12000,n)
    destination=tmp_path/'complete.h5'
    history.finish(destination,{'case_id':'test'})
    history.close()
    with h5py.File(destination) as f:
        assert f.attrs['complete']
        assert np.all(np.diff(f['time'][:])>0)
        assert np.array_equal(f['concentrations'][-1],np.arange(n)*1000)
    assert not list(tmp_path.glob('*.tmp'))


def test_unfinished_history_cleanup_is_scoped(tmp_path):
    unrelated=tmp_path/'other.h5.tmp';unrelated.write_bytes(b'preserve')
    history=DiskHistory(tmp_path,2)
    own=history.path
    history.close()
    assert not own.exists() and unrelated.read_bytes()==b'preserve'


def test_recovery_uses_committed_cache_and_does_not_fake_missing_results(tmp_path,monkeypatch):
    import pyteck.respecth.runner as runner
    monkeypatch.setattr(runner,'project_root',lambda:tmp_path)
    output=tmp_path/'run';(output/'cache').mkdir(parents=True)
    manifest={'status':'running','workers':2,'created_utc':'2026-10-09T00:00:00+00:00',
              'experiments':[], 'cases':[{'id':'a','mechanism':{'id':'m'}},{'id':'b','mechanism':{'id':'m'}}], 'results':[]}
    (output/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    h=output/'cache/a.h5'
    with h5py.File(h,'w') as f:
        f.attrs['case_id']='a';f.attrs['validation']=json.dumps({'passed':True})
        f.create_dataset('temperature',data=[1000.]);f.create_dataset('mole_fractions',data=[[.1,.9]])
    result={'case_id':'a','status':'success','predictions':{'x':.1},'history_path':str(h),'validation':{'passed':True}}
    (output/'cache/a.json').write_text(json.dumps(result),encoding='utf-8')
    recovered=recover_interrupted_run(output)
    assert recovered['status']=='cancelled'
    assert [r['status'] for r in recovered['results']]==['success','cancelled']
    assert recovered['results'][1]['predictions']=={}
    assert json.loads(Path(recovered['recovery']['original_manifest']).read_text())==manifest
    assert (output/'cache/a.json').read_text()==json.dumps(result)


def test_recovery_refuses_live_owner(tmp_path,monkeypatch):
    import pyteck.respecth.runner as runner
    monkeypatch.setattr(runner,'project_root',lambda:tmp_path)
    (tmp_path/'run.lock').touch()
    with pytest.raises(ValueError,match='owner lock'):
        recover_interrupted_run(tmp_path)
