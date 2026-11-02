"""Verify compact retention against an actual existing methylamine result copy."""
from pathlib import Path
from dataclasses import asdict,replace
import json
import shutil
import tempfile
import h5py
import numpy as np
from pyteck.respecth.runner import project_root,load_run
from pyteck.respecth.models import file_hash
from pyteck.respecth.atomic_io import atomic_json
from pyteck.respecth.compact_storage import retain_plot_result
from pyteck.respecth.recovery import verified_history
from pyteck.respecth.reporting import render_figures
from pyteck.respecth.evaluation import evaluate_results


def main():
    root=project_root()
    info=json.loads((root/'docs/delivery/project-storage-verification.json').read_text(encoding='utf-8'))
    source=Path(info['saved_project'])/'simulation'
    manifest,experiments,cases,results=load_run(source)
    case=cases[0];result=results[0];history=Path(result.history_path)
    original_hash=file_hash(history);before=history.stat().st_size
    with h5py.File(history) as data:
        original_rows=len(data['temperature'])
        original_final=data['mole_fractions'][-1]
    base=root/'.cache/compact-validation';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as value:
        directory=Path(value);(directory/'inputs').mkdir()
        shutil.copy2(source/'inputs'/f'{case.experiment_id}.xml',directory/'inputs'/f'{case.experiment_id}.xml')
        target=directory/'case.h5';shutil.copy2(history,target)
        compact=retain_plot_result(replace(result,history_path=str(target)))
        assert verified_history(asdict(compact)) and compact.predictions==result.predictions
        with h5py.File(target) as data:
            np.testing.assert_array_equal(data['mole_fractions'][-1],original_final)
            compact_rows=len(data['temperature'])
        saved={**manifest,'results':[asdict(compact)],'config':{**manifest['config'],'output':str(directory)}}
        atomic_json(directory/'manifest.json',saved)
        restored=load_run(directory)
        assert restored[3][0].status=='success' and restored[3][0].predictions==result.predictions
        reference=evaluate_results(experiments,results,{},cases)
        assert evaluate_results(restored[1],restored[3],{},restored[2])==reference
        figures=render_figures(restored[1],{'cases':restored[2],'results':restored[3]},
            {'output':str(directory/'figures'),'formats':['png']})
        assert figures
        report={'mechanism':case.mechanism.id,'case_id':case.id,'original_rows':original_rows,
            'compact_rows':compact_rows,'history_bytes_before':before,'history_bytes_after':target.stat().st_size,
            'reduction_percent':100*(1-target.stat().st_size/before),'predictions_identical':True,
            'scores_identical':True,'load_and_plot_passed':True,'figure_files':len(figures),
            'source_history_unchanged':file_hash(history)==original_hash,'new_simulations':0}
    atomic_json(root/'docs/delivery/compact-storage-validation.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__': main()
