"""Inspect wheel/sdist, then import from the wheel extraction rather than source."""
from pathlib import Path
import json
import sys
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
wheel = next((root/'dist').glob('*.whl'))
sdist = next((root/'dist').glob('*.tar.gz'))
required = [p.name for p in (root/'src/pyteck/respecth').glob('*.py')]
destination = root/'.cache/wheel-install'
with zipfile.ZipFile(wheel) as package:
    names = package.namelist()
    for name in required:
        assert f'pyteck/respecth/{name}' in names
    assert 'pyteck/respecth/cache_compatibility.json' in names
    assert 'pyteck/simulation.py' in names and 'pyteck/eval_model.py' in names
    assert 'pyteck/gas_io.py' in names and 'pyteck/path_io.py' in names
    package.extractall(destination)
with tarfile.open(sdist) as package:
    names = package.getnames()
    for suffix in ('SPEC.md', 'README_ReSpecTh.md', 'docs/validation/ACCEPTANCE.md', 'UPSTREAM.json',
                   'start.ps1', 'setup.ps1', '一键启动.bat', 'tools/launch_ui.py', 'DELIVERY.md', 'examples/respecth/demo.yaml', 'tools/acceptance_smoke.py', '.streamlit/config.toml', 'docs/validation/NATIVE_ANALYSIS_VALIDATION.md'):
        assert any(name.endswith('/'+suffix) for name in names)
sys.path.insert(0, str(destination))
import pyteck
from pyteck.respecth import load_experiment
assert Path(pyteck.__file__).is_relative_to(destination)
experiment = load_experiment(root/'examples/respecth/synthetic-pfr.xml')
assert experiment.kind == 'pfr'
report = {'wheel': wheel.name, 'sdist': sdist.name, 'extension_modules': len(required),
          'upstream_modules_present': True, 'wheel_import_path': pyteck.__file__, 'parse_from_wheel': True}
(root/'docs/delivery/package-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
