from __future__ import annotations

import sys
from pathlib import Path


def platform_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2]
