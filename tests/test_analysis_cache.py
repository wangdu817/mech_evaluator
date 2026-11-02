from copy import deepcopy
import json
from pyteck.respecth import analysis_cache as cache


def saved(tmp_path,monkeypatch):
    monkeypatch.setattr(cache,'project_root',lambda:tmp_path)
    monkeypatch.setattr(cache,'numeric_signature',lambda:'signature1')
    history=tmp_path/'history.h5';history.write_bytes(b'unchanged-history')
    directory=tmp_path/'results/analysis/old';directory.mkdir(parents=True)
    payload={'case':{'id':'case','mechanism':{'sha256':'chemistry','path':'old.yaml','provenance':{},'phase':'gas','species_map':{}},
        'config':{'rtol':1e-9}},'result':{'history_path':str(history),'status':'success','predictions':{'OH':.1},'validation':{'passed':True}},
        'settings':{'sensitivity':True,'reaction_indices':[1,2],'top_n':15}}
    (directory/'job.json').write_text(json.dumps(payload))
    (directory/'report.json').write_text(json.dumps({'status':'completed','case':{'id':'case'},'numeric_signature':'signature1'}))
    return payload,directory


def test_reuse_ignores_plot_limit_and_equivalent_history_location(tmp_path,monkeypatch):
    payload,directory=saved(tmp_path,monkeypatch)
    original=(directory/'job.json').read_bytes()
    other=tmp_path/'linked-history.h5';other.write_bytes(b'unchanged-history')
    payload=deepcopy(payload);payload['settings']['top_n']=30
    payload['result']['history_path']=str(other);payload['case']['mechanism']['path']='new-location.yaml'
    assert cache.reusable_directory(payload)==directory
    assert (directory/'job.json').read_bytes()==original


def test_numeric_settings_chemistry_and_history_changes_block_reuse(tmp_path,monkeypatch):
    payload,directory=saved(tmp_path,monkeypatch)
    changed=deepcopy(payload);changed['case']['config']['rtol']=1e-6
    assert cache.reusable_directory(changed) is None
    changed=deepcopy(payload);changed['case']['mechanism']['sha256']='different'
    assert cache.reusable_directory(changed) is None
    changed=deepcopy(payload);changed['settings']['reaction_indices']=[3]
    assert cache.reusable_directory(changed) is None
    monkeypatch.setattr(cache,'numeric_signature',lambda:'signature2')
    assert cache.reusable_directory(payload) is None


def test_legacy_result_requires_explicit_review_certificate(tmp_path,monkeypatch):
    payload,directory=saved(tmp_path,monkeypatch)
    report=directory/'report.json';report.write_text(json.dumps({'status':'completed','case':{'id':'case'}}))
    assert cache.reusable_directory(payload) is None
    assert cache.certify_reviewed_legacy_reports()==1
    assert cache.reusable_directory(payload)==directory
    report.write_text(json.dumps({'status':'completed','case':{'id':'case'},'extra':'tampered'}))
    assert cache.reusable_directory(payload) is None


def test_component_reuse_separates_sensitivity_from_rop_settings(tmp_path,monkeypatch):
    payload,directory=saved(tmp_path,monkeypatch)
    payload['settings'].update(rop=True,species='OH',row=50,target_key='oh',zero_floor=1e-20)
    (directory/'job.json').write_text(json.dumps(payload))
    report={'status':'completed','case':{'id':'case'},'numeric_signature':'signature1',
            'sensitivity':{'rows':[{'coefficient':1.}]},'rop':{'species':'OH'}}
    (directory/'report.json').write_text(json.dumps(report))
    wanted=deepcopy(payload)
    wanted['settings'].update(rop=False,species=None,row=0)
    assert cache.reusable_directory(wanted,component='sensitivity')==directory
    wanted['settings']['reaction_indices']=[3]
    assert cache.reusable_directory(wanted,component='sensitivity') is None
    wanted=deepcopy(payload)
    wanted['settings'].update(sensitivity=False,target_key='other',reaction_indices=[3],zero_floor=1e-9)
    assert cache.reusable_directory(wanted,component='rop')==directory
    wanted['settings']['species']='H2'
    assert cache.reusable_directory(wanted,component='rop') is None
    wanted['settings'].update(species='OH',row=40)
    assert cache.reusable_directory(wanted,component='rop') is None


def test_missing_species_matrix_does_not_count_as_completed_cache(tmp_path,monkeypatch):
    payload,directory=saved(tmp_path,monkeypatch)
    report={'status':'completed','case':{'id':'case'},'numeric_signature':'signature1',
            'sensitivity':{'all_species_path':str(tmp_path/'missing.h5')}}
    (directory/'report.json').write_text(json.dumps(report))
    assert cache.reusable_directory(payload,component='sensitivity') is None


def test_pfr_full_matrix_reuses_other_species_but_jsr_target_stays_strict(tmp_path,monkeypatch):
    import h5py
    payload,directory=saved(tmp_path,monkeypatch)
    payload['case'].update(kind='pfr',targets=[{'key':'oh','species':'OH','quantity':'composition'},
                                             {'key':'h2','species':'H2','quantity':'composition'}])
    payload['settings']['target_key']='oh'
    matrix=directory/'matrix.h5'
    with h5py.File(matrix,'w') as file:
        file.attrs.update(case_id='case',mechanism_sha256='chemistry')
        file.create_dataset('species',data=['OH','H2'],dtype=h5py.string_dtype())
    (directory/'job.json').write_text(json.dumps(payload))
    report={'status':'completed','case':{'id':'case'},'numeric_signature':'signature1',
            'sensitivity':{'all_species_path':str(matrix)}}
    (directory/'report.json').write_text(json.dumps(report))
    requested=deepcopy(payload);requested['settings']['target_key']='h2'
    assert cache.reusable_directory(requested,component='sensitivity')==directory
    payload['case']['kind']='jsr';requested['case']['kind']='jsr'
    (directory/'job.json').write_text(json.dumps(payload))
    assert cache.reusable_directory(requested,component='sensitivity') is None
