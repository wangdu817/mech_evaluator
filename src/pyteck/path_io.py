"""Normalize dot segments before Windows filesystem resolution."""
from pathlib import Path
import os


def absolute_path(path):
    return Path(os.path.abspath(Path(path).expanduser())).resolve()
