from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
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


def _policy_from_data(data: object) -> SourcePolicy:
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


def _policy_to_data(policy: SourcePolicy) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "includeDirectories": list(policy.include_directories),
        "rootFiles": list(policy.root_files),
        "excludeDirectoryNames": sorted(policy.exclude_directory_names),
        "excludeSuffixes": sorted(policy.exclude_suffixes),
        "sensitiveNamePatterns": [pattern.pattern for pattern in policy.sensitive_name_patterns],
        "maxFileBytes": policy.max_file_bytes,
    }


def load_policy(path: Path) -> SourcePolicy:
    return _policy_from_data(json.loads(Path(path).read_text(encoding="utf-8")))


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


def _inside(root: Path, relative: str) -> Path:
    base = Path(root).resolve()
    candidate = (base / Path(relative)).resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise SourceAuthorityError(f"managed path escapes root: {relative}") from exc
    return candidate


def _destination_reparse(root: Path, relative: str) -> bool:
    base = Path(root).resolve()
    current = base
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.exists() and _is_reparse(current):
            return True
    return False


def plan_bootstrap(
    source_root: Path, mirror_root: Path, policy: SourcePolicy
) -> dict[str, object]:
    source = Path(source_root).resolve()
    mirror = Path(mirror_root).resolve(strict=False)
    inventory = inventory_source(source, policy)
    blockers = list(inventory["blockers"])
    changes: list[dict[str, object]] = []
    for entry in inventory["files"]:
        relative = str(entry["path"])
        destination = _inside(mirror, relative)
        destination_hash: str | None = None
        if _destination_reparse(mirror, relative):
            blockers.append(
                {
                    "code": "destination-reparse-point",
                    "path": relative,
                    "message": "destination path contains a reparse point",
                }
            )
            action = "blocked"
        elif destination.exists():
            if not destination.is_file():
                blockers.append(
                    {
                        "code": "destination-conflict",
                        "path": relative,
                        "message": "destination exists and is not a regular file",
                    }
                )
                action = "blocked"
            else:
                destination_hash = _sha256(destination)
                if destination_hash == entry["sha256"]:
                    action = "unchanged"
                else:
                    blockers.append(
                        {
                            "code": "destination-conflict",
                            "path": relative,
                            "message": "destination has different content",
                        }
                    )
                    action = "blocked"
        else:
            action = "create"
        changes.append(
            {
                "path": relative,
                "action": action,
                "sourceSha256": entry["sha256"],
                "destinationSha256": destination_hash,
            }
        )
    blockers.sort(key=lambda item: (str(item["path"]).casefold(), str(item["code"])))
    return {
        "schemaVersion": 1,
        "mode": "bootstrap-runtime-to-git",
        "sourceRoot": str(source),
        "mirrorRoot": str(mirror),
        "sourceFingerprint": inventory["sourceFingerprint"],
        "policy": _policy_to_data(policy),
        "changes": changes,
        "blockers": blockers,
        "isNoop": not blockers and all(item["action"] == "unchanged" for item in changes),
    }


def apply_bootstrap(
    plan: dict[str, object], *, confirmed: bool
) -> dict[str, object]:
    if not confirmed:
        raise SourceAuthorityError("bootstrap confirmation is required")
    if plan.get("schemaVersion") != 1 or plan.get("mode") != "bootstrap-runtime-to-git":
        raise SourceAuthorityError("invalid bootstrap plan")
    if plan.get("blockers"):
        raise SourceAuthorityError("bootstrap plan has blockers")
    policy = _policy_from_data(plan.get("policy"))
    source = Path(str(plan["sourceRoot"]))
    mirror = Path(str(plan["mirrorRoot"]))
    current_inventory = inventory_source(source, policy)
    if current_inventory["sourceFingerprint"] != plan.get("sourceFingerprint"):
        raise SourceAuthorityError("source changed after bootstrap plan")
    current_plan = plan_bootstrap(source, mirror, policy)
    if current_plan["blockers"] or current_plan["changes"] != plan.get("changes"):
        raise SourceAuthorityError("destination changed after bootstrap plan")

    copied = 0
    unchanged = 0
    for change in current_plan["changes"]:
        action = change["action"]
        if action == "unchanged":
            unchanged += 1
            continue
        if action != "create":
            raise SourceAuthorityError(f"unsupported bootstrap action: {action}")
        relative = str(change["path"])
        source_path = _inside(source, relative)
        destination = _inside(mirror, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_name(f".{destination.name}.xydp-copying")
        if pending.exists():
            pending.unlink()
        shutil.copy2(source_path, pending)
        if _sha256(pending) != change["sourceSha256"]:
            pending.unlink(missing_ok=True)
            raise SourceAuthorityError(f"copied file hash mismatch: {relative}")
        os.replace(pending, destination)
        if _sha256(destination) != change["sourceSha256"]:
            raise SourceAuthorityError(f"destination hash mismatch: {relative}")
        copied += 1

    snapshot = {
        "schemaVersion": 1,
        "sourceRoot": str(source.resolve()),
        "sourceFingerprint": current_inventory["sourceFingerprint"],
        "files": current_inventory["files"],
    }
    canonical = json.dumps(
        snapshot["files"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    snapshot["snapshotFingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    snapshot_path = mirror / "source-authority.snapshot.json"
    _write_json(snapshot_path, snapshot)
    return {
        "schemaVersion": 1,
        "mode": "bootstrap-runtime-to-git",
        "copiedFiles": copied,
        "unchangedFiles": unchanged,
        "snapshot": str(snapshot_path.resolve()),
        "sourceFingerprint": current_inventory["sourceFingerprint"],
    }


def _load_snapshot(path: Path) -> dict[str, object]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise SourceAuthorityError("invalid source authority snapshot schema")
    files = data.get("files")
    if not isinstance(files, list):
        raise SourceAuthorityError("snapshot files must be a list")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise SourceAuthorityError("snapshot file entry must be an object")
        try:
            relative = _normalized_relative(item.get("path"), "snapshot files")
        except ValueError as exc:
            raise SourceAuthorityError(str(exc)) from exc
        if relative.casefold() in seen:
            raise SourceAuthorityError(f"duplicate snapshot relative path: {relative}")
        seen.add(relative.casefold())
        digest = item.get("sha256")
        size = item.get("bytes")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SourceAuthorityError(f"invalid snapshot sha256: {relative}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise SourceAuthorityError(f"invalid snapshot byte count: {relative}")
        item["path"] = relative
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if data.get("snapshotFingerprint") != expected:
        raise SourceAuthorityError("snapshot fingerprint does not match file records")
    return data


def _managed_hash(root: Path, relative: str) -> str | None:
    if _destination_reparse(root, relative):
        raise SourceAuthorityError(f"managed path contains a reparse point: {relative}")
    path = _inside(root, relative)
    if not path.exists():
        return None
    if not path.is_file():
        raise SourceAuthorityError(f"managed path is not a regular file: {relative}")
    return _sha256(path)


def preflight_sync(
    mirror_root: Path, runtime_root: Path, snapshot_path: Path
) -> dict[str, object]:
    mirror = Path(mirror_root).resolve()
    runtime = Path(runtime_root).resolve()
    if not mirror.is_dir():
        raise SourceAuthorityError(f"mirror root is not a directory: {mirror}")
    if not runtime.is_dir():
        raise SourceAuthorityError(f"runtime root is not a directory: {runtime}")
    snapshot = _load_snapshot(snapshot_path)
    changes: list[dict[str, object]] = []
    blockers: list[dict[str, str]] = []
    files = sorted(snapshot["files"], key=lambda item: str(item["path"]).casefold())
    for item in files:
        relative = str(item["path"])
        baseline = str(item["sha256"])
        mirror_hash = _managed_hash(mirror, relative)
        runtime_hash = _managed_hash(runtime, relative)
        if mirror_hash is None:
            action = "blocked"
            blockers.append(
                {
                    "code": "mirror-missing",
                    "path": relative,
                    "message": "managed Git mirror file is missing",
                }
            )
        elif runtime_hash is None:
            action = "create-runtime"
        elif mirror_hash == baseline and runtime_hash == baseline:
            action = "unchanged"
        elif mirror_hash != baseline and runtime_hash == baseline:
            action = "update-runtime"
        elif mirror_hash == baseline and runtime_hash != baseline:
            action = "blocked"
            blockers.append(
                {
                    "code": "runtime-drift",
                    "path": relative,
                    "message": "runtime changed while Git mirror stayed at baseline",
                }
            )
        elif mirror_hash == runtime_hash:
            action = "converged"
        else:
            action = "blocked"
            blockers.append(
                {
                    "code": "three-way-conflict",
                    "path": relative,
                    "message": "Git mirror and runtime changed differently from baseline",
                }
            )
        changes.append(
            {
                "path": relative,
                "action": action,
                "baselineSha256": baseline,
                "mirrorSha256": mirror_hash,
                "runtimeSha256": runtime_hash,
            }
        )
    blockers.sort(key=lambda item: (item["path"].casefold(), item["code"]))
    no_write_actions = {"unchanged", "converged"}
    return {
        "schemaVersion": 1,
        "mode": "git-to-runtime-preflight",
        "mirrorRoot": str(mirror),
        "runtimeRoot": str(runtime),
        "snapshotFingerprint": snapshot["snapshotFingerprint"],
        "changes": changes,
        "blockers": blockers,
        "isNoop": not blockers and all(
            str(item["action"]) in no_write_actions for item in changes
        ),
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
    bootstrap_plan = subparsers.add_parser(
        "bootstrap-plan", help="生成一次性E盘到Git镜像引入计划"
    )
    bootstrap_plan.add_argument("--source-root", type=Path, required=True)
    bootstrap_plan.add_argument("--mirror-root", type=Path, required=True)
    bootstrap_plan.add_argument("--policy", type=Path, required=True)
    bootstrap_plan.add_argument("--output", type=Path, required=True)
    bootstrap_apply = subparsers.add_parser(
        "bootstrap-apply", help="确认执行一次性E盘到Git镜像引入"
    )
    bootstrap_apply.add_argument("--plan", type=Path, required=True)
    bootstrap_apply.add_argument("--policy", type=Path, required=True)
    bootstrap_apply.add_argument("--yes", action="store_true")
    sync_preflight = subparsers.add_parser(
        "sync-preflight", help="Git镜像到E盘运行副本三方只读预检"
    )
    sync_preflight.add_argument("--mirror-root", type=Path, required=True)
    sync_preflight.add_argument("--runtime-root", type=Path, required=True)
    sync_preflight.add_argument("--snapshot", type=Path, required=True)
    sync_preflight.add_argument("--output", type=Path, required=True)
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
    if args.command == "bootstrap-plan":
        plan = plan_bootstrap(
            args.source_root, args.mirror_root, load_policy(args.policy)
        )
        _write_json(args.output, plan)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "changes": len(plan["changes"]),
                    "blockers": len(plan["blockers"]),
                    "isNoop": plan["isNoop"],
                },
                ensure_ascii=False,
            )
        )
        return 2 if plan["blockers"] else 0
    if args.command == "bootstrap-apply":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        supplied_policy = _policy_to_data(load_policy(args.policy))
        if plan.get("policy") != supplied_policy:
            raise SourceAuthorityError("supplied policy differs from bootstrap plan")
        result = apply_bootstrap(plan, confirmed=args.yes)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "sync-preflight":
        report = preflight_sync(args.mirror_root, args.runtime_root, args.snapshot)
        _write_json(args.output, report)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "changes": len(report["changes"]),
                    "blockers": len(report["blockers"]),
                    "isNoop": report["isNoop"],
                },
                ensure_ascii=False,
            )
        )
        return 2 if report["blockers"] else 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
