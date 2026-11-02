import json
from pyteck.respecth.runner import record_run_failure


def test_interruption_retains_committed_cases(tmp_path):
    (tmp_path/'cache').mkdir()
    manifest={'status':'running','created_utc':'2026-10-09T00:00:00Z','workers':1,
        'experiments':[{'id':'e','path':'test.xml'}],
        'cases':[{'id':v,'mechanism':{'id':'m'}} for v in ['a','b']], 'results':[]}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    result={'case_id':'a','status':'success','predictions':{'target':1},'validation':{'passed':True}}
    (tmp_path/'cache/a.json').write_text(json.dumps(result))
    record_run_failure(tmp_path,'import lock failure')
    updated=json.loads((tmp_path/'manifest.json').read_text())
    assert updated['status']=='interrupted'
    assert updated['pending_cases']==1
    assert updated['results']==[result]
    assert json.loads((tmp_path/'progress.json').read_text())['active']==[]
    assert json.loads((tmp_path/'cache/a.json').read_text())==result
