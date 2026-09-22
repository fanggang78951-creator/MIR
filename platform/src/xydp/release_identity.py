"""Execution-code fingerprints, independent of source/build directory names."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import types
from pathlib import Path


def _constant(value):
    if isinstance(value, types.CodeType):
        return {"code": value.co_code.hex(), "consts": [_constant(x) for x in value.co_consts],
                "names": value.co_names, "vars": value.co_varnames, "free": value.co_freevars,
                "cells": value.co_cellvars, "flags": value.co_flags, "argc": value.co_argcount,
                "posonly": value.co_posonlyargcount, "kwonly": value.co_kwonlyargcount,
                "exceptiontable": value.co_exceptiontable.hex()}
    if isinstance(value, bytes): return {"bytes": value.hex()}
    if isinstance(value, tuple): return {"tuple": [_constant(x) for x in value]}
    if isinstance(value, frozenset): return {"frozenset": sorted((_constant(x) for x in value), key=repr)}
    if isinstance(value, (str, int, float, bool)) or value is None: return value
    return {"type": type(value).__name__, "repr": repr(value)}


def code_fingerprint(code: types.CodeType) -> str:
    return hashlib.sha256(json.dumps(_constant(code), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_identity(source_root: Path) -> dict[str, str]:
    root = Path(source_root)
    files: list[tuple[str, Path]] = [
        ("xydp." + p.stem, p)
        for p in sorted((root / "xydp").glob("*.py"))
        if p.stem != "__init__"
    ]
    package = root / "xyequip" / "equipment_graphics"
    if not package.is_dir():
        package = root.parent / "做装备" / "src" / "xyequip" / "equipment_graphics"
    if package.is_dir():
        for path in sorted(package.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(package).with_suffix("")
            parts = relative.parts
            if parts[-1] == "__init__":
                module = ".".join(("xyequip", "equipment_graphics", *parts[:-1]))
            else:
                module = ".".join(("xyequip", "equipment_graphics", *parts))
            files.append((module, path))
    return {name: code_fingerprint(compile(path.read_bytes(), str(path), "exec", dont_inherit=True))
            for name, path in files}


def runtime_identity(module_names: list[str]) -> dict:
    result = {}
    for name in module_names:
        allowed = (name.startswith("xydp.") and name.count(".") == 1) or name == "xyequip.equipment_graphics" or name.startswith("xyequip.equipment_graphics.")
        if not allowed: raise ValueError("只核对平台模块及装备图形包")
        spec = importlib.util.find_spec(name)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "get_code"):
            result[name] = None
            continue
        code = spec.loader.get_code(name)
        result[name] = code_fingerprint(code) if code else None
    return result
