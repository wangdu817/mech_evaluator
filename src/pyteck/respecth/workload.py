"""Read-only workload accounting using the executor's cache acceptance rules."""
from dataclasses import asdict
from pathlib import Path
from collections import Counter
import json
import math

from .models import result_from_dict
from .recovery import verified_history


def cached_result(case, output, reusable=None, *, force=False):
    if force:
        return None
    result = None
    path = Path(output) / 'cache' / f'{case.id}.json'
    try:
        value = result_from_dict(json.loads(path.read_text(encoding='utf-8')))
        if value.case_id != case.id:
            value = None
        elif value.status == 'success' and (not verified_history(asdict(value)) or
                any(t['key'] not in value.predictions or not math.isfinite(value.predictions[t['key']]) for t in case.targets)):
            value = None
        elif value.status in {'success', 'unverified', 'no_ignition'} and not Path(value.history_path).is_file():
            value = None
        result = value
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if (result is None or result.status != 'success') and case.id in (reusable or {}):
        prior, origin = reusable[case.id]
        if all(t['key'] in prior.predictions and math.isfinite(prior.predictions[t['key']]) for t in case.targets):
            result = result_from_dict(asdict(prior))
            result.metadata = {**result.metadata, 'reused_from': origin}
    return result


def reusable_results(config, *, force=False):
    from .runner import load_run
    reusable = {}
    for directory in ([] if force else config.reuse_results):
        if Path(directory).resolve() == Path(config.output).resolve():
            continue
        _, _, _, results = load_run(directory)
        for result in results:
            if verified_history(asdict(result)):
                reusable.setdefault(result.case_id, (result, str(directory)))
    return reusable


def accepts_cached(result, retry_failed):
    return bool(result and (result.status == 'success' or
                            (not retry_failed and result.status != 'cancelled')))


def preview_workload(cases, config, *, force=False):
    reusable = reusable_results(config, force=force)
    rows = {}
    for case in cases:
        row = rows.setdefault(case.mechanism.id, Counter(total=0, processed=0, success=0,
            retained_failed=0, pending=0, blocked=0, new_solves=0, scoring=0, dense=0))
        row['total'] += 1
        row['scoring' if case.role == 'scoring' else 'dense'] += 1
        result = cached_result(case, config.output, reusable, force=force)
        if accepts_cached(result, config.retry_failed):
            row['processed'] += 1
            row['success' if result.status == 'success' else 'retained_failed'] += 1
        else:
            row['pending'] += 1
            row['blocked' if case.issues else 'new_solves'] += 1
    totals = Counter()
    for row in rows.values():
        totals.update(row)
    return {'mechanisms': [{'mechanism': name, **dict(row)} for name, row in rows.items()],
            'totals': dict(totals)}
