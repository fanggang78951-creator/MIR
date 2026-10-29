from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


DEFAULT_PROTECTED_ROOTS = (
    Path(r"D:\MirServer"),
    Path(r"D:\素材文件夹"),
    Path(r"D:\11周年"),
)


class PolicyDenied(PermissionError):
    pass


def _normalized(path: Path) -> str:
    return os.path.normcase(os.fspath(Path(path).expanduser().resolve(strict=False)))


def _is_within(path: Path, root: Path) -> bool:
    path_value = _normalized(path)
    root_value = _normalized(root)
    try:
        return os.path.commonpath([path_value, root_value]) == root_value
    except ValueError:
        return False


def is_protected_write_path(
    path: Path | str,
    protected_roots: Iterable[Path | str] = DEFAULT_PROTECTED_ROOTS,
) -> bool:
    return any(_is_within(Path(path), Path(root)) for root in protected_roots)


class WritePolicy:
    def __init__(
        self,
        allowed_write_roots: Iterable[Path | str],
        *,
        protected_roots: Iterable[Path | str] = DEFAULT_PROTECTED_ROOTS,
    ) -> None:
        self.allowed_write_roots = tuple(Path(path) for path in allowed_write_roots)
        self.protected_roots = tuple(Path(path) for path in protected_roots)

    def assert_writable(self, path: Path | str) -> Path:
        candidate = Path(path).expanduser().resolve(strict=False)
        for protected in self.protected_roots:
            if _is_within(candidate, protected):
                raise PolicyDenied(f"write target is below protected root: {protected}")
        if not self.allowed_write_roots:
            raise PolicyDenied("no allowed write root was provided")
        if not any(_is_within(candidate, root) for root in self.allowed_write_roots):
            raise PolicyDenied("write target is outside every allowed write root")
        return candidate
