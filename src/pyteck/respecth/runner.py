"""Resumable per-case process execution with atomic manifests."""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import json
import multiprocessing
import os
import threading
import platform
import importlib.metadata
import importlib
import ctypes
import psutil
import math
import shutil
import uuid
import time
from contextlib import ExitStack
from collections import Counter

import cantera as ct
import yaml

from .models import RunConfig, result_from_dict
from .reader import load_experiment
from .cases import build_cases, prepare_mechanism
from .solvers import simulate_case
from .atomic_io import atomic_json
from .evaluation import evaluate_results
from .._version import __version__
from ..path_io import absolute_path
from .yaml_io import load_yaml


def project_root():
    workspace = os.environ.get('PYTECK_WORKSPACE')
    if workspace:
        return Path(workspace).expanduser().resolve()
    for path in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if path.is_dir() and (path / "UPSTREAM.json").exists():
            return path
    return Path.cwd().resolve()


def load_config(path):
    path = absolute_path(path)
    return RunConfig.from_dict(load_yaml(path.read_text(encoding="utf-8-sig")), path.parent)


def _safe_output(config):
    output = Path(config.output).resolve()
    if not output.is_relative_to(project_root()):
        raise ValueError("Output must remain inside the new pyteck-respecth project directory")
    if output == project_root():
        raise ValueError("Use a results subdirectory rather than the project root")
    output.mkdir(parents=True, exist_ok=True)
    return output


def prepare_run(config):
    output = _safe_output(config)
    experiments = [load_experiment(p) for p in config.datasets]
    ids = [e.id for e in experiments]
    if len(ids) != len(set(ids)):
        raise ValueError("Same experiment selected more than once")
    for name in ("rtol", "atol", "steady_threshold", "steady_floor", "width", "validation_relative"):
        if name in config.solver and config.solver[name] <= 0:
            raise ValueError(f"solver.{name} must be positive")
    mechanisms = [prepare_mechanism({**m, "prepared_dir": str(output / "prepared")}) for m in config.mechanisms]
    # Per-mechanism grids change generated conditions, not numerical identities
    # of unchanged experimental points or unchanged existing curve points.
    if any('grid' in m for m in config.mechanisms):
        cases, warnings = [], []
        for entry, mechanism in zip(config.mechanisms, mechanisms):
            selected = replace(config, grid=entry.get('grid', config.grid))
            generated, notes = build_cases(experiments, selected, [mechanism])
            cases.extend(generated)
            warnings.extend(f'{mechanism.id}: {note}' for note in notes)
    else:
        cases, warnings = build_cases(experiments, config, mechanisms)
    return experiments, cases, warnings


def _restore_initial(case, predecessor):
    if predecessor.status != "success":
        return False
    import h5py
    with h5py.File(predecessor.history_path, "r") as history:
        names = json.loads(history.attrs["species_names"])
        fractions = history["mole_fractions"][-1]
        case.config["initial_X"] = {name: float(value) for name, value in zip(names, fractions)}
    return True


def _publish_progress(output, manifest, done, active, pending):
    """Small live snapshot; histories and full input library stay on disk."""
    experiments = {e['id']: e['path'] for e in manifest['experiments']}
    active_records = [{'id':c.id, 'XML':experiments[c.experiment_id], 'group_id':c.group_id,
        'point_indices':c.point_indices, 'mechanism':c.mechanism.id, 'kind':c.kind,
        'condition':asdict(c.condition), 'model':c.config} for c in active.values()]
    latest = next(reversed(done.values()), None)
    snapshot = {'schema_version':1, 'status':manifest['status'], 'created_utc':manifest['created_utc'],
        'finished_utc':manifest.get('finished_utc'), 'updated_utc':datetime.now(timezone.utc).isoformat(),
        'total_cases':len(manifest['cases']), 'completed_cases':len(done),
        'status_counts':dict(Counter(r.status for r in done.values())), 'active':active_records,
        'pending_cases':pending, 'workers':manifest['workers'], 'output':str(output),
        'mechanisms':sorted({c['mechanism']['id'] for c in manifest['cases']}),
        'xml_count':len(manifest['experiments']),
        'cache_hits':len(manifest.get('cache_hits', [])), 'submitted_cases':len(manifest.get('submitted_cases', [])),
        'latest_result': {'case_id':latest.case_id,'status':latest.status,'reason':latest.reason} if latest else None}
    atomic_json(output/'progress.json', snapshot)


def run_project(config, progress=None, cancel_event: threading.Event | None = None, *, force_rerun=False, discard_previous=False):
    if discard_previous and not force_rerun:
        raise ValueError('Deleting previous results requires an explicit full rerun')
    if not isinstance(config, RunConfig):
        config = RunConfig.from_dict(config)
    output = _safe_output(config)
    lock = output / "run.lock"
    # Exclusive output ownership; a UI rerun cannot start a second writer.
    if lock.exists():
        try:
            owner = json.loads(lock.read_text(encoding="utf-8"))
            pid = owner["pid"]
            if pid == os.getpid():
                alive = any(t.ident == owner["thread"] and t.is_alive() for t in threading.enumerate())
            elif os.name == "nt":
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    alive = True
                else:
                    alive = ctypes.windll.kernel32.GetLastError() == 5
            else:
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True
            if not alive:
                lock.unlink()
        except (ValueError, KeyError, OSError):
            # Unknown owner: do not override another writer; leave a clear error.
            pass
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(descriptor, "w", encoding="utf-8") as owner_file:
        json.dump({"pid": os.getpid(), "thread": threading.get_ident()}, owner_file)
    try:
        return _run(config, output, progress, cancel_event, force_rerun=force_rerun, discard_previous=discard_previous)
    except Exception as error:
        record_run_failure(output, str(error))
        raise
    finally:
        lock.unlink(missing_ok=True)


def record_run_failure(output, reason):
    """Commit truthful interrupted state, retaining independently written caches."""
    output=Path(output)
    path=output/'manifest.json'
    if not path.exists():
        return
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('status')!='running':
        return
    results={r['case_id']:r for r in manifest.get('results',[])}
    for case in manifest['cases']:
        cache=output/'cache'/f"{case['id']}.json"
        if cache.exists():
            try:
                result=json.loads(cache.read_text(encoding='utf-8'))
                if result.get('case_id')==case['id']:
                    results[case['id']]=result
            except (OSError, ValueError):
                pass
    manifest.update(status='interrupted',reason=reason,active_cases=[],
        pending_cases=len(manifest['cases'])-len(results),
        results=[results[c['id']] for c in manifest['cases'] if c['id'] in results],
        finished_utc=datetime.now(timezone.utc).isoformat())
    atomic_json(path,manifest)
    _publish_progress(output,manifest,{k:result_from_dict(v) for k,v in results.items()},{},manifest['pending_cases'])


def archive_previous_batch(output):
    """Retain completed batch metadata before another selection replaces it."""
    source = output / 'manifest.json'
    if not source.is_file():
        return None
    previous = json.loads(source.read_text(encoding='utf-8'))
    if previous.get('status') == 'running' or not previous.get('results'):
        return None
    destination = output / 'saved-batches' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    destination.mkdir(parents=True)
    for name in ('manifest.json', 'config.yaml', 'evaluation.json', 'run_summary.json'):
        if (output / name).is_file():
            shutil.copy2(output / name, destination / name)
    if (output / 'inputs').is_dir():
        shutil.copytree(output / 'inputs', destination / 'inputs')
    return destination


def _run(config, output, progress, cancel_event, *, force_rerun=False, discard_previous=False):
    removed = []
    if discard_previous:
        # Validate new inputs before deleting existing output, under owner lock.
        experiments, cases, warnings = prepare_run(config)
        from .result_cleanup import discard_output_results
        removed = discard_output_results(output)
    # The exclusive owner lock is already held. Preserve the previous crashed
    # batch before new selections can replace its input snapshots and manifest.
    old_manifest = output/'manifest.json'
    if old_manifest.exists() and json.loads(old_manifest.read_text(encoding='utf-8')).get('status') == 'running':
        record_run_failure(output, 'Previous owner stopped; committed results preserved before resume')
    archived = archive_previous_batch(output)
    if not discard_previous:
        experiments, cases, warnings = prepare_run(config)
    backup = ''
    if force_rerun and not discard_previous:
        previous = [p for c in cases for p in (output/'cache'/f'{c.id}.json', output/'cache'/f'{c.id}.h5') if p.is_file()]
        if previous or (output/'manifest.json').is_file():
            destination = output/'rerun-backups'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
            (destination/'cache').mkdir(parents=True)
            for path in previous:
                shutil.copy2(path,destination/'cache'/path.name)
            source = archived or output
            for name in ('manifest.json','config.yaml','evaluation.json','run_summary.json'):
                if (source/name).is_file():shutil.copy2(source/name,destination/name)
            if (source/'inputs').is_dir():shutil.copytree(source/'inputs',destination/'inputs')
            # Backed-up manifests must reference the preserved histories, not files about to be replaced.
            for manifest_path in [destination/'manifest.json', *(([archived/'manifest.json']) if archived else [])]:
                if not manifest_path.exists(): continue
                saved=json.loads(manifest_path.read_text(encoding='utf-8'))
                for result in saved.get('results',[]):
                    retained=destination/'cache'/f"{result['case_id']}.h5"
                    if retained.is_file(): result['history_path']=str(retained)
                atomic_json(manifest_path,saved)
            backup = str(destination)
    # Freeze the source XML used for this run; redraw does not depend on later source edits.
    frozen = output / "inputs"
    frozen.mkdir(exist_ok=True)
    for experiment in experiments:
        (frozen / f"{experiment.id}.xml").write_bytes(Path(experiment.path).read_bytes())
    cancel_file = output / "CANCEL"
    cancel_file.unlink(missing_ok=True)
    config_record = config.to_dict()
    (output / "config.yaml").write_text(yaml.safe_dump(config_record, allow_unicode=True, sort_keys=False), encoding="utf-8")
    manifest = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                "status": "running", "cantera": ct.__version__, "config": config_record,
                "software": {"pyteck": __version__, "python": platform.python_version(), **{
                    name: importlib.metadata.version(name) for name in ("numpy", "scipy", "matplotlib", "h5py", "streamlit")}},
                "experiments": [asdict(e) for e in experiments], "cases": [asdict(c) for c in cases],
                "warnings": warnings, "results": []}
    manifest['execution'] = {'force_rerun':bool(force_rerun),'cache_backup':backup,
                             'discard_previous':bool(discard_previous),'removed_result_paths':removed,
                             'previous_batch': str(archived) if archived else ''}
    atomic_json(output / "manifest.json", manifest)
    workers = config.workers or min(4, max(1, (os.cpu_count() or 1)-1))
    manifest["workers"] = workers
    manifest["active_cases"] = []
    remaining = list(cases)
    done, active = {}, {}
    from .recovery import verified_history
    from .workload import cached_result, accepts_cached, reusable_results
    reusable = reusable_results(config, force=force_rerun)
    manifest["reused_cases"] = []
    manifest['cache_hits'] = []
    manifest['submitted_cases'] = []
    # Account for every reusable result before submitting new work, so live
    # progress starts at the existing processed count rather than at zero.
    pending = []
    for case in remaining:
        cached = cached_result(case, output, reusable, force=force_rerun)
        if accepts_cached(cached, config.retry_failed):
            if case.id in reusable and cached.metadata.get('reused_from') == reusable[case.id][1]:
                atomic_json(output/'cache'/f'{case.id}.json', asdict(cached))
                manifest['reused_cases'].append({'case_id':case.id,'source':cached.metadata['reused_from']})
            manifest['cache_hits'].append({'case_id':case.id,'status':cached.status,
                'source':cached.metadata.get('reused_from', str(output))})
            done[case.id] = cached
        else:
            pending.append(case)
    remaining = pending
    manifest['results'] = [asdict(done[c.id]) for c in cases if c.id in done]
    manifest['pending_cases'] = len(remaining)
    atomic_json(output/'manifest.json', manifest)
    _publish_progress(output, manifest, done, active, len(remaining))
    if progress:
        progress(len(done), len(cases), '', 'cached')
    cancelled = False
    published_state = None
    # Restart drained pools explicitly; avoid accumulating native solver allocations
    # and avoid ProcessPoolExecutor max_tasks_per_child replacement hangs.
    last_checkpoint = time.monotonic()
    batch_submitted = 0
    # Resolve the entry before scheduling, not repeatedly from a background
    # thread while Streamlit may reload package modules.
    entry = importlib.import_module("pyteck.respecth.process_entry").execute_case
    with ExitStack() as stack:
        pool = stack.enter_context(ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")))
        while remaining or active:
            from .memory_control import pool_pressure,stop_owned_pool
            memory_reason=pool_pressure(pool) if not cancelled else ''
            if memory_reason:
                cancelled = True
                cancel_file.touch()
                manifest['warnings'].append(memory_reason+'; committed results retained; resume when memory is available')
                manifest['execution']['memory_stop_reason']=memory_reason
                # A native integration may block between Python callbacks.
                # Do not wait until Windows kills the UI and all calculations.
                stop_owned_pool(pool)
                from .models import CaseResult
                for future,case in list(active.items()):
                    done[case.id]=CaseResult(case.id,'cancelled',reason=memory_reason)
                active.clear()
            if not active and batch_submitted >= workers*8:
                pool.shutdown(wait=True)
                pool = stack.enter_context(ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")))
                batch_submitted = 0
            if (cancel_event and cancel_event.is_set()) or cancel_file.exists():
                cancelled = True
                cancel_file.touch()
            if not cancelled:
                available_flames = config.flame_workers - sum(c.kind in {"flame", "burner_profile"} for c in active.values())
                for case in list(remaining):
                    if len(active) >= workers or batch_submitted >= workers*8:
                        break
                    if case.kind in {"flame", "burner_profile"} and available_flames <= 0:
                        continue
                    if case.predecessor and case.predecessor not in done:
                        continue
                    cache = output / "cache" / f"{case.id}.json"
                    if case.issues:
                        result = simulate_case(case, output, cancel_file)
                        done[case.id] = result
                        atomic_json(cache, asdict(result))
                        remaining.remove(case)
                        if progress:
                            progress(len(done),len(cases),case.id,result.status)
                        continue
                    if case.predecessor and not _restore_initial(case, done[case.predecessor]):
                        from .models import CaseResult
                        result = CaseResult(case.id, "solver_failed", reason="Continuation predecessor did not succeed")
                        done[case.id] = result
                        atomic_json(cache, asdict(result))
                        remaining.remove(case)
                        continue
                    future = pool.submit(entry, asdict(case), str(output), str(cancel_file))
                    batch_submitted += 1
                    manifest['submitted_cases'].append(case.id)
                    active[future] = case
                    remaining.remove(case)
                    if progress:
                        progress(len(done), len(cases), case.id, "running")
                    if case.kind in {"flame", "burner_profile"}:
                        available_flames -= 1
            if cancelled:
                from .models import CaseResult
                for case in remaining:
                    done[case.id] = CaseResult(case.id, "cancelled", reason="Cancelled before submission")
                remaining.clear()
                for future, case in list(active.items()):
                    if future.cancel():
                        done[case.id] = CaseResult(case.id, "cancelled", reason="Cancelled in queue")
                        active.pop(future)
            if active:
                completed, _ = wait(active, timeout=.25, return_when=FIRST_COMPLETED)
                for future in completed:
                    case = active.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        from .models import CaseResult
                        result = CaseResult(case.id, "solver_failed", reason=f"Worker error: {exc}")
                    done[case.id] = result
                    atomic_json(output / "cache" / f"{case.id}.json", asdict(result))
                    if progress:
                        progress(len(done), len(cases), case.id, result.status)
            elif remaining and not cancelled:
                # If no task can advance, do not spin forever on a broken continuation graph.
                ready = any(not c.predecessor or c.predecessor in done for c in remaining)
                if not ready:
                    raise RuntimeError("Unresolvable continuation dependency")
            state = (len(done), tuple(c.id for c in active.values()), len(remaining), cancelled)
            if state != published_state:
                manifest["active_cases"] = list(state[1])
                manifest["pending_cases"] = len(remaining)
                _publish_progress(output, manifest, done, active, len(remaining))
                if time.monotonic()-last_checkpoint >= 30:
                    manifest["results"] = [asdict(done[c.id]) for c in cases if c.id in done]
                    atomic_json(output / "manifest.json", manifest)
                    last_checkpoint = time.monotonic()
                published_state = state
    results = [done[c.id] for c in cases]
    manifest.update(results=[asdict(r) for r in results], cases=[asdict(c) for c in cases],
                    status="cancelled" if cancelled else "completed", active_cases=[], pending_cases=0,
                    finished_utc=datetime.now(timezone.utc).isoformat())
    atomic_json(output / "manifest.json", manifest)
    _publish_progress(output, manifest, done, {}, 0)
    if manifest['execution'].get('memory_stop_reason'):
        # Defer large scoring tables and image generation until memory recovers.
        return manifest
    evaluation = evaluate_results(experiments, results, config.scoring, cases)
    atomic_json(output / "evaluation.json", evaluation)
    from .reporting import export_results, render_figures, export_run_summary
    export_run_summary(manifest)
    export_results({"output": str(output), "evaluation": evaluation, "cases": cases})
    render_figures(experiments, {"cases": cases, "results": results}, {**config.figure, "output": str(output / "figures")})
    return manifest


def load_run(output):
    from .models import case_from_dict
    output = Path(output).resolve()
    if not output.is_relative_to(project_root()):
        raise ValueError("Saved result directory must be inside the project")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get('snapshot_mechanisms'):
        for case in manifest['cases']:
            reference = case.pop('_snapshot_mechanism')
            case['mechanism'] = manifest['snapshot_mechanisms'][reference]
    if manifest["status"] == "running":
        # A stale manifest after OOM must not conceal independently committed cases.
        lock = output/'run.lock'
        if lock.exists():
            try:
                owner = json.loads(lock.read_text(encoding='utf-8'))
                pid = int(owner['pid'])
                alive = (any(t.ident == owner['thread'] and t.is_alive() for t in threading.enumerate())
                         if pid == os.getpid() else psutil.pid_exists(pid))
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError('Run owner cannot be verified; do not load until the owner is confirmed stopped')
            if alive:
                raise ValueError('Run is still active; wait for completion or cancel before post-processing')
            lock.unlink()
        from .recovery import recover_interrupted_run
        manifest = recover_interrupted_run(output)
    experiments = []
    for record in manifest["experiments"]:
        frozen = output / 'inputs' / f"{record['id']}.xml"
        from .models import file_hash
        if record.get('sha256') and file_hash(frozen) != record['sha256']:
            raise ValueError(f'Frozen XML does not match saved input hash: {frozen}; original results retained')
        experiment = load_experiment(frozen)
        # Restore original identity/provenance after reading the frozen bytes under a different name.
        experiment.id, experiment.path = record["id"], record["path"]
        for series, original in zip(experiment.observations, record["observations"]):
            series.id = original["id"]
        experiments.append(experiment)
    cases = [case_from_dict(c) for c in manifest["cases"]]
    results = [result_from_dict(r) for r in manifest["results"]]
    from .models import clean_obsolete_options
    import h5py
    by_id={r.case_id:r for r in results}
    retired='Concentration basis requires explicit wet/dry confirmation'
    for case in cases:
        result=by_id.get(case.id)
        if case.config.get('concentration_basis')=='dry' and result and result.status=='success':
            try:
                with h5py.File(result.history_path,'r') as history:
                    if str(history.attrs.get('case_id',''))!=case.id:
                        raise ValueError('Stored history identity mismatch')
                    names=json.loads(history.attrs['species_names'])
                    predictions=dict(result.predictions)
                    for target in case.targets:
                        if not target.get('species'): continue
                        species=case.mechanism.species_map.get(target['species'],target['species'])
                        field='concentrations' if target['units'] in {'mol/m3','mol/cm3'} else 'mole_fractions'
                        predictions[target['key']]=float(history[field][-1,names.index(species)])
                    result.metadata={**result.metadata,'legacy_reported_predictions':result.predictions,
                        'prediction_view':'actual stored reactor mole fractions/concentrations'}
                    result.predictions=predictions
            except (OSError,KeyError,ValueError) as error:
                result.status='unverified'
                result.reason=f'Cannot recover actual concentrations from legacy history: {error}'
        case.config=clean_obsolete_options(case.config)
        case.issues=[i for i in case.issues if i!=retired]
        if result and retired in result.reason:
            result.metadata={**result.metadata,'legacy_reason':result.reason}
            result.reason='旧版本输入限制导致未计算；新版已取消此限制，请重新运行该工况'
    from .recovery import verified_history
    for result in results:
        if result.status=='success' and not verified_history(asdict(result)):
            result.status='unverified'
            result.reason='Saved success has missing, incomplete or inconsistent committed history; retry this case'
    manifest['config']=clean_obsolete_options(manifest['config'])
    manifest['cases']=[asdict(c) for c in cases]
    manifest['results']=[asdict(r) for r in results]
    return manifest, experiments, cases, results
