# -*- coding: utf-8 -*-
"""Stage and deploy the complete weapon/clothing action resource bundle.

The compiler never writes the formal client directly.  It first produces a
full staging copy, reads the result back, then deploys all affected files as a
single recoverable group.  The launcher patch source participates only for
the three static icon libraries it actually owns.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from .action_resource_bundle import (
    ActionResourceError,
    build_action_manifest,
    compile_action_sequences,
    compile_static_libraries,
    render_static_icons,
    write_candidate_resource_map,
)


LIBRARIES = ("Items", "StateItem", "DnItems", "Weapon", "Hum")
STATIC_LIBRARIES = ("Items", "StateItem", "DnItems")


class CompleteResourceImportError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _read_count(path: Path) -> int:
    data = Path(path).read_bytes()
    if len(data) < 48 or (len(data) - 48) % 4:
        raise CompleteResourceImportError(f"WZX 格式不合法: {path}")
    return int.from_bytes(data[44:48], "little")


def _pair_paths(data_dir: Path, libraries: tuple[str, ...]) -> tuple[Path, ...]:
    return tuple(data_dir / f"{library}{ext}" for library in libraries for ext in (".wzl", ".wzx"))


def stage_client_pairs(formal_data: Path, run_root: Path) -> Path:
    """Copy all formal pairs to an isolated per-run staging directory."""
    formal_data, run_root = Path(formal_data), Path(run_root)
    staging = run_root / "client_staging"
    staging.mkdir(parents=True, exist_ok=False)
    for source in _pair_paths(formal_data, LIBRARIES):
        if not source.is_file():
            raise CompleteResourceImportError(f"客户端图库不存在: {source}")
        target = staging / source.name
        shutil.copy2(source, target)
        if _sha256(source) != _sha256(target):
            raise CompleteResourceImportError(f"工作区副本哈希不一致: {source.name}")
    return staging


def deploy_verified_files(
    source_to_target: dict[Path, Path],
    *,
    expected_before: dict[Path, str],
    backup_root: Path,
) -> tuple[Path, dict[str, str]]:
    """Deploy a prepared file group, restoring every target on any failure."""
    if not source_to_target:
        raise CompleteResourceImportError("部署文件为空")
    targets = tuple(source_to_target.values())
    if len(set(targets)) != len(targets):
        raise CompleteResourceImportError("部署目标重复")
    for source, target in source_to_target.items():
        if not source.is_file() or not target.is_file():
            raise CompleteResourceImportError(f"部署源或目标不存在: {source} -> {target}")
        if expected_before.get(target) != _sha256(target):
            raise CompleteResourceImportError(f"预检后目标文件发生变化，停止部署: {target}")

    backup_dir = Path(backup_root) / f"完整武器衣服动作素材_{_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, object] = {"files": []}
    for target in targets:
        backup = backup_dir / f"{len(manifest['files']):02d}_{target.name}"
        shutil.copy2(target, backup)
        manifest["files"].append({"target": str(target), "backup": str(backup), "sha256": _sha256(target)})
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    token = uuid.uuid4().hex
    temps: list[Path] = []
    try:
        for source, target in source_to_target.items():
            temp = target.with_name(f".{target.name}.{token}.tmp")
            shutil.copy2(source, temp)
            if _sha256(source) != _sha256(temp):
                raise CompleteResourceImportError(f"部署临时副本哈希不一致: {target}")
            temps.append(temp)
        for target in targets:
            temp = target.with_name(f".{target.name}.{token}.tmp")
            os.replace(temp, target)
        after = {str(target): _sha256(target) for target in targets}
        for source, target in source_to_target.items():
            if _sha256(source) != after[str(target)]:
                raise CompleteResourceImportError(f"部署回读哈希不一致: {target}")
        return backup_dir, after
    except Exception:
        for entry in manifest["files"]:
            shutil.copy2(Path(entry["backup"]), Path(entry["target"]))
        raise
    finally:
        for temp in temps:
            if temp.exists():
                temp.unlink()


def add_launcher_static_sources(
    source_to_target: dict[Path, Path],
    *,
    staging: Path,
    launcher_patch: Path,
    launcher_staging: Path,
) -> None:
    """Add unique duplicate sources so static pairs reach both destinations."""
    launcher_staging.mkdir(parents=True, exist_ok=False)
    for library in STATIC_LIBRARIES:
        for ext in (".wzl", ".wzx"):
            source = staging / f"{library}{ext}"
            duplicate = launcher_staging / source.name
            shutil.copy2(source, duplicate)
            if _sha256(source) != _sha256(duplicate):
                raise CompleteResourceImportError(f"登录器部署副本哈希不一致: {source.name}")
            source_to_target[duplicate] = launcher_patch / f"{library}{ext}"


def _verify_staging(staging: Path) -> dict[str, int]:
    counts = {library: _read_count(staging / f"{library}.wzx") for library in LIBRARIES}
    expected = {"Items": 7326, "StateItem": 7326, "DnItems": 7326, "Weapon": 170400, "Hum": 80400}
    if counts != expected:
        raise CompleteResourceImportError(f"工作区图库数量不符合固定契约: {counts}")
    return counts


def run(args: argparse.Namespace) -> dict[str, object]:
    source_root = Path(args.source_root)
    formal_data = Path(args.client_data)
    launcher_patch = Path(args.launcher_patch_data)
    resource_map = Path(args.resource_map)
    workspace_root = Path(args.workspace_root)
    backup_root = Path(args.backup_root)
    evidence_root = Path(args.evidence_root)
    run_root = workspace_root / f"完整武器衣服动作素材_{_stamp()}"
    run_root.mkdir(parents=True, exist_ok=False)

    target_paths = list(_pair_paths(formal_data, LIBRARIES))
    target_paths.extend(_pair_paths(launcher_patch, STATIC_LIBRARIES))
    target_paths.append(resource_map)
    if not resource_map.is_file():
        raise CompleteResourceImportError(f"平台资源映射不存在: {resource_map}")
    expected_before = {target: _sha256(target) for target in target_paths}

    # The launcher source must be demonstrably the same baseline before it is
    # allowed to join the deployment.  This prevents guessing a patch root.
    for library in STATIC_LIBRARIES:
        for ext in (".wzl", ".wzx"):
            client = formal_data / f"{library}{ext}"
            patch = launcher_patch / f"{library}{ext}"
            if expected_before[client] != expected_before[patch]:
                raise CompleteResourceImportError(f"登录器补丁源并非当前客户端同一基线: {library}{ext}")

    manifest = build_action_manifest(source_root)
    if len(manifest.weapons) != 104 or len(manifest.clothes) != 55 or len(manifest.static_entries) != 214:
        raise CompleteResourceImportError(
            f"来源清单数量异常: 武器={len(manifest.weapons)} 衣服={len(manifest.clothes)} 静态={len(manifest.static_entries)}"
        )
    staging = stage_client_pairs(formal_data, run_root)
    action_receipt = compile_action_sequences(
        manifest,
        staging / "Weapon.wzl", staging / "Weapon.wzx",
        staging / "Hum.wzl", staging / "Hum.wzx",
        backup_root=run_root / "compile_backups",
    )
    icon_root = run_root / "static_icons"
    static_icons = render_static_icons(manifest, icon_root)
    static_receipt = compile_static_libraries(manifest, icon_root, staging, backup_root=run_root / "compile_backups")
    candidate_map = run_root / "装备资源映射表_候选.csv"
    map_result = write_candidate_resource_map(resource_map, candidate_map, manifest)
    if map_result.retired_count != 60 or map_result.added_count != 214:
        raise CompleteResourceImportError(f"资源映射变更数量异常: 退役={map_result.retired_count} 新增={map_result.added_count}")
    counts = _verify_staging(staging)

    result: dict[str, object] = {
        "run_root": str(run_root),
        "mode": "apply" if args.apply else "stage_only",
        "source_root": str(source_root),
        "manifest": {"weapons": len(manifest.weapons), "clothes": len(manifest.clothes), "static": len(manifest.static_entries)},
        "counts_after_staging": counts,
        "action": {"weapon_shapes": list(action_receipt.weapon.shapes), "hum_shapes": list(action_receipt.hum.shapes)},
        "static": {"count_before": static_receipt.count_before, "count_after": static_receipt.count_after, "icons": len(static_icons)},
        "map": {"retired": map_result.retired_count, "added": map_result.added_count, "candidate": str(candidate_map)},
        "hash_before": {str(path): digest for path, digest in expected_before.items()},
        "backup_dir": "",
        "hash_after": {},
    }
    if args.apply:
        source_to_target: dict[Path, Path] = {}
        for library in LIBRARIES:
            for ext in (".wzl", ".wzx"):
                source_to_target[staging / f"{library}{ext}"] = formal_data / f"{library}{ext}"
        # A dict cannot use one source path for two targets.  Add a second,
        # hash-identical static source set for the launcher patch.
        add_launcher_static_sources(
            source_to_target,
            staging=staging,
            launcher_patch=launcher_patch,
            launcher_staging=run_root / "launcher_static_staging",
        )
        source_to_target[candidate_map] = resource_map
        backup_dir, hashes_after = deploy_verified_files(
            source_to_target, expected_before=expected_before, backup_root=backup_root
        )
        result["backup_dir"] = str(backup_dir)
        result["hash_after"] = hashes_after

    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = evidence_root / f"完整武器衣服动作素材_{_stamp()}.json"
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["evidence"] = str(evidence)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入完整武器衣服静态图与动作帧；默认只构建工作区。")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--client-data", type=Path, required=True)
    parser.add_argument("--launcher-patch-data", type=Path, required=True)
    parser.add_argument("--resource-map", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
