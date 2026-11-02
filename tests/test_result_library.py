from pathlib import Path
import json
from pyteck.respecth import result_library


def test_catalog_keeps_distinct_mechanisms_and_skips_history(tmp_path,monkeypatch):
    monkeypatch.setattr(result_library,'project_root',lambda:tmp_path)
    def write(path,mechanism):
        path.mkdir(parents=True)
        (path/'manifest.json').write_text(json.dumps({'status':'completed','cases':[{'mechanism':{'id':mechanism}}],
            'experiments':[{'id':'experiment'}],'results':[{'status':'success','validation':{'passed':True}}]}),encoding='utf-8')
    write(tmp_path/'results/one','audited')
    write(tmp_path/'results/two','clear')
    write(tmp_path/'results/one/cache','hidden')
    write(tmp_path/'results/analysis/job','analysis')
    rows=result_library.discover_saved_results()
    assert {tuple(r['mechanisms']) for r in rows}=={('audited',),('clear',)}


def test_persistent_view_is_independent_of_last_run(tmp_path,monkeypatch):
    monkeypatch.setattr(result_library,'project_root',lambda:tmp_path)
    directory=tmp_path/'results/comparison';directory.mkdir(parents=True)
    (directory/'manifest.json').write_text('{}',encoding='utf-8')
    from pyteck.respecth import result_access
    monkeypatch.setattr(result_access,'load_result_view',lambda path:(path,('two-mechanism-run',)))
    result_library.save_result_view(directory)
    (tmp_path/'results/ui-state.json').write_text(json.dumps({'output':'clear-only'}),encoding='utf-8')
    path,loaded=result_library.restore_result_view()
    assert path==str(directory.resolve()) and loaded==('two-mechanism-run',)


def test_batch_archive_preserves_inputs_and_history_references(tmp_path):
    from pyteck.respecth.runner import archive_previous_batch
    output=tmp_path/'run';(output/'inputs').mkdir(parents=True)
    original={'status':'completed','results':[{'history_path':'original-history.h5'}]}
    (output/'manifest.json').write_text(json.dumps(original),encoding='utf-8')
    (output/'inputs/experiment.xml').write_text('original XML',encoding='utf-8')
    saved=archive_previous_batch(output)
    (output/'manifest.json').write_text('{}',encoding='utf-8')
    (output/'inputs/experiment.xml').write_text('new XML',encoding='utf-8')
    assert json.loads((saved/'manifest.json').read_text())==original
    assert (saved/'inputs/experiment.xml').read_text()=='original XML'
