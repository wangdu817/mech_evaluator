"""Verify the actual project dependency closure, excluding unrelated host tools."""
from importlib import metadata
from pathlib import Path
import json
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pending = [('pyteck', set()), ('pytest', set()), ('build', set()), ('hatchling', set())]
seen, versions, errors = set(), {}, []
while pending:
    name, extras = pending.pop(0)
    key = canonicalize_name(name), tuple(sorted(extras))
    if key in seen:
        continue
    seen.add(key)
    try:
        version = metadata.version(name)
        versions[name] = version
        for value in metadata.requires(name) or []:
            req = Requirement(value)
            if req.marker and not any(req.marker.evaluate({'extra': extra}) for extra in {'', *extras}):
                continue
            actual = metadata.version(req.name)
            if actual not in req.specifier:
                errors.append(f'{name}: {req}, installed {actual}')
            pending.append((req.name, set(req.extras)))
    except metadata.PackageNotFoundError as exc:
        errors.append(str(exc))
report = {'versions': versions, 'project_dependency_errors': errors,
          'scope': 'PyTeCK runtime and test/build dependencies; unrelated inherited applications excluded'}
project = Path(__file__).resolve().parents[1]
(project/'results/runtime.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
