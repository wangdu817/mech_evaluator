"""Read-only real-library workload audit; does not submit any simulation."""
from pathlib import Path
from dataclasses import asdict
import json
import time
from pyteck.respecth.runner import load_config, prepare_run
from pyteck.respecth.workload import preview_workload

root = Path(__file__).resolve().parents[1]
start = time.monotonic()
config = load_config(root/'results/ui-run/precheck-config.yaml')
experiments, cases, notes = prepare_run(config)
plan = preview_workload(cases, config)
previous = json.loads((Path(config.output)/'manifest.json').read_text(encoding='utf-8'))
previous_ids = {c['id'] for c in previous['cases']}
plan['previous_case_identity_matches'] = len(previous_ids & {c.id for c in cases})
plan['xml_count'] = len(experiments)
plan['warnings'] = notes
plan['elapsed_seconds'] = time.monotonic()-start
plan['mechanism_validation'] = {c.mechanism.id: {'phase':c.mechanism.phase, 'species':len(c.mechanism.species),
    'transport':c.mechanism.transport, 'provenance':c.mechanism.provenance} for c in cases}
destination = root/'docs/delivery/workload-verification.json'
destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in plan.items() if k not in {'mechanism_validation','warnings'}}, ensure_ascii=False, indent=2))
