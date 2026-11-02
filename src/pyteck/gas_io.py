"""Load Cantera mechanisms on Windows with Unicode project directories."""
from pathlib import Path
import os
import cantera as ct


def load_gas(path, phase=""):
    source = Path(path)
    if not source.is_file():
        return ct.Solution(str(path), phase) if phase else ct.Solution(str(path))
    source = source.resolve()
    try:
        relative = os.path.relpath(source, Path.cwd())
    except ValueError:  # Different Windows drives
        relative = str(source)
    if relative.isascii():
        return ct.Solution(relative, phase) if phase else ct.Solution(relative)
    text = source.read_text(encoding="utf-8-sig")
    return ct.Solution(yaml=text, name=phase) if phase else ct.Solution(yaml=text)
