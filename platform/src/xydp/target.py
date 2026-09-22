from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
from pathlib import Path


class TargetError(ValueError):
    pass


def running_executable_paths() -> list[Path]:
    if not hasattr(ctypes, "windll"):
        return []
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (0, -1):
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    paths: list[Path] = []
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, entry.th32ProcessID)
            if process:
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                        paths.append(Path(buffer.value))
                finally:
                    kernel32.CloseHandle(process)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return paths


def is_executable_running(executable: Path) -> bool:
    wanted = str(Path(executable).resolve()).casefold()
    return any(str(path.resolve()).casefold() == wanted for path in running_executable_paths())


@dataclass(frozen=True)
class TargetInfo:
    root: Path
    mir200: Path
    envir: Path
    engine: str = "LFM2"


class TargetInspector:
    @staticmethod
    def inspect(root: Path) -> TargetInfo:
        root = Path(root).absolute()
        mir200 = root / "Mir200"
        envir = mir200 / "Envir"
        required = [mir200 / "M2Server.exe", envir, envir / "MapInfo.txt"]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise TargetError("不是有效的翎风/LFM2服务端，缺少: " + ", ".join(missing))
        return TargetInfo(root=root, mir200=mir200, envir=envir)
