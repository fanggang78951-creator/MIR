from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable


class SourceAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourcePolicy:
    include_directories: tuple[str, ...]
    root_files: tuple[str, ...]
    exclude_directory_names: frozenset[str]
    exclude_suffixes: frozenset[str]
    sensitive_name_patterns: tuple[re.Pattern[str], ...]
    max_file_bytes: int


def _normalized_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} entries must be non-empty relative paths")
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        pure.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"{field} entries must be relative paths: {value}")
    return pure.as_posix()


def _string_list(data: dict[str, object], name: str) -> list[str]:
    value = data.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    return list(value)


def load_policy(path: Path) -> SourcePolicy:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("source authority policy schemaVersion must be 1")
    maximum = data.get("maxFileBytes")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ValueError("maxFileBytes must be a positive integer")
    include = tuple(
        _normalized_relative(item, "includeDirectories")
        for item in _string_list(data, "includeDirectories")
    )
    roots = tuple(
        _normalized_relative(item, "rootFiles")
        for item in _string_list(data, "rootFiles")
    )
    excluded_dirs = frozenset(_string_list(data, "excludeDirectoryNames"))
    excluded_suffixes = frozenset(
        suffix.casefold() for suffix in _string_list(data, "excludeSuffixes")
    )
    try:
        patterns = tuple(
            re.compile(pattern) for pattern in _string_list(data, "sensitiveNamePatterns")
        )
    except re.error as exc:
        raise ValueError(f"invalid sensitiveNamePatterns regex: {exc}") from exc
    if len(set(include)) != len(include) or len(set(roots)) != len(roots):
        raise ValueError("policy paths must be unique")
    return SourcePolicy(
        include_directories=include,
        root_files=roots,
        exclude_directory_names=excluded_dirs,
        exclude_suffixes=excluded_suffixes,
        sensitive_name_patterns=patterns,
        max_file_bytes=maximum,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _walk_directory(
    root: Path, relative_root: str, policy: SourcePolicy, blockers: list[dict[str, str]]
) -> Iterable[tuple[str, Path]]:
    start = root / Path(relative_root)
    if not start.exists():
        blockers.append(
            {
                "code": "missing-path",
                "path": relative_root,
                "message": "managed source directory does not exist",
            }
        )
        return
    if _is_reparse(start):
        blockers.append(
            {
                "code": "reparse-point",
                "path": relative_root,
                "message": "managed source directory is a reparse point",
            }
        )
        return
    pending = [start]
    while pending:
        directory = pending.pop()
        entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if _is_reparse(path):
                blockers.append(
                    {
                        "code": "reparse-point",
                        "path": relative,
                        "message": "reparse points are not followed",
                    }
                )
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in policy.exclude_directory_names:
                    pending.append(path)
                continue
            if entry.is_file(follow_symlinks=False):
                yield relative, path


def inventory_source(source_root: Path, policy: SourcePolicy) -> dict[str, object]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise SourceAuthorityError(f"source root is not a directory: {root}")
    blockers: list[dict[str, str]] = []
    candidates: list[tuple[str, Path]] = []
    for relative in policy.root_files:
        path = root / Path(relative)
        if not path.exists():
            blockers.append(
                {
                    "code": "missing-path",
                    "path": relative,
                    "message": "managed root file does not exist",
                }
            )
        elif _is_reparse(path):
            blockers.append(
                {
                    "code": "reparse-point",
                    "path": relative,
                    "message": "managed root file is a reparse point",
                }
            )
        elif path.is_file():
            candidates.append((relative, path))
        else:
            blockers.append(
                {
                    "code": "not-a-file",
                    "path": relative,
                    "message": "managed root entry is not a regular file",
                }
            )
    for relative in policy.include_directories:
        candidates.extend(_walk_directory(root, relative, policy, blockers))

    files: list[dict[str, object]] = []
    seen: set[str] = set()
    for relative, path in sorted(candidates, key=lambda item: item[0].casefold()):
        folded = relative.casefold()
        if folded in seen:
            blockers.append(
                {
                    "code": "duplicate-path",
                    "path": relative,
                    "message": "managed path is selected more than once",
                }
            )
            continue
        seen.add(folded)
        if path.suffix.casefold() in policy.exclude_suffixes:
            continue
        if any(pattern.search(relative) for pattern in policy.sensitive_name_patterns):
            blockers.append(
                {
                    "code": "sensitive-name",
                    "path": relative,
                    "message": "relative path matches a sensitive-name rule",
                }
            )
            continue
        size = path.stat().st_size
        if size > policy.max_file_bytes:
            blockers.append(
                {
                    "code": "file-too-large",
                    "path": relative,
                    "message": f"file exceeds maxFileBytes ({size}>{policy.max_file_bytes})",
                }
            )
            continue
        files.append({"path": relative, "bytes": size, "sha256": _sha256(path)})
    files.sort(key=lambda item: str(item["path"]).casefold())
    blockers.sort(key=lambda item: (item["path"].casefold(), item["code"]))
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "schemaVersion": 1,
        "sourceRoot": str(root),
        "sourceFingerprint": fingerprint,
        "summary": {
            "managedFiles": len(files),
            "managedBytes": sum(int(item["bytes"]) for item in files),
            "blockers": len(blockers),
        },
        "files": files,
        "blockers": blockers,
    }


def _write_json(path: Path, value: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(f".{destination.name}.pending")
    pending.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(pending, destination)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="玄渊平台源码权威盘点与预检")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="只读盘点正式平台可维护源码")
    inventory.add_argument("--source-root", type=Path, required=True)
    inventory.add_argument("--policy", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "inventory":
        report = inventory_source(args.source_root, load_policy(args.policy))
        _write_json(args.output, report)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "summary": report["summary"],
                    "sourceFingerprint": report["sourceFingerprint"],
                },
                ensure_ascii=False,
            )
        )
        return 2 if report["blockers"] else 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
