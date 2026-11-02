"""Bounded execution policies; no changes to chemistry or solver tolerances."""
from concurrent.futures import TimeoutError
import ctypes
import os
import time
import psutil

GIB = 1024**3


def memory_snapshot():
    physical = psutil.virtual_memory()
    snapshot = {'available':physical.available, 'total':physical.total, 'commit_available':None}
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
                ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended')]
        status=Status(); status.length=ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            snapshot['commit_available']=status.avail_page
    return snapshot


def pressure_reason(snapshot=None):
    snapshot=memory_snapshot() if snapshot is None else snapshot
    reserve=max(2*GIB,int(snapshot['total']*.1))
    if snapshot['available']<reserve:
        return f"Memory guard: physical memory below reserve {reserve/GIB:.2f} GiB"
    if snapshot.get('commit_available') is not None and snapshot['commit_available']<reserve:
        return f"Memory guard: Windows commit headroom below reserve {reserve/GIB:.2f} GiB"
    return ''


def pool_pressure(pool, worker_limit=2*GIB):
    reason=pressure_reason()
    if reason: return reason
    # Python 3.13 has no public terminate_workers; inspect only our owned pool.
    for process in (getattr(pool,'_processes',None) or {}).values():
        try:
            info=psutil.Process(process.pid).memory_info()
            private=getattr(info,'private',info.rss)
            if max(info.rss,private)>worker_limit:
                return f'Memory guard: owned worker {process.pid} exceeded {worker_limit/GIB:g} GiB'
        except (psutil.NoSuchProcess,psutil.AccessDenied): pass
    return ''


def stop_owned_pool(pool):
    """Emergency stop is restricted to workers owned by this executor."""
    processes=list((getattr(pool,'_processes',None) or {}).values())
    for process in processes:
        if process.is_alive(): process.terminate()
    for process in processes:
        process.join(timeout=1)
        if process.is_alive(): process.kill()


def monitored_result(pool, future, cancel_file=None):
    from .solvers import Cancelled
    while True:
        reason=pool_pressure(pool)
        if cancel_file and os.path.exists(cancel_file): reason='Analysis cancellation requested'
        if reason:
            stop_owned_pool(pool)
            raise Cancelled(reason)
        try: return future.result(timeout=.25)
        except TimeoutError: pass
