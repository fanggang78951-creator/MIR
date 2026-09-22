# -*- coding: utf-8 -*-
"""Build a read-only-reviewed deployment candidate for stable Looks asset replacement."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

from .equipment_asset_replacement import (
    ReplacementPlanError,
    apply_shape_updates_to_database_copy,
    build_replacement_plan,
    compile_static_replacements,
    render_replacement_icons,
    write_replacement_resource_map,
)
from .import_complete_weapon_clothing import deploy_verified_files


STATIC_LIBRARIES = ("Items", "StateItem", "DnItems")
FRAME_COUNT = 1200


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wzx_count(path: Path) -> int:
    data = Path(path).read_bytes()
    if len(data) < 48 or len(data) != 48 + int.from_bytes(data[44:48], "little") * 4:
        raise ReplacementPlanError(f"WZX 格式不合法: {path}")
    return int.from_bytes(data[44:48], "little")


def _frame_type(wzl: Path, wzx: Path, index: int) -> int:
    offsets = wzx.read_bytes()
    offset = struct.unpack_from("<I", offsets, 48 + index * 4)[0]
    if offset == 0:
        return 0
    return struct.unpack_from("<H", wzl.read_bytes(), offset)[0]


def _verify_action_blocks(client_data: Path, plan) -> None:
    for family, library, assets in (
        ("武器", "Weapon", plan.weapon_replacements),
        ("衣服", "Hum", plan.clothing_replacements),
    ):
        wzl, wzx = client_data / f"{library}.wzl", client_data / f"{library}.wzx"
        offsets = wzx.read_bytes()
        count = _wzx_count(wzx)
        pixels = wzl.read_bytes()
        for asset in assets:
            start = asset.action_shape * FRAME_COUNT
            if start + FRAME_COUNT > count:
                raise ReplacementPlanError(f"{family}动作帧不足: Shape={asset.action_shape}，WZX={count}")
            if not any(
                (offset := struct.unpack_from("<I", offsets, 48 + index * 4)[0]) != 0
                and struct.unpack_from("<H", pixels, offset)[0] == 6
                for index in range(start, start + FRAME_COUNT)
            ):
                raise ReplacementPlanError(f"{family}动作帧全为空或类型不符: Shape={asset.action_shape}")


def stage(
    *,
    source_root: Path,
    client_data: Path,
    database: Path,
    resource_map: Path,
    output_root: Path,
) -> dict[str, object]:
    """Stage every mutable result; never modify client, DB, or formal map."""
    source_root, client_data = Path(source_root), Path(client_data)
    database, resource_map, output_root = Path(database), Path(resource_map), Path(output_root)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = output_root / f"稳定编号武器衣服替换_{stamp}"
    run_root.mkdir(parents=True, exist_ok=False)
    staging_data = run_root / "client_static_staging"
    staging_data.mkdir()
    source_hashes: dict[str, str] = {}
    for library in STATIC_LIBRARIES:
        for ext in (".wzl", ".wzx"):
            source = client_data / f"{library}{ext}"
            if not source.is_file():
                raise ReplacementPlanError(f"客户端静态图库不存在: {source}")
            target = staging_data / source.name
            shutil.copy2(source, target)
            source_hashes[str(source)] = _sha256(source)
            if source_hashes[str(source)] != _sha256(target):
                raise ReplacementPlanError(f"工作区静态图库复制校验失败: {source.name}")
    staging_db = run_root / database.name
    shutil.copy2(database, staging_db)
    source_hashes[str(database)] = _sha256(database)
    if source_hashes[str(database)] != _sha256(staging_db):
        raise ReplacementPlanError("工作区数据库复制校验失败")
    source_hashes[str(resource_map)] = _sha256(resource_map)

    plan = build_replacement_plan(database, source_root)
    _verify_action_blocks(client_data, plan)
    icons = render_replacement_icons(plan, run_root / "static_icons")
    static_receipt = compile_static_replacements(plan, run_root / "static_icons", staging_data, backup_root=run_root / "compile_backups")
    updated_shapes = apply_shape_updates_to_database_copy(staging_db, plan)
    candidate_map = run_root / "装备资源映射表_稳定编号候选.csv"
    map_receipt = write_replacement_resource_map(resource_map, candidate_map, plan)

    expected_count = max(item.looks for item in plan.weapon_replacements + plan.clothing_replacements + plan.tail_additions) + 1
    counts = {library: _wzx_count(staging_data / f"{library}.wzx") for library in STATIC_LIBRARIES}
    if set(counts.values()) != {expected_count}:
        raise ReplacementPlanError(f"工作区静态图库计数不一致: {counts}，期望={expected_count}")
    for library in STATIC_LIBRARIES:
        for asset in plan.weapon_replacements + plan.clothing_replacements + plan.tail_additions:
            if _frame_type(staging_data / f"{library}.wzl", staging_data / f"{library}.wzx", asset.looks) != 6:
                raise ReplacementPlanError(f"工作区静态图回读失败: {library} Looks={asset.looks}")

    staged_hashes = {str(path): _sha256(path) for path in [
        staging_db, candidate_map,
        *(staging_data / f"{library}{ext}" for library in STATIC_LIBRARIES for ext in (".wzl", ".wzx")),
    ]}
    result: dict[str, object] = {
        "mode": "stage_only",
        "run_root": str(run_root),
        "source_hashes": source_hashes,
        "staged_hashes": staged_hashes,
        "static_count_before": static_receipt.count_before,
        "static_count_after": static_receipt.count_after,
        "weapon_replacements": len(plan.weapon_replacements),
        "clothing_replacements": len(plan.clothing_replacements),
        "tail_additions": len(plan.tail_additions),
        "shape_updates": updated_shapes,
        "resource_map_removed_failed_candidates": map_receipt.removed_failed_candidates,
        "resource_map_added_entries": map_receipt.added_entries,
        "shape_updates_detail": [
            {"idx": item.idx, "looks": item.looks, "old_shape": item.old_shape, "new_shape": item.new_shape}
            for item in plan.shape_updates
        ],
    }
    evidence = run_root / "staging_receipt.json"
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["evidence"] = str(evidence)
    return result


def deploy_staged_replacement(
    *,
    run_root: Path,
    client_data: Path,
    launcher_patch_data: Path,
    database: Path,
    resource_map: Path,
    backup_root: Path,
) -> dict[str, object]:
    """Atomically deploy a previously read-back staging candidate after fresh hash checks."""
    run_root, client_data, launcher_patch_data = Path(run_root), Path(client_data), Path(launcher_patch_data)
    database, resource_map, backup_root = Path(database), Path(resource_map), Path(backup_root)
    receipt_path = run_root / "staging_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    source_hashes: dict[str, str] = receipt.get("source_hashes", {})
    staging = run_root / "client_static_staging"
    candidate_map = run_root / "装备资源映射表_稳定编号候选.csv"
    staging_db = run_root / database.name
    targets_expected: dict[Path, str] = {}
    source_to_target: dict[Path, Path] = {}
    for library in STATIC_LIBRARIES:
        for ext in (".wzl", ".wzx"):
            target = client_data / f"{library}{ext}"
            expected = source_hashes.get(str(target))
            if expected is None:
                raise ReplacementPlanError(f"测试收据缺少客户端哈希: {target}")
            targets_expected[target] = expected
            source_to_target[staging / target.name] = target
    for target in (database, resource_map):
        expected = source_hashes.get(str(target))
        if expected is None:
            raise ReplacementPlanError(f"测试收据缺少目标哈希: {target}")
        targets_expected[target] = expected
    source_to_target[staging_db] = database
    source_to_target[candidate_map] = resource_map

    # The launcher patch source can legitimately have a different old version;
    # it is copied from the already-validated client staging files and gets its
    # own fresh preflight hash and rollback entry.
    launcher_stage = run_root / "launcher_static_deployment"
    launcher_stage.mkdir(exist_ok=False)
    for library in STATIC_LIBRARIES:
        for ext in (".wzl", ".wzx"):
            source = staging / f"{library}{ext}"
            duplicate = launcher_stage / source.name
            shutil.copy2(source, duplicate)
            if _sha256(source) != _sha256(duplicate):
                raise ReplacementPlanError(f"登录器部署副本哈希不一致: {source.name}")
            target = launcher_patch_data / source.name
            if not target.is_file():
                raise ReplacementPlanError(f"登录器补丁源不存在: {target}")
            targets_expected[target] = _sha256(target)
            source_to_target[duplicate] = target

    backup_dir, hash_after = deploy_verified_files(
        source_to_target,
        expected_before=targets_expected,
        backup_root=backup_root,
    )
    expected_count = int(receipt["static_count_after"])
    counts = {library: _wzx_count(client_data / f"{library}.wzx") for library in STATIC_LIBRARIES}
    launcher_counts = {library: _wzx_count(launcher_patch_data / f"{library}.wzx") for library in STATIC_LIBRARIES}
    if set(counts.values()) != {expected_count} or set(launcher_counts.values()) != {expected_count}:
        raise ReplacementPlanError(f"部署后静态图库数量异常: client={counts}; launcher={launcher_counts}")
    con = __import__("sqlite3").connect(database)
    try:
        for update in receipt["shape_updates_detail"]:
            row = con.execute("SELECT Looks, Shape FROM StdItems WHERE Idx=?", (update["idx"],)).fetchone()
            if row is None or tuple(map(int, row)) != (update["looks"], update["new_shape"]):
                raise ReplacementPlanError(f"部署后 Shape 回读失败: {update}")
    finally:
        con.close()
    result = {
        "mode": "deployed",
        "run_root": str(run_root),
        "backup_dir": str(backup_dir),
        "hash_after": hash_after,
        "client_counts": counts,
        "launcher_counts": launcher_counts,
        "shape_updates_verified": len(receipt["shape_updates_detail"]),
    }
    (run_root / "deployment_receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建稳定编号武器/衣服替换测试副本，不写正式资源。")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--client-data", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--resource-map", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--deploy-run-root", type=Path)
    parser.add_argument("--launcher-patch-data", type=Path)
    parser.add_argument("--backup-root", type=Path)
    args = parser.parse_args(argv)
    if args.deploy_run_root:
        if args.launcher_patch_data is None or args.backup_root is None:
            parser.error("部署必须提供 --launcher-patch-data 与 --backup-root")
        result = deploy_staged_replacement(
            run_root=args.deploy_run_root,
            client_data=args.client_data,
            launcher_patch_data=args.launcher_patch_data,
            database=args.database,
            resource_map=args.resource_map,
            backup_root=args.backup_root,
        )
    else:
        result = stage(
            source_root=args.source_root,
            client_data=args.client_data,
            database=args.database,
            resource_map=args.resource_map,
            output_root=args.output_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
