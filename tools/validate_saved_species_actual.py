"""Audit default-tolerance single-pass sensitivity on frozen real cases."""
import json
from pathlib import Path
import h5py
import cantera as ct
import numpy as np
from pyteck.respecth.runner import project_root
from pyteck.respecth.models import case_from_dict, result_from_dict, file_hash
from pyteck.respecth.analysis import analysis_identity
from pyteck.respecth.analysis_job import run_job, export_analysis
from pyteck.respecth.native_analysis import species_sensitivity_view
from pyteck.respecth.atomic_io import atomic_json


def main():
    root=project_root(); evidence=[]
    records=json.loads((root/'results/case-analysis-actual-validation.json').read_text(encoding='utf-8'))
    for record in records:
        payload=json.loads((Path(record['directory'])/'job.json').read_text(encoding='utf-8'))
        case=case_from_dict(payload['case']); result=result_from_dict(payload['result'])
        before=file_hash(result.history_path)
        settings={**payload['settings'],'rop':False}
        settings['reaction_indices']=list(dict.fromkeys([settings['reaction_indices'][0],0,1]))
        directory=root/'results/analysis'/analysis_identity(case,result,settings)
        directory.mkdir(parents=True,exist_ok=True)
        atomic_json(directory/'job.json',{**payload,'settings':settings})
        report=run_job(directory/'job.json')
        assert report['status']=='completed',report.get('reason')
        sensitivity=report['sensitivity']; saved=Path(sensitivity['all_species_path'])
        assert sensitivity['native_solves']==1 and not sensitivity['tolerance_verification']
        defaults=ct.ReactorNet([])
        with h5py.File(saved,'r') as stream:
            names=stream['species'].asstr()[:].tolist()
            assert len(names)==len(case.mechanism.species)
            assert stream['X/derivative'].shape==(len(names),len(settings['reaction_indices']))
            assert stream.attrs['rtol']==defaults.rtol
            assert stream.attrs['rtol_sensitivity']==defaults.rtol_sensitivity
            assert np.all(np.isfinite(stream['X/derivative'][:]))
            np.testing.assert_allclose(stream['X/derivative'][:].sum(axis=0),0,atol=1e-10)
        matrix_hash=file_hash(saved)
        for species in ('NO','CH3NH2'):
            if species not in names: continue
            view=species_sensitivity_view(saved,species)
            output=directory/'views'/species; output.mkdir(parents=True,exist_ok=True)
            export_analysis({**report,'rop':{},'sensitivity':view},output)
            assert (output/'sensitivity.csv').is_file()
        assert file_hash(saved)==matrix_hash and file_hash(result.history_path)==before
        evidence.append({'kind':case.kind,'mechanism':case.mechanism.id,'directory':str(directory),
            'species_count':len(names),'reaction_count':len(settings['reaction_indices']),
            'native_solves':1,'tolerance_verification':False,'matrix_shape':[len(names),len(settings['reaction_indices'])],
            'switch_species_without_integration':True,'source_history_unchanged':True})
        atomic_json(root/'results/saved-species-actual-validation.json',evidence)
        print(json.dumps(evidence[-1],ensure_ascii=False),flush=True)


if __name__=='__main__': main()
