import hashlib
import multiprocessing
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from PIL import Image
from pyteck.respecth.models import file_hash
from pyteck.respecth.memory_control import pressure_reason,monitored_result,GIB
from pyteck.respecth.solvers import Cancelled
from pyteck.respecth.ui_artifacts import preview_image,deferred_archive
from pyteck.respecth.coverage import dataset_options

def test_streaming_hash_matches_sha_and_never_read_bytes(tmp_path,monkeypatch):
    data=b'actual-history-block'*70000
    path=tmp_path/'history.h5'; path.write_bytes(data)
    def forbidden(*args): raise AssertionError('whole-file read is forbidden')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    assert file_hash(path)==hashlib.sha256(data).hexdigest()

def test_guard_reserves_physical_and_commit_headroom():
    assert pressure_reason({'total':32*GIB,'available':2*GIB,'commit_available':20*GIB})
    assert 'commit' in pressure_reason({'total':32*GIB,'available':10*GIB,'commit_available':GIB})
    assert not pressure_reason({'total':32*GIB,'available':10*GIB,'commit_available':10*GIB})

def test_supervisor_stops_only_owned_native_worker(monkeypatch):
    import pyteck.respecth.memory_control as memory
    with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn')) as pool:
        future=pool.submit(time.sleep,60)
        processes=list(pool._processes.values())
        monkeypatch.setattr(memory,'pool_pressure',lambda pool:'Memory guard: test pressure')
        with pytest.raises(Cancelled,match='Memory guard'): monitored_result(pool,future)
        assert processes and all(not process.is_alive() for process in processes)

def test_preview_is_small_export_unchanged_and_archive_lazy(tmp_path):
    image=tmp_path/'figure.png'; Image.new('RGB',(3600,2400),'white').save(image)
    before=file_hash(image)
    preview=preview_image(image)
    with Image.open(preview) as displayed: assert max(displayed.size)<=1400
    assert file_hash(image)==before
    download=deferred_archive(tmp_path,[image])
    assert not (tmp_path/'download.zip').exists()
    assert download() and (tmp_path/'download.zip').exists()
    with zipfile.ZipFile(tmp_path/'download.zip') as archive: assert archive.namelist()==['figure.png']
    with pytest.raises(ValueError,match='64 MiB'): deferred_archive(tmp_path,[image],limit=1)()

def test_xml_classification_preserves_zero_instruments_and_mechanisms():
    experiment=NS(id='e',path='source.xml',observations=[NS(id='s',point_indices=[0,1]),NS(id='instrument2',point_indices=[0])])
    def case(identity,mechanism):
        return NS(id=identity,experiment_id='e',mechanism=NS(id=mechanism),role='scoring',
            targets=[{'key':'s','quantity':'composition','point_indices':[0,1]},
                     {'key':'instrument2','quantity':'composition','point_indices':[0]}])
    first=case('c','clear'); second=case('d','other')
    result=NS(case_id='c',status='success',predictions={'s':0.,'instrument2':1.},validation={'passed':True})
    options,rows=dataset_options([experiment],[first,second],[result])
    assert options['e']['category']=='部分完成'
    assert rows[0]['原始测量预测']==3 and rows[0]['分类']=='全部完成'
    assert rows[1]['分类']=='未运行'
    assert dataset_options([experiment],[first,second],[result],['clear'])[0]['e']['category']=='全部完成'
    result.predictions.pop('instrument2')
    assert dataset_options([experiment],[first],[result])[1][0]['原始测量预测']==2
    result.status='solver_failed'
    assert dataset_options([experiment],[first],[result])[0]['e']['category']=='计算失败或不可用'
