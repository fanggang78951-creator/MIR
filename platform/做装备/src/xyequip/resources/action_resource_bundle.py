from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import os
import re
import sys

from PIL import Image


PLATFORM_ROOT = Path(__file__).resolve().parents[4]
WZL_SRC = PLATFORM_ROOT / "wzl编辑" / "src"
if str(WZL_SRC) not in sys.path:
    sys.path.insert(0, str(WZL_SRC))

from wzl_blackbox.transaction import AppendSequenceResult, PngSequenceFrame, append_png_sequence_transaction


FRAME_COUNT = 1200


class ActionResourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionFrame:
    index: int
    png_path: Path
    empty: bool
    x: int
    y: int


@dataclass(frozen=True)
class ActionEntry:
    source_name: str
    source_dir: Path
    shape: int
    frame_count: int
    frames: tuple[ActionFrame, ...]


@dataclass(frozen=True)
class StaticEntry:
    looks: int
    slot: str
    source_name: str
    shape: int


@dataclass(frozen=True)
class ActionManifest:
    weapons: tuple[ActionEntry, ...]
    clothes: tuple[ActionEntry, ...]
    static_entries: tuple[StaticEntry, ...]


@dataclass(frozen=True)
class LibraryCompileReceipt:
    shapes: tuple[int, ...]
    count_before: int
    count_after: int
    transaction: AppendSequenceResult


@dataclass(frozen=True)
class ActionCompileReceipt:
    weapon: LibraryCompileReceipt
    hum: LibraryCompileReceipt


@dataclass(frozen=True)
class StaticIconOutput:
    looks: int
    library: str
    png_path: Path


@dataclass(frozen=True)
class StaticCompileReceipt:
    count_before: int
    count_after: int
    transactions: tuple[AppendSequenceResult, ...]


@dataclass(frozen=True)
class ResourceMapUpdateResult:
    retired_count: int
    added_count: int
    output_path: Path


def _directory_key(path: Path) -> tuple[int, str]:
    match = re.match(r"^(\d+)", path.name)
    if match is None:
        raise ActionResourceError(f"动作目录不以编号开头: {path}")
    return int(match.group(1)), path.name.casefold()


def _placement(path: Path) -> tuple[int, int]:
    values = path.read_text(encoding="utf-8-sig").strip().splitlines()
    if len(values) != 2:
        raise ActionResourceError(f"坐标文件必须正好两行: {path}")
    try:
        x, y = int(values[0].strip()), int(values[1].strip())
    except ValueError as exc:
        raise ActionResourceError(f"坐标文件不是整数: {path}") from exc
    if not (-32768 <= x <= 32767 and -32768 <= y <= 32767):
        raise ActionResourceError(f"坐标超出 WZL short 范围: {path}")
    return x, y


def _read_action_directory(path: Path, shape: int) -> ActionEntry:
    # A directory contains 1,200 frames.  One enumeration avoids doing two
    # filesystem round trips per frame before we read the required placement.
    png_sizes = {
        entry.name: entry.stat().st_size
        for entry in os.scandir(path)
        if entry.is_file() and entry.name.upper().endswith(".PNG")
    }
    frames: list[ActionFrame] = []
    for index in range(FRAME_COUNT):
        png_path = path / f"{index:05d}.PNG"
        size = png_sizes.get(png_path.name)
        if size is None:
            raise ActionResourceError(f"缺少动作帧: {png_path}")
        empty = size == 0
        x = y = 0
        if not empty:
            placement = path / "Placements" / f"{index:05d}.txt"
            if not placement.is_file():
                raise ActionResourceError(f"有效动作帧缺少坐标: {placement}")
            x, y = _placement(placement)
        frames.append(ActionFrame(index, png_path, empty, x, y))
    return ActionEntry(path.name, path, shape, FRAME_COUNT, tuple(frames))


def _discover(path: Path, shape_start: int) -> tuple[ActionEntry, ...]:
    if not path.is_dir():
        raise ActionResourceError(f"动作目录不存在: {path}")
    candidates = sorted((entry for entry in path.iterdir() if entry.is_dir()), key=_directory_key)
    if not candidates:
        raise ActionResourceError(f"动作目录为空: {path}")
    return tuple(_read_action_directory(folder, shape_start + index) for index, folder in enumerate(candidates))


def build_action_manifest(
    source_root: Path,
    *,
    static_start: int = 7112,
    weapon_shape_start: int = 38,
    cloth_shape_start: int = 12,
) -> ActionManifest:
    """Read only the complete source action folders and assign future IDs."""
    source_root = Path(source_root)
    if static_start < 7112:
        raise ActionResourceError("静态编号不得占用保留位 7098-7111")
    weapons = _discover(source_root / "武器-" / "外观", weapon_shape_start)
    clothes = _discover(source_root / "衣服-" / "外观", cloth_shape_start)
    static_entries: list[StaticEntry] = []
    looks = static_start
    for entry in weapons:
        static_entries.append(StaticEntry(looks, "武器", entry.source_name, entry.shape))
        looks += 1
    for entry in clothes:
        static_entries.append(StaticEntry(looks, "男衣服", entry.source_name, entry.shape))
        looks += 1
        static_entries.append(StaticEntry(looks, "女衣服", entry.source_name, entry.shape))
        looks += 1
    return ActionManifest(weapons, clothes, tuple(static_entries))


def _wzx_count(path: Path) -> int:
    data = Path(path).read_bytes()
    if len(data) < 48 or (len(data) - 48) % 4:
        raise ActionResourceError(f"非法 WZX: {path}")
    return int.from_bytes(data[44:48], "little")


def _compile_library(
    entries: tuple[ActionEntry, ...],
    wzl_path: Path,
    wzx_path: Path,
    backup_root: Path,
    label: str,
) -> LibraryCompileReceipt:
    if not entries:
        raise ActionResourceError(f"{label} 没有动作条目")
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    count_before = _wzx_count(wzx_path)
    first_shape = entries[0].shape
    expected_before = first_shape * FRAME_COUNT
    if count_before != expected_before:
        raise ActionResourceError(
            f"{label} 起始 Shape 不匹配: WZX={count_before}, shape={first_shape}, expected={expected_before}"
        )
    expected_shapes = tuple(range(first_shape, first_shape + len(entries)))
    if tuple(entry.shape for entry in entries) != expected_shapes:
        raise ActionResourceError(f"{label} Shape 必须连续")

    sequence = [
        PngSequenceFrame(None if frame.empty else frame.png_path, x=frame.x, y=frame.y)
        for entry in entries
        for frame in entry.frames
    ]
    result = append_png_sequence_transaction(
        wzl_path, wzx_path, sequence, backup_root=Path(backup_root) / f"{label}_backups"
    )
    expected_after = count_before + len(sequence)
    if result.count_after != expected_after or _wzx_count(wzx_path) != expected_after:
        raise ActionResourceError(f"{label} 动作库写后计数不一致")
    return LibraryCompileReceipt(expected_shapes, count_before, expected_after, result)


def compile_action_sequences(
    manifest: ActionManifest,
    weapon_wzl: Path,
    weapon_wzx: Path,
    hum_wzl: Path,
    hum_wzx: Path,
    *,
    backup_root: Path,
) -> ActionCompileReceipt:
    """Compile full action frames into staging WZL/WZX pairs only."""
    backup_root = Path(backup_root)
    weapon = _compile_library(manifest.weapons, weapon_wzl, weapon_wzx, backup_root, "Weapon")
    hum = _compile_library(manifest.clothes, hum_wzl, hum_wzx, backup_root, "Hum")
    return ActionCompileReceipt(weapon, hum)


def _static_source(entry: ActionEntry) -> Image.Image:
    for frame in entry.frames:
        if frame.empty:
            continue
        with Image.open(frame.png_path) as source:
            image = source.convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        if bbox is not None:
            return image.crop(bbox)
    raise ActionResourceError(f"动作没有可见帧，无法生成静态图: {entry.source_dir}")


def _fit_static_icon(source: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    available = (max(1, canvas_size[0] - 4), max(1, canvas_size[1] - 4))
    icon = source.copy()
    icon.thumbnail(available, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    x = (canvas_size[0] - icon.width) // 2
    y = (canvas_size[1] - icon.height) // 2
    canvas.alpha_composite(icon, (x, y))
    return canvas


def render_static_icons(manifest: ActionManifest, output_root: Path) -> tuple[StaticIconOutput, ...]:
    """Render each future Looks icon from the same source action it will use."""
    output_root = Path(output_root)
    by_source = {("武器", entry.source_name): entry for entry in manifest.weapons}
    by_source.update({("衣服", entry.source_name): entry for entry in manifest.clothes})
    source_cache: dict[tuple[str, str], Image.Image] = {}
    canvases = {"Items": (48, 48), "StateItem": (64, 64), "DnItems": (32, 32)}
    outputs: list[StaticIconOutput] = []
    for item in manifest.static_entries:
        family = "武器" if item.slot == "武器" else "衣服"
        key = (family, item.source_name)
        entry = by_source.get(key)
        if entry is None:
            raise ActionResourceError(f"静态图找不到动作来源: {item.slot}/{item.source_name}")
        if key not in source_cache:
            source_cache[key] = _static_source(entry)
        source = source_cache[key]
        for library, size in canvases.items():
            target = output_root / library / f"{item.looks:05d}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            _fit_static_icon(source, size).save(target)
            outputs.append(StaticIconOutput(item.looks, library, target))
    return tuple(outputs)


def compile_static_libraries(
    manifest: ActionManifest,
    icon_root: Path,
    data_dir: Path,
    *,
    backup_root: Path,
) -> StaticCompileReceipt:
    """Append reserved holes and three distinct static icon sequences in staging."""
    if not manifest.static_entries:
        raise ActionResourceError("静态动作清单为空")
    icon_root, data_dir, backup_root = Path(icon_root), Path(data_dir), Path(backup_root)
    static_start = manifest.static_entries[0].looks
    expected_looks = tuple(range(static_start, static_start + len(manifest.static_entries)))
    if tuple(item.looks for item in manifest.static_entries) != expected_looks:
        raise ActionResourceError("静态 Looks 必须连续")
    counts = {library: _wzx_count(data_dir / f"{library}.wzx") for library in ("Items", "StateItem", "DnItems")}
    if len(set(counts.values())) != 1:
        raise ActionResourceError(f"三图库当前数量不一致: {counts}")
    count_before = next(iter(counts.values()))
    if count_before > static_start:
        raise ActionResourceError(f"三图库尾号已越过静态起点: {count_before}>{static_start}")
    transactions: list[AppendSequenceResult] = []
    for library in ("Items", "StateItem", "DnItems"):
        frames = [PngSequenceFrame(None) for _ in range(static_start - count_before)]
        for item in manifest.static_entries:
            png = icon_root / library / f"{item.looks:05d}.png"
            if not png.is_file():
                raise ActionResourceError(f"静态图不存在: {png}")
            frames.append(PngSequenceFrame(png))
        transaction = append_png_sequence_transaction(
            data_dir / f"{library}.wzl",
            data_dir / f"{library}.wzx",
            frames,
            backup_root=backup_root / f"{library}_backups",
        )
        transactions.append(transaction)
    count_after = static_start + len(manifest.static_entries)
    if any(_wzx_count(data_dir / f"{library}.wzx") != count_after for library in ("Items", "StateItem", "DnItems")):
        raise ActionResourceError("三图库写后数量不一致")
    return StaticCompileReceipt(count_before, count_after, tuple(transactions))


def write_candidate_resource_map(
    source_csv: Path,
    output_csv: Path,
    manifest: ActionManifest,
) -> ResourceMapUpdateResult:
    """Create a candidate map, retiring only marked legacy weapon/clothing rows."""
    source_csv, output_csv = Path(source_csv), Path(output_csv)
    with source_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        rows = [dict(row) for row in reader]
    required = {"资源编号", "部位", "StdMode", "Looks", "Shape", "Items", "DnItems", "StateItem", "Weapon", "Hum", "状态", "备注"}
    if not required.issubset(fields):
        raise ActionResourceError(f"资源映射缺少字段: {sorted(required - set(fields))}")
    retired = 0
    legacy_slots = {"武器", "男衣服", "女衣服"}
    for row in rows:
        try:
            resource_id = int(row.get("资源编号", ""))
        except ValueError:
            continue
        note = row.get("备注", "")
        if 6398 <= resource_id <= 7097 and row.get("部位") in legacy_slots and "玄渊二十套全装备700件" in note:
            row["状态"] = "已退役_不可选"
            row["备注"] = f"{note}；20260910完整动作素材替换后退役"
            retired += 1
    existing_ids = {row.get("资源编号", "") for row in rows}
    additions: list[dict[str, str]] = []
    for item in manifest.static_entries:
        resource_id = str(item.looks)
        if resource_id in existing_ids:
            raise ActionResourceError(f"新资源编号已经存在: {resource_id}")
        row = {field: "" for field in fields}
        stdmode = {"武器": "5", "男衣服": "10", "女衣服": "11"}[item.slot]
        row.update({
            "资源编号": resource_id,
            "部位": item.slot,
            "StdMode": stdmode,
            "Looks": resource_id,
            "Shape": str(item.shape),
            "Items": resource_id,
            "DnItems": resource_id,
            "StateItem": resource_id,
            "Weapon": "Weapon.wzl" if item.slot == "武器" else "",
            "Hum": "Hum.wzl" if item.slot != "武器" else "",
            "状态": "candidate_待客户端游戏验收",
            "备注": f"20260910完整动作素材；来源={item.source_name}；静态动作同源",
        })
        additions.append(row)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    token = output_csv.with_name(f".{output_csv.name}.tmp")
    with token.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerows(additions)
    os.replace(token, output_csv)
    return ResourceMapUpdateResult(retired, len(additions), output_csv)
