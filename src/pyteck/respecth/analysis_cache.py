"""Diagnostic reuse identity excludes plotting, preserves numerical provenance."""
from pathlib import Path
import inspect
import json
import cantera as ct
from .models import digest,file_hash
from .runner import project_root
from .atomic_io import atomic_json


def analysis_reports(root=None):
    root=Path(root) if root else project_root()
    yield from (root/'results/analysis').glob('*/report.json')
    yield from (root/'results/projects').glob('*/analysis/*/report.json')


def numeric_signature():
    from .analysis_job import run_job
    root=Path(__file__).parent
    signature=digest({'cantera':ct.__version__,'job':inspect.getsource(run_job),
        'sources':{name:file_hash(root/name) for name in ['analysis.py','native_analysis.py','solvers.py','history_io.py','gas_io.py']}})
    # Only exact reviewed source revisions may reuse the preceding signature.
    # Any numerical edit produces another digest and bypasses this mapping.
    compatibility=root/'analysis_cache_compatibility.json'
    aliases=json.loads(compatibility.read_text(encoding='utf-8')).get('aliases',{}) if compatibility.exists() else {}
    return aliases.get(signature,signature)


def payload_identity(payload, component=None, *, matrix_view=False):
    case=dict(payload['case']);mechanism=dict(case['mechanism'])
    # Full chemistry identity includes original input hashes and phase/map.
    mechanism.pop('path',None);mechanism.pop('provenance',None)
    case['mechanism']=mechanism
    result=dict(payload['result']);history=Path(result.pop('history_path'))
    result.pop('metadata',None)
    settings={k:v for k,v in payload['settings'].items() if k!='top_n'}
    if component == 'sensitivity':
        # ROP species/location have no effect on sensitivity integration.
        for key in ('rop','species','row'):
            settings.pop(key,None)
        settings['sensitivity']=True
        if matrix_view:
            settings.pop('target_key',None)
    elif component == 'rop':
        # Sensitivity targets/reaction subsets have no effect on ROP.
        for key in ('sensitivity','target_key','reaction_indices','reference_time','zero_floor'):
            settings.pop(key,None)
        settings['rop']=True
    return digest({'case':case,'result':result,'settings':settings,'history_sha256':file_hash(history)})


def reusable_directory(payload, component=None):
    if component not in (None,'sensitivity','rop'):
        raise ValueError('Unknown diagnostic cache component')
    wanted=payload_identity(payload,component);signature=numeric_signature()
    target=next((t for t in payload['case'].get('targets',[]) if t.get('key')==payload['settings'].get('target_key')), {})
    matrix_target=target.get('species') if target.get('quantity') in {'composition','concentration'} else None
    # PFR's integration endpoint is independent of the displayed species.
    # JSR sensitivity steady-state checks depend on the target: keep it strict.
    allow_matrix=component=='sensitivity' and payload['case'].get('kind')=='pfr' and bool(matrix_target)
    wanted_matrix=payload_identity(payload,component,matrix_view=True) if allow_matrix else None
    registry=project_root()/'results/analysis-reuse-index.json'
    known=json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {}
    for path in analysis_reports():
        try:
            report=json.loads(path.read_text(encoding='utf-8'))
            if report.get('status')!='completed' or report.get('case',{}).get('id')!=payload['case']['id']:continue
            if component and not report.get(component):continue
            stamp=report.get('numeric_signature') or known.get(file_hash(path))
            if stamp!=signature:continue
            original=json.loads((path.parent/'job.json').read_text(encoding='utf-8'))
            exact=payload_identity(original,component)==wanted
            matrix=report.get('sensitivity',{}).get('all_species_path') if component in (None,'sensitivity') else None
            matrix_match=bool(allow_matrix and matrix and payload_identity(original,component,matrix_view=True)==wanted_matrix)
            if exact or matrix_match:
                if matrix:
                    import h5py
                    with h5py.File(matrix,'r') as saved:
                        if saved.attrs.get('case_id') != payload['case']['id'] or saved.attrs.get('mechanism_sha256') != payload['case']['mechanism']['sha256']:
                            continue
                        if matrix_match:
                            species=payload['case']['mechanism'].get('species_map',{}).get(matrix_target,matrix_target)
                            if species not in saved['species'].asstr()[:]:
                                continue
                return path.parent
        except (OSError,ValueError,KeyError):continue
    return None


def certify_reviewed_legacy_reports():
    """One-time migration after verifying this release changed only UI/plotting."""
    signature=numeric_signature();path=project_root()/'results/analysis-reuse-index.json'
    known=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    count=0
    for report_path in (project_root()/'results/analysis').glob('*/report.json'):
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('status')=='completed' and not report.get('numeric_signature'):
            payload=json.loads((report_path.parent/'job.json').read_text(encoding='utf-8'))
            payload_identity(payload)  # Require intact source history before migration.
            known[file_hash(report_path)]=signature;count+=1
    atomic_json(path,known)
    return count
