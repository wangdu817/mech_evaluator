from pyteck.respecth.analysis_ui import measurement_display


def test_summary_keeps_mechanism_and_case_identity_with_display_units():
    base={'experiment_id':'set','group_id':'dg1','species':'NO','quantity':'composition',
          'instrument':'FTIR','units':'ppm','status':'success','temperature':1000.,
          'experimental':1e-4,'predicted':2e-4,'residual':1e-4}
    rows=[dict(base,mechanism='clear',case_id='case-clear'),
          dict(base,mechanism='ncho',case_id='case-ncho')]
    displayed=measurement_display(rows,{'set':'set.xml'})
    assert [r['机理'] for r in displayed]==['clear','ncho']
    assert [r['工况 ID'] for r in displayed]==['case-clear','case-ncho']
    assert all(r['XML']=='set.xml' and r['dataGroup']=='dg1' and r['温度 (K)']==1000. for r in displayed)
    assert all(abs(r['experimental']-100)<1e-10 and abs(r['predicted']-200)<1e-10 for r in displayed)
