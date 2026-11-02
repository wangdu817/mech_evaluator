import json
from pathlib import Path
from pyteck.respecth import analysis_batch_job as batch


def prepare(tmp_path):
    directory=tmp_path/'results/analysis-batches/batch'
    directory.mkdir(parents=True)
    jobs=[]
    for i in range(2):
        job=tmp_path/f'results/analysis/job{i}/job.json';job.parent.mkdir(parents=True)
        job.write_text('{}')
        (job.parent/'report.json').write_text(json.dumps({'status':'completed','case':{'id':str(i)}}))
        jobs.append({'job':str(job),'label':str(i)})
    path=directory/'jobs.json';path.write_text(json.dumps({'jobs':jobs}))
    return path,jobs


def test_batch_reuses_completed_reports_without_solver(tmp_path,monkeypatch):
    path,jobs=prepare(tmp_path)
    monkeypatch.setattr(batch,'project_root',lambda:tmp_path)
    monkeypatch.setattr(batch.subprocess,'Popen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('recalculated cached job')))
    original=[(Path(j['job']).parent/'report.json').read_bytes() for j in jobs]
    report=batch.run_batch(path)
    assert report['status']=='completed'
    assert len(report['analysis_directories'])==2
    assert all(j['cached'] for j in report['jobs'])
    assert [(Path(j['job']).parent/'report.json').read_bytes() for j in jobs]==original


def test_cancel_stops_pending_queue_preserving_completed_results(tmp_path,monkeypatch):
    path,jobs=prepare(tmp_path)
    monkeypatch.setattr(batch,'project_root',lambda:tmp_path)
    (path.parent/'CANCEL').touch()
    report=batch.run_batch(path)
    assert report['status']=='cancelled'
    assert report['pending']==2
    assert all((Path(j['job']).parent/'report.json').is_file() for j in jobs)

def test_cancel_is_forwarded_to_active_child_and_stops_next_job(tmp_path,monkeypatch):
    path,jobs=prepare(tmp_path)
    first=Path(jobs[0]['job']).parent
    (first/'report.json').unlink()
    monkeypatch.setattr(batch,'project_root',lambda:tmp_path)
    monkeypatch.setattr(batch.time,'sleep',lambda _:None)
    class Child:
        def __init__(self):self.calls=0
        def poll(self):
            self.calls+=1
            if self.calls==1:return None
            (first/'report.json').write_text(json.dumps({'status':'cancelled'}))
            return 0
    def spawn(*args,**kwargs):
        (path.parent/'CANCEL').touch()
        return Child()
    monkeypatch.setattr(batch.subprocess,'Popen',spawn)
    result=batch.run_batch(path)
    assert (first/'CANCEL').exists()
    assert result['status']=='cancelled' and result['pending']==1
    assert result['jobs'][0]['status']=='cancelled'
