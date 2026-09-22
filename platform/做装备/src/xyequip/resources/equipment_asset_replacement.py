# -*- coding: utf-8 -*-
"""Plan stable-Looks replacement of existing Codex weapon and clothing art."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import os
import re
import sqlite3
import sys

from PIL import Image


PLATFORM_ROOT = Path(__file__).resolve().parents[4]
WZL_SRC = PLATFORM_ROOT / "wzl编辑" / "src"
if str(WZL_SRC) not in sys.path:
    sys.path.insert(0, str(WZL_SRC))

from wzl_blackbox.transaction import AppendSequenceResult, PngSequenceFrame, append_png_sequence_transaction


class ReplacementPlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplacementAsset:
    family: str
    looks: int
    source_dir: Path
    source_order: int
    action_shape: int


@dataclass(frozen=True)
class ShapeUpdate:
    idx: int
    looks: int
    old_shape: int
    new_shape: int


@dataclass(frozen=True)
class ReplacementPlan:
    weapon_replacements: tuple[ReplacementAsset, ...]
    clothing_replacements: tuple[ReplacementAsset, ...]
    tail_additions: tuple[ReplacementAsset, ...]
    shape_updates: tuple[ShapeUpdate, ...]
    db_max_looks: int


@dataclass(frozen=True)
class StaticIconOutput:
    looks: int
    library: str
    png_path: Path


@dataclass(frozen=True)
class StaticReplacementReceipt:
    count_before: int
    count_after: int
    transactions: tuple[AppendSequenceResult, ...]


@dataclass(frozen=True)
class ResourceMapReplacementReceipt:
    removed_failed_candidates: int
    added_entries: int
    output_path: Path


def _source_directories(source_root: Path, family: str) -> tuple[Path, ...]:
    root = Path(source_root) / family / "外观"
    if not root.is_dir():
        raise ReplacementPlanError(f"动作素材目录不存在: {root}")
    def key(path: Path) -> tuple[int, str]:
        match = re.match(r"(\d+)", path.name)
        if not match:
            raise ReplacementPlanError(f"动作素材目录必须以数字排序: {path}")
        return int(match.group(1)), path.name
    result = tuple(sorted((path for path in root.iterdir() if path.is_dir()), key=key))
    if not result:
        raise ReplacementPlanError(f"动作素材目录为空: {root}")
    return result


def _database_rows(db_path: Path) -> list[tuple[int, int, int, int]]:
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        return [tuple(map(int, row)) for row in con.execute("SELECT Idx, StdMode, Shape, Looks FROM StdItems")]
    finally:
        con.close()


def build_replacement_plan(
    db_path: Path,
    source_root: Path,
    *,
    weapon_shape_start: int = 38,
    clothing_shape_start: int = 12,
) -> ReplacementPlan:
    """Keep occupied Looks stable and allocate only unused source assets at tail."""
    rows = _database_rows(Path(db_path))
    if not rows:
        raise ReplacementPlanError("StdItems 为空")
    db_max_looks = max(row[3] for row in rows)
    weapons = sorted({looks for _idx, mode, _shape, looks in rows if looks >= 7098 and mode in {5, 68}})
    clothes = sorted({looks for _idx, mode, _shape, looks in rows if looks >= 7098 and mode in {10, 66}})
    overlap = set(weapons) & set(clothes)
    if overlap:
        raise ReplacementPlanError(f"同一Looks混用武器和衣服，必须人工拆分: {sorted(overlap)}")
    weapon_sources = _source_directories(source_root, "武器-")
    clothing_sources = _source_directories(source_root, "衣服-")
    if len(weapons) > len(weapon_sources) or len(clothes) > len(clothing_sources):
        raise ReplacementPlanError("已有装备编号多于同类动作素材，不能保证一对一替换")

    weapon_replacements = tuple(
        ReplacementAsset("武器", looks, weapon_sources[index], index + 1, weapon_shape_start + index)
        for index, looks in enumerate(weapons)
    )
    clothing_replacements = tuple(
        ReplacementAsset("衣服", looks, clothing_sources[index], index + 1, clothing_shape_start + index)
        for index, looks in enumerate(clothes)
    )
    tail: list[ReplacementAsset] = []
    next_looks = db_max_looks + 1
    for index, source in enumerate(weapon_sources[len(weapon_replacements):], start=len(weapon_replacements)):
        tail.append(ReplacementAsset("武器", next_looks, source, index + 1, weapon_shape_start + index))
        next_looks += 1
    for index, source in enumerate(clothing_sources[len(clothing_replacements):], start=len(clothing_replacements)):
        tail.append(ReplacementAsset("衣服", next_looks, source, index + 1, clothing_shape_start + index))
        next_looks += 1

    shape_by_looks = {item.looks: item.action_shape for item in weapon_replacements + clothing_replacements}
    updates = tuple(
        ShapeUpdate(idx, looks, shape, shape_by_looks[looks])
        for idx, _mode, shape, looks in rows
        if shape == 1 and looks in shape_by_looks and shape != shape_by_looks[looks]
    )
    return ReplacementPlan(weapon_replacements, clothing_replacements, tuple(tail), updates, db_max_looks)


def _first_visible_image(asset: ReplacementAsset) -> Image.Image:
    # One directory enumeration is important here: production action folders
    # contain 1,200 frames and the staged replacement has 159 source folders.
    candidates = sorted(
        (Path(entry.path) for entry in os.scandir(asset.source_dir) if entry.is_file() and entry.name.casefold().endswith(".png") and entry.stat().st_size > 0),
        key=lambda path: path.name,
    )
    for png in candidates:
        with Image.open(png) as source:
            image = source.convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        if bbox is not None:
            return image.crop(bbox)
    raise ReplacementPlanError(f"动作素材没有可见帧，无法生成静态图: {asset.source_dir}")


def _fit_icon(source: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    icon = source.copy()
    icon.thumbnail((max(1, canvas_size[0] - 4), max(1, canvas_size[1] - 4)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas.alpha_composite(icon, ((canvas_size[0] - icon.width) // 2, (canvas_size[1] - icon.height) // 2))
    return canvas


def _all_assets(plan: ReplacementPlan) -> tuple[ReplacementAsset, ...]:
    return plan.weapon_replacements + plan.clothing_replacements + plan.tail_additions


def render_replacement_icons(plan: ReplacementPlan, output_root: Path) -> tuple[StaticIconOutput, ...]:
    """Render one distinct static icon per preserved/tail Looks from its own action source."""
    output_root = Path(output_root)
    outputs: list[StaticIconOutput] = []
    canvases = {"Items": (48, 48), "StateItem": (64, 64), "DnItems": (32, 32)}
    for asset in _all_assets(plan):
        source = _first_visible_image(asset)
        for library, canvas_size in canvases.items():
            png = output_root / library / f"{asset.looks:05d}.png"
            png.parent.mkdir(parents=True, exist_ok=True)
            _fit_icon(source, canvas_size).save(png)
            outputs.append(StaticIconOutput(asset.looks, library, png))
    return tuple(outputs)


def _wzx_count(path: Path) -> int:
    data = Path(path).read_bytes()
    if len(data) < 48 or (len(data) - 48) % 4:
        raise ReplacementPlanError(f"WZX 格式不合法: {path}")
    count = int.from_bytes(data[44:48], "little")
    if len(data) != 48 + count * 4:
        raise ReplacementPlanError(f"WZX 计数与偏移表长度不一致: {path}")
    return count


def compile_static_replacements(
    plan: ReplacementPlan,
    icon_root: Path,
    data_dir: Path,
    *,
    backup_root: Path,
) -> StaticReplacementReceipt:
    """Append through required Looks, filling only planned IDs and preserving every other gap."""
    icon_root, data_dir, backup_root = Path(icon_root), Path(data_dir), Path(backup_root)
    assets = _all_assets(plan)
    if not assets:
        raise ReplacementPlanError("替换清单为空")
    by_looks = {asset.looks: asset for asset in assets}
    if len(by_looks) != len(assets):
        raise ReplacementPlanError("替换清单出现重复 Looks")
    final_count = max(by_looks) + 1
    counts = {library: _wzx_count(data_dir / f"{library}.wzx") for library in ("Items", "StateItem", "DnItems")}
    if len(set(counts.values())) != 1:
        raise ReplacementPlanError(f"三套静态图库数量不一致: {counts}")
    count_before = next(iter(counts.values()))
    if count_before > min(by_looks):
        raise ReplacementPlanError(
            f"静态图库已包含需替换编号，不能安全追加覆盖: 当前={count_before}，首个目标={min(by_looks)}"
        )
    transactions: list[AppendSequenceResult] = []
    for library in ("Items", "StateItem", "DnItems"):
        frames: list[PngSequenceFrame] = []
        for looks in range(count_before, final_count):
            asset = by_looks.get(looks)
            if asset is None:
                frames.append(PngSequenceFrame(None))
                continue
            png = icon_root / library / f"{asset.looks:05d}.png"
            if not png.is_file():
                raise ReplacementPlanError(f"缺少已渲染静态图: {png}")
            frames.append(PngSequenceFrame(png))
        transactions.append(
            append_png_sequence_transaction(
                data_dir / f"{library}.wzl",
                data_dir / f"{library}.wzx",
                frames,
                backup_root=backup_root / f"{library}_backups",
            )
        )
    if any(_wzx_count(data_dir / f"{library}.wzx") != final_count for library in ("Items", "StateItem", "DnItems")):
        raise ReplacementPlanError("静态图库写后数量不一致")
    return StaticReplacementReceipt(count_before, final_count, tuple(transactions))


def apply_shape_updates_to_database_copy(database_copy: Path, plan: ReplacementPlan) -> int:
    """Apply only proven Shape=1 action bindings to a writable staging database copy."""
    database_copy = Path(database_copy)
    if not database_copy.is_file():
        raise ReplacementPlanError(f"测试数据库副本不存在: {database_copy}")
    con = sqlite3.connect(database_copy)
    try:
        con.execute("BEGIN IMMEDIATE")
        for update in plan.shape_updates:
            current = con.execute("SELECT Looks, Shape FROM StdItems WHERE Idx=?", (update.idx,)).fetchone()
            if current is None:
                raise ReplacementPlanError(f"预检后的装备记录不存在: Idx={update.idx}")
            if tuple(map(int, current)) != (update.looks, update.old_shape):
                raise ReplacementPlanError(
                    f"预检后的装备 Shape 发生变化: Idx={update.idx}，当前={tuple(current)}，预期={(update.looks, update.old_shape)}"
                )
            con.execute("UPDATE StdItems SET Shape=? WHERE Idx=?", (update.new_shape, update.idx))
        con.commit()
        return len(plan.shape_updates)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def write_replacement_resource_map(
    source_csv: Path,
    output_csv: Path,
    plan: ReplacementPlan,
) -> ResourceMapReplacementReceipt:
    """Replace only the known failed candidate map rows with the stable-Looks mapping."""
    source_csv, output_csv = Path(source_csv), Path(output_csv)
    with source_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        rows = [dict(row) for row in reader]
    required = {"资源编号", "部位", "StdMode", "Looks", "Shape", "Items", "DnItems", "StateItem", "Weapon", "Hum", "状态", "备注"}
    if not required.issubset(fields):
        raise ReplacementPlanError(f"装备资源映射缺少字段: {sorted(required - set(fields))}")
    retained: list[dict[str, str]] = []
    removed = 0
    for row in rows:
        try:
            resource_id = int(row.get("资源编号", ""))
        except ValueError:
            retained.append(row)
            continue
        is_failed_candidate = (
            7112 <= resource_id <= 7325
            and row.get("状态", "").startswith("candidate_")
            and "20260910完整动作素材" in row.get("备注", "")
        )
        if is_failed_candidate:
            removed += 1
        else:
            retained.append(row)
    existing = {row.get("资源编号", "") for row in retained}
    additions: list[dict[str, str]] = []
    for asset in _all_assets(plan):
        resource_id = str(asset.looks)
        if resource_id in existing:
            raise ReplacementPlanError(f"保留映射已占用替换编号，不能安全改写: {resource_id}")
        row = {field: "" for field in fields}
        is_weapon = asset.family == "武器"
        row.update({
            "资源编号": resource_id,
            "部位": "武器" if is_weapon else "衣服",
            "StdMode": "5" if is_weapon else "10",
            "Looks": resource_id,
            "Shape": str(asset.action_shape),
            "Items": resource_id,
            "DnItems": resource_id,
            "StateItem": resource_id,
            "Weapon": "Weapon.wzl" if is_weapon else "",
            "Hum": "Hum.wzl" if not is_weapon else "",
            "状态": "candidate_待客户端游戏验收",
            "备注": f"20260910稳定编号替换；来源={asset.source_dir.name}；{'原编号外观替换' if asset.looks <= plan.db_max_looks else '尾部备用素材'}",
        })
        additions.append(row)
        existing.add(resource_id)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    temp = output_csv.with_name(f".{output_csv.name}.tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(retained)
        writer.writerows(additions)
    os.replace(temp, output_csv)
    return ResourceMapReplacementReceipt(removed, len(additions), output_csv)
