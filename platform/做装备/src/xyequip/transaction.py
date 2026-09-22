from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".xydp.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
