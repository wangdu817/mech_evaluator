"""Read-only access to completed results, including a batch still being solved."""
import json
from pathlib import Path
from .runner import load_run, project_root


def load_result_view(output, *, completed_snapshot=False):
    directory = Path(output).resolve()
    if not directory.is_relative_to(project_root()):
        raise ValueError('Saved result directory must be inside the project')
    progress = directory / 'progress.json'
    if progress.is_file():
        completed_snapshot = completed_snapshot or json.loads(progress.read_text(encoding='utf-8')).get('status') == 'running'
    if completed_snapshot:
        from .live_snapshot import create_completed_snapshot
        directory = create_completed_snapshot(directory)
        return directory, load_run(directory)
    try:
        return directory, load_run(directory)
    except ValueError as error:
        # Old batches may have no lightweight progress file. Preserve the
        # ownership guard in load_run, never recover or edit an active writer.
        if str(error) != 'Run is still active; wait for completion or cancel before post-processing':
            raise
    from .live_snapshot import create_completed_snapshot
    directory = create_completed_snapshot(directory)
    return directory, load_run(directory)
