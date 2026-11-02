"""Audit actual completed results without rerunning or changing source inputs."""
from pathlib import Path
from collections import Counter
import csv
import json
import hashlib
import h5py
from PIL import Image
from pyteck.respecth.runner import load_run

root = Path(__file__).resolve().parents[1]
directory = root/'results/actual-audited/full'
manifest, experiments, cases, results = load_run(directory)
assert manifest['status'] == 'completed' and len(results) == len(cases) == 876
assert sum(len(g.points) for e in experiments for g in e.groups) == 1000
for experiment in experiments:
    assert hashlib.sha256(Path(experiment.path).read_bytes()).hexdigest() == experiment.sha256
source = cases[0].mechanism.provenance['inputs']['path']
assert hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() == source['sha256']
for case, result in zip(cases, results):
    assert case.id == result.case_id
    if result.status == 'success':
        assert result.validation['passed'] is True
        with h5py.File(result.history_path) as history:
            assert history.attrs['case_id'] == case.id
            assert 'units' in history.attrs and 'species_names' in history.attrs
            assert len(history['time']) > 1
with (directory/'comparison.csv').open(encoding='utf-8-sig',newline='') as stream:
    rows = list(csv.DictReader(stream))
assert len(rows) == 5577
failed = [r for r in rows if r['status'] in {'solver_failed','invalid_input'}]
assert all(r['predicted'] == '' for r in failed)
evaluation = json.loads((directory/'evaluation.json').read_text(encoding='utf8'))
assert evaluation['formal']['ranking'] == []
references = json.loads((root/'results/actual-audited/reference-reactors.json').read_text())
references['jsr'] = json.loads((root/'results/actual-audited/reference-jsr-950.json').read_text())
by_id = {r.case_id:r for r in results}
reference_comparison = {}
for kind, reference in references.items():
    result = by_id[reference['case_id']]
    errors = {k:abs(result.predictions[k]-v)/max(abs(v),1e-10) for k,v in reference['predictions'].items()}
    assert max(errors.values()) < .01
    reference_comparison[kind] = {'max_relative_difference':max(errors.values()),'passed':True}
figures = list((directory/'figures').glob('*.png'))
for figure in figures:
    with Image.open(figure) as image:
        assert abs(image.info['dpi'][0]-300) < .1
    assert figure.with_suffix('.pdf').exists() and figure.with_suffix('.svg').exists()
report = {'mechanism': source, 'source_hashes_unchanged': True, 'experiments':len(experiments),
    'raw_points':1000,'physical_cases':len(cases),'measurement_rows':len(rows),
    'case_status_counts':dict(Counter(r.status for r in results)),
    'measurement_status_counts':dict(Counter(r['status'] for r in rows)),
    'validated_hdf5':sum(r.status=='success' for r in results),
    'failed_predictions_blank':True,'formal_ranking_ineligible':True,
    'reference_comparison':reference_comparison,'png_300_dpi_pdf_svg':len(figures)}
(root/'results/actual-audited/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
