"""Rebuild discarded trajectories only for the requested diagnostic job."""
from contextlib import contextmanager
from pathlib import Path
from dataclasses import replace
import tempfile
import numpy as np
from . import analysis
from .compact_storage import is_compact
from .solvers import simulate_case,Cancelled


@contextmanager
def full_trajectory(case,result,cancel_file=None):
    if not is_compact(result.history_path):
        yield result
        return
    from .runner import project_root
    base=project_root()/'.cache/analysis-trajectories'
    base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='single-',dir=base) as directory:
        rebuilt=simulate_case(case,directory,cancel_file)
        if rebuilt.status=='cancelled': raise Cancelled(rebuilt.reason)
        if rebuilt.status!='success': raise ValueError('Single-case trajectory reconstruction failed: '+rebuilt.reason)
        for key,value in result.predictions.items():
            actual=rebuilt.predictions.get(key)
            if actual is None or not np.isfinite(actual) or abs(actual-value)>max(abs(value)*case.config.get('validation_relative',.01),case.config.get('validation_absolute',1e-10)):
                raise ValueError('Reconstructed trajectory disagrees with the retained observable: '+key)
        yield replace(result,history_path=rebuilt.history_path)


def compute_rop(case,result,species,row,*args,**kwargs):
    _,coordinates=analysis.history_coordinates(case,result)
    if not 0<=row<len(coordinates): raise ValueError('Selected history row is outside retained states')
    selected=float(case.config.get('analysis_coordinate', coordinates[row]))
    with full_trajectory(case,result,kwargs.get('cancel_file')) as rebuilt:
        _,full=analysis.history_coordinates(case,rebuilt)
        index=int(np.argmin(abs(full-selected)))
        return analysis.compute_rop(case,rebuilt,species,index,*args,**kwargs)


compute_sensitivity=analysis.compute_sensitivity


def compute_temperature_sensitivity(case,result,indices,reference_time,cancel_file=None,*args,**kwargs):
    with full_trajectory(case,result,cancel_file) as rebuilt:
        return analysis.compute_temperature_sensitivity(case,rebuilt,indices,reference_time,cancel_file,*args,**kwargs)
