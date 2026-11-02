"""Retain inlet/outlet states, not full batch trajectories; chemistry is unchanged."""
from pathlib import Path
import uuid
import h5py
import numpy as np


def is_compact(path):
    with h5py.File(path,'r') as stream:
        return stream.attrs.get('storage_mode')=='endpoints'


def compact_history(source,destination=None):
    source=Path(source);destination=Path(destination or source)
    temporary=destination.with_name('.compact-'+uuid.uuid4().hex+'.h5.tmp')
    try:
        with h5py.File(source,'r') as original,h5py.File(temporary,'w') as output:
            for key,value in original.attrs.items(): output.attrs[key]=value
            output.attrs['storage_mode']='endpoints'
            output.attrs['trajectory_available']=False
            for name,item in original.items():
                if not isinstance(item,h5py.Dataset):
                    raise ValueError('Unexpected nested history; compacting aborted')
                if item.ndim and len(item)>2:
                    values=np.stack((item[0],item[-1]))
                else: values=item[()]
                output.create_dataset(name,data=values,compression='gzip' if np.ndim(values) else None)
            output.attrs['complete']=original.attrs.get('complete',True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def retain_plot_result(result):
    if result.history_path and Path(result.history_path).is_file():
        compact_history(result.history_path)
        result.metadata={**result.metadata,'storage_mode':'endpoints',
            'trajectory_available':False,'analysis_requires_reconstruction':True}
    return result
