"""Fail-fast target-level transaction exclusion shared by install and rollback.

Windows named mutexes leave no lock files and are released by the OS after a
crash. The process-local guard also rejects recursive entry on the same thread.
This protects cooperating platform writers; per-file hashes detect other edits.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import threading


class TargetBusyError(RuntimeError):
    pass


_guard = threading.Lock()
_held: set[str] = set()


@contextmanager
def target_lock(root: Path):
    key = os.path.normcase(str(Path(root).resolve()))
    name = hashlib.sha256(key.encode('utf-8')).hexdigest()
    with _guard:
        if key in _held:
            raise TargetBusyError(f'目标正在执行其他安装或回滚事务：{root}')
        _held.add(key)
    handle = None
    acquired = False
    kernel = None
    stream = None
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            kernel.ReleaseMutex.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.CreateMutexW(None, False, 'Global\\XYDP_Target_' + name)
            if not handle:
                raise OSError(ctypes.get_last_error(), '无法创建目标事务互斥锁')
            status = kernel.WaitForSingleObject(handle, 0)
            if status not in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
                raise TargetBusyError(f'目标正在执行其他安装或回滚事务：{root}')
            acquired = True
        else:
            import fcntl
            directory = Path(root) / '.xydp'
            directory.mkdir(parents=True, exist_ok=True)
            stream = (directory / 'transaction.lock').open('a+b')
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TargetBusyError(f'目标正在执行其他安装或回滚事务：{root}') from exc
        yield
    finally:
        if handle and kernel:
            if acquired:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
        if stream:
            stream.close()
        with _guard:
            _held.discard(key)
