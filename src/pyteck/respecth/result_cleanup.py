"""Remove generated results for one output directory, retaining mechanism inputs."""
from pathlib import Path
import json
import shutil
from .runner import project_root


def discard_output_results(output):
    root = project_root().resolve()
    output = Path(output).resolve()
    if output == root or not output.is_relative_to(root):
        raise ValueError('Cleanup must target a result subdirectory inside the project')
    targets = [output/name for name in ('cache', 'figures', 'saved-batches', 'rerun-backups', 'recovery-backups')]
    targets += [output/name for name in ('manifest.json', 'progress.json', 'evaluation.json', 'run_summary.json', 'CANCEL')]
    targets += [p for p in output.iterdir() if p.is_file() and p.suffix.lower() in {'.h5', '.csv', '.png', '.pdf', '.svg', '.zip'}]
    for view in (root/'results/live-snapshots').glob('*/view/manifest.json'):
        record = json.loads(view.read_text(encoding='utf-8'))
        if Path(record.get('snapshot', {}).get('source', '.')).resolve() == output:
            targets.append(view.parent.parent)
    # Check every final target before deleting any file.
    for path in targets:
        if (not path.resolve().is_relative_to(root) or path.resolve() == root
                or output.is_relative_to(path.resolve())):
            raise ValueError(f'Cleanup target escaped project: {path}')
    removed = []
    for path in targets:
        if not path.exists(): continue
        if path.is_dir(): shutil.rmtree(path)
        else: path.unlink()
        removed.append(str(path))
    state = root/'results/result-view-state.json'
    if state.is_file():
        selected = Path(json.loads(state.read_text(encoding='utf-8'))['loaded_output']).resolve()
        if selected == output or any(selected.is_relative_to(Path(p)) for p in removed):
            state.unlink()
    return removed
