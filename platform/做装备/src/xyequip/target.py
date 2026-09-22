from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
from pathlib import Path


class EquipmentTargetError(ValueError):
    pass


@dataclass(frozen=True)
class EquipmentTarget:
    root: Path
    m2server: Path
    envir: Path
    database: Path
    m2_running: bool = False
    engine: str = "LFM2"


def running_executable_paths() -> list[Path]:
    if not hasattr(ctypes, "windll"):
        return []
    snapshot_flag = 0x00000002
    query_limited = 0x1000

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.windll.kernel32
    snapshot = kernel.CreateToolhelp32Snapshot(snapshot_flag, 0)
    if snapshot in (0, -1):
        return []
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    result: list[Path] = []
    try:
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            process = kernel.OpenProcess(query_limited, False, entry.th32ProcessID)
            if process:
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                        result.append(Path(buffer.value))
                finally:
                    kernel.CloseHandle(process)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def inspect_target(root: Path) -> EquipmentTarget:
    root = Path(root).resolve()
    m2server = root / "Mir200" / "M2Server.exe"
    envir = root / "Mir200" / "Envir"
    database = root / "Mud2" / "DB" / "ApexM2.DB"
    required = (m2server, envir, database)
    missing = [str(item) for item in required if not item.exists()]
    if missing:
        raise EquipmentTargetError("不是有效的翎风/LFM2服务端，缺少：" + "；".join(missing))
    wanted = str(m2server.resolve()).casefold()
    running = any(str(path.resolve()).casefold() == wanted for path in running_executable_paths())
    return EquipmentTarget(root, m2server, envir, database, running)
