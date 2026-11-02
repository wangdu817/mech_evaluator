"""Combine independently saved assessments without solving any case."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json

from .models import digest, file_hash
from .runner import load_run, project_root
from .atomic_io import atomic_json
from .evaluation import evaluate_results
from .reporting import export_results, render_figures, export_run_summary


def combine_saved_runs(directories, output, dataset_policy="intersection", mechanisms=None):
    if len(directories) < 2:
        raise ValueError("Select at least two saved result directories")
    if dataset_policy not in {"intersection", "union"}:
        raise ValueError("Unknown dataset selection policy")
    sources = [Path(p).resolve() for p in directories]
    destination = Path(output).resolve()
    if not destination.is_relative_to(project_root()) or destination == project_root():
        raise ValueError("Comparison output must be a project subdirectory")
    if destination in sources or (destination/'manifest.json').exists():
        raise ValueError("Use a new comparison directory to preserve existing results")
    from .result_access import load_result_view
    accessible = [load_result_view(p) for p in sources]
    sources = [p for p, _ in accessible]
    runs = [run for _, run in accessible]
    ids = [set(e.id for e in run[1]) for run in runs]
    selected = set.intersection(*ids) if dataset_policy == "intersection" else set.union(*ids)
    if not selected:
        raise ValueError("No shared XML datasets; choose union explicitly")
    experiments, cases, results, identities, case_keys = {}, [], [], {}, {}
    duplicates, ignored = [], []
    origins = {}
    for source, (manifest, source_experiments, source_cases, source_results) in zip(sources, runs):
        for e in source_experiments:
            if e.id not in selected:
                ignored.append({"source": str(source), "experiment": e.id})
                continue
            frozen = source/'inputs'/f'{e.id}.xml'
            if file_hash(frozen) != e.sha256:
                raise ValueError(f"Frozen XML hash mismatch: {frozen}")
            if e.id in experiments and e.sha256 != experiments[e.id].sha256:
                raise ValueError(f"Conflicting XML identities: {e.id}")
            experiments.setdefault(e.id, e)
            origins.setdefault(e.id, frozen)
        by_id = {r.case_id:r for r in source_results}
        for case in source_cases:
            if case.experiment_id not in selected or (mechanisms is not None and case.mechanism.id not in mechanisms):
                continue
            identity = (case.mechanism.sha256, case.mechanism.phase, digest(case.mechanism.species_map))
            if case.mechanism.id in identities and identities[case.mechanism.id] != identity:
                raise ValueError(f"Mechanism label refers to different inputs: {case.mechanism.id}")
            identities[case.mechanism.id] = identity
            # Prior runs retain their original software/case IDs. First source wins only
            # for an identical model/condition/observable combination; every choice is logged.
            key = digest({"mechanism": case.mechanism.id, "identity":identity,
                "experiment":case.experiment_id, "condition":asdict(case.condition),
                "config":{k:v for k,v in case.config.items() if k not in {"_cancel_file","_engine_fingerprint"}},
                "targets":case.targets, "role":case.role, "predecessor":case.predecessor})
            if key in case_keys:
                duplicates.append({"source":str(source), "case":case.id,"kept":case_keys[key]})
                continue
            case_keys[key] = case.id
            if case.id in {c.id for c in cases}:
                raise ValueError("Conflicting duplicate case ID")
            cases.append(case)
            if case.id not in by_id:
                raise ValueError(f"Saved result missing for {case.id}")
            results.append(by_id[case.id])
    if not cases:
        raise ValueError("No selected mechanism cases")
    # Avoid double-scoring alternate physical models for the same original measurement.
    observations = {}
    for case in cases:
        if case.role != 'scoring': continue
        for target in case.targets:
            for point in target['point_indices']:
                key = (case.mechanism.id,target['key'],point)
                if key in observations:
                    raise ValueError("Same mechanism/measurement has alternate saved models; select one source run")
                observations[key] = case.id
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'inputs').mkdir(exist_ok=True)
    for identity, source in origins.items():
        (destination/'inputs'/f'{identity}.xml').write_bytes(source.read_bytes())
    config = dict(runs[0][0]['config'])
    config['output'] = str(destination)
    config['datasets'] = [e.path for e in experiments.values()]
    config['mechanisms'] = [{"id":m,"path":next(c.mechanism.path for c in cases if c.mechanism.id==m)} for m in identities]
    manifest = {"schema_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),"status":"completed",
        "cantera":runs[0][0].get('cantera'),"software":runs[0][0].get('software',{}),"config":config,
        "experiments":[asdict(e) for e in experiments.values()],"cases":[asdict(c) for c in cases],
        "results":[asdict(r) for r in results],"warnings":[],"saved_comparison":{
            "sources":[str(p) for p in sources],"source_software":[r[0].get('software',{}) for r in runs],
            "dataset_policy":dataset_policy,"excluded_datasets":ignored,"duplicate_cases_first_source_kept":duplicates,
            "simulations_executed":0,"histories":"References to original saved HDF5 files"}}
    atomic_json(destination/'manifest.json',manifest)
    exp = list(experiments.values())
    evaluation = evaluate_results(exp,results,config.get('scoring',{}),cases)
    atomic_json(destination/'evaluation.json',evaluation)
    export_run_summary(manifest)
    export_results({"output":str(destination),"evaluation":evaluation,"cases":cases})
    render_figures(exp,{"cases":cases,"results":results},{"output":str(destination/'figures')})
    return manifest
