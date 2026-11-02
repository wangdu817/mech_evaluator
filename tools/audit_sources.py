"""Snapshot/verify all pre-existing source files outside the new project."""
import hashlib
import json
from pathlib import Path
import sys

project = Path(__file__).resolve().parents[1]
root = project.parent
snapshot = project / "results" / "source-baseline.json"
current = {}
for item in root.iterdir():
    if item == project:
        continue
    files = item.rglob("*") if item.is_dir() and item.name.startswith("exp") else ([item] if item.is_file() else [])
    for file in files:
        if file.is_file():
            current[str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
if "--snapshot" in sys.argv:
    if snapshot.exists():
        raise SystemExit("Baseline already exists; do not overwrite")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Frozen source hashes: {len(current)}")
else:
    old = json.loads(snapshot.read_text(encoding="utf-8"))
    differences = [name for name in set(old) | set(current) if old.get(name) != current.get(name)]
    result = {"files": len(current), "unchanged": not differences, "differences": differences}
    (project / "results" / "source-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if differences:
        raise SystemExit(1)
