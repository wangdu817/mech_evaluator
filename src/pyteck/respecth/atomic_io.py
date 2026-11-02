"""Retry Windows sharing conflicts while retaining atomic result publication."""
import time
from .solvers import atomic_json as _atomic_json


def atomic_json(path, data):
    for attempt in range(8):
        try:
            return _atomic_json(path, data)
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(.05 * 2**attempt, .5))
