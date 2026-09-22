#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract one WZL frame and append it to Items/StateItem/DnItems.

This tool is intentionally limited to static equipment icons. It does not
touch Weapon/cboWeapon/Hum action-frame libraries.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from icon_pipeline import write_png_rgba  # noqa: E402
from append_static_wzl_type6 import append_library, make_backup  # noqa: E402


TOOL_DIR = Path(__file__).resolve().parent
EQUIPMENT_ROOT = TOOL_DIR.parents[2]
DEFAULT_OUTPUT = EQUIPMENT_ROOT / "outputs" / "resources"
DEFAULT_BACKUP_ROOT = EQUIPMENT_ROOT / "backups" / "resources"
DEFAULT_RESOURCE_MAP = EQUIPMENT_ROOT / "profiles" / "装备资源映射表.csv"
LIBS = ("Items", "StateItem", "DnItems")


class StaticIconError(RuntimeError):
    pass


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def read_offsets(wzx_path: Path) -> list[int]:
    data = wzx_path.read_bytes()
    if len(data) < 48:
        raise StaticIconError(f"WZX too small: {wzx_path}")
    declared = struct.unpack_from("<I", data, 44)[0]
    count = (len(data) - 48) // 4
    if declared != count:
        raise StaticIconError(f"WZX declared count {declared} != offset count {count}: {wzx_path}")
    return [struct.unpack_from("<I", data, 48 + i * 4)[0] for i in range(count)]


def read_wzl_header_count(wzl_path: Path) -> int:
    data = wzl_path.read_bytes()
    if len(data) < 48:
        raise StaticIconError(f"WZL too small: {wzl_path}")
    return struct.unpack_from("<I", data, 44)[0]


def inspect_client_static_state(client_data: Path, target_id: int) -> dict[str, object]:
    state: dict[str, object] = {}
    for lib in LIBS:
        wzx_path = client_data / f"{lib}.wzx"
        wzl_path = client_data / f"{lib}.wzl"
        wzx_data = wzx_path.read_bytes()
        if len(wzx_data) < 48:
            raise StaticIconError(f"WZX too small: {wzx_path}")
        wzx_declared = struct.unpack_from("<I", wzx_data, 44)[0]
        wzx_offset_count = (len(wzx_data) - 48) // 4
        wzl_header_count = read_wzl_header_count(wzl_path)
        if wzx_declared != wzx_offset_count:
            raise StaticIconError(f"{lib} WZX declared count {wzx_declared} != offset count {wzx_offset_count}")
        if len(wzx_data) != 48 + wzx_declared * 4:
            raise StaticIconError(f"{lib} WZX length {len(wzx_data)} != 48 + count*4")
        if wzl_header_count != wzx_declared:
            raise StaticIconError(
                f"{lib} WZL header count {wzl_header_count} != WZX declared count {wzx_declared}. "
                "WZL头部count未更新，客户端可能不显示新图标。"
            )
        if wzl_header_count < target_id + 1:
            raise StaticIconError(
                f"{lib} WZL header count {wzl_header_count} < Looks+1 {target_id + 1}. "
                "WZL头部count未更新，客户端可能不显示新图标。"
            )
        offsets = [struct.unpack_from("<I", wzx_data, 48 + i * 4)[0] for i in range(wzx_offset_count)]
        if target_id < 0 or target_id >= len(offsets):
            raise StaticIconError(f"{lib} target id {target_id} out of range after import")
        offset = offsets[target_id]
        if offset <= 0:
            raise StaticIconError(f"{lib} target id {target_id} has empty offset after import")
        wzl_data = wzl_path.read_bytes()
        if offset + 16 > len(wzl_data):
            raise StaticIconError(f"{lib} target id {target_id} offset outside WZL after import")
        frame_type, _zero, width, height, x, y, payload_len, unk = struct.unpack_from("<HHHHhhhh", wzl_data, offset)
        state[lib] = {
            "wzx_declared_count": wzx_declared,
            "wzx_offset_count": wzx_offset_count,
            "wzx_file_length": len(wzx_data),
            "wzx_expected_length": 48 + wzx_declared * 4,
            "wzl_header_count": wzl_header_count,
            "target_offset": offset,
            "frame": {
                "type": frame_type,
                "width": width,
                "height": height,
                "x": x,
                "y": y,
                "payload_len": payload_len,
                "unk": unk,
            },
        }
    return state


def source_pair(source_wzl: Path) -> tuple[Path, Path]:
    if source_wzl.suffix.lower() == ".wzx":
        source_wzx = source_wzl
        source_wzl = source_wzl.with_suffix(".wzl")
    else:
        source_wzx = source_wzl.with_suffix(".wzx")
    if not source_wzl.exists():
        raise StaticIconError(f"Source WZL not found: {source_wzl}")
    if not source_wzx.exists():
        raise StaticIconError(f"Source WZX not found: {source_wzx}")
    return source_wzl, source_wzx


def scale5(value: int) -> int:
    return value * 255 // 31


def decode_rgb555(raw: bytes, width: int, height: int) -> list[tuple[int, int, int, int]]:
    expected = width * height * 2
    if len(raw) != expected:
        raise StaticIconError(f"RGB555 data length {len(raw)} != expected {expected}")
    pixels: list[tuple[int, int, int, int]] = []
    for pos in range(0, len(raw), 2):
        value = struct.unpack_from("<H", raw, pos)[0]
        if value == 0:
            pixels.append((0, 0, 0, 0))
            continue
        r = scale5((value >> 10) & 0x1F)
        g = scale5((value >> 5) & 0x1F)
        b = scale5(value & 0x1F)
        pixels.append((r, g, b, 255))
    return pixels


def decode_type6_bgr(payload: bytes, width: int, height: int) -> list[tuple[int, int, int, int]]:
    expected = width * height * 3
    if len(payload) < expected:
        raise StaticIconError(f"type6 payload length {len(payload)} < expected {expected}")
    pixels: list[tuple[int, int, int, int]] = []
    for pos in range(0, expected, 3):
        b, g, r = payload[pos], payload[pos + 1], payload[pos + 2]
        if r == 0 and g == 0 and b == 0:
            pixels.append((0, 0, 0, 0))
        else:
            pixels.append((r, g, b, 255))
    return pixels


def extract_frame_to_png(source_wzl: Path, source_id: int, output_png: Path) -> dict[str, object]:
    wzl, wzx = source_pair(source_wzl)
    offsets = read_offsets(wzx)
    if source_id < 0 or source_id >= len(offsets):
        raise StaticIconError(f"Source id {source_id} out of range 0-{len(offsets) - 1}: {wzx}")
    offset = offsets[source_id]
    if offset <= 0:
        raise StaticIconError(f"Source id {source_id} is empty in {wzx}")

    data = wzl.read_bytes()
    if offset + 16 > len(data):
        raise StaticIconError(f"Source offset outside WZL: id={source_id}, offset={offset}")
    frame_type, _zero, width, height, x, y, payload_len, _unk = struct.unpack_from("<HHHHhhhh", data, offset)
    if width <= 0 or height <= 0:
        raise StaticIconError(f"Invalid frame size at id {source_id}: {width}x{height}")

    if frame_type == 261:
        compressed = data[offset + 16: offset + 16 + payload_len]
        raw = zlib.decompress(compressed)
        pixels = decode_rgb555(raw, width, height)
        codec = "type261_zlib_rgb555"
    elif frame_type == 6:
        payload = data[offset + 16: offset + 16 + width * height * 3]
        pixels = decode_type6_bgr(payload, width, height)
        codec = "type6_bgr24"
    else:
        raise StaticIconError(f"Unsupported frame type {frame_type} at id {source_id}: {wzl}")

    output_png.parent.mkdir(parents=True, exist_ok=True)
    write_png_rgba(output_png, width, height, pixels)
    return {
        "source_wzl": str(wzl),
        "source_wzx": str(wzx),
        "source_id": source_id,
        "offset": offset,
        "frame_type": frame_type,
        "codec": codec,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "output_png": str(output_png),
    }


def create_blank_png(path: Path) -> None:
    write_png_rgba(path, 1, 1, [(0, 0, 0, 0)])


def sibling_source_libraries(source_wzl: Path) -> dict[str, Path]:
    wzl, _wzx = source_pair(source_wzl)
    folder = wzl.parent
    stem = wzl.stem.lower()
    if stem in ("items", "stateitem", "dnitems"):
        return {
            "Items": folder / "Items.wzl",
            "StateItem": folder / "StateItem.wzl",
            "DnItems": folder / "DnItems.wzl",
        }
    return {lib: wzl for lib in LIBS}


def build_package(
    client_data: Path,
    source_pngs: dict[str, Path],
    extract_info_by_lib: dict[str, object],
    output_dir: Path,
    item_name: str,
) -> tuple[Path, int, dict[str, int]]:
    counts: dict[str, int] = {}
    for lib in LIBS:
        counts[lib] = len(read_offsets(client_data / f"{lib}.wzx"))
    target_id = max(counts.values())
    package_dir = output_dir / "static_icon_package"
    safe_name = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in item_name)
    metadata: dict[str, dict[str, dict[str, int]]] = {}
    for lib in LIBS:
        import_dir = package_dir / f"{lib}_batch_import"
        import_dir.mkdir(parents=True, exist_ok=True)
        metadata[lib] = {}
        for idx in range(counts[lib], target_id):
            placeholder_name = f"{idx:05d}_placeholder.png"
            create_blank_png(import_dir / placeholder_name)
            metadata[lib][placeholder_name] = {"x": 0, "y": 0}
        target_name = f"{target_id:05d}_{safe_name}.png"
        shutil.copy2(source_pngs[lib], import_dir / target_name)
        info = extract_info_by_lib.get(lib, {})
        if isinstance(info, dict):
            metadata[lib][target_name] = {
                "x": int(info.get("x", 0)),
                "y": int(info.get("y", 0)),
            }
        else:
            metadata[lib][target_name] = {"x": 0, "y": 0}
    (package_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return package_dir, target_id, counts


def append_to_client(client_data: Path, package_dir: Path, backup_root: Path, no_backup: bool, dry_run: bool) -> str:
    if dry_run:
        for lib in LIBS:
            append_library(client_data, package_dir, lib, dry_run=True)
        return ""
    backup_dir = ""
    if not no_backup:
        backup_dir = str(make_backup(client_data, backup_root, now_stamp()))
    for lib in LIBS:
        append_library(client_data, package_dir, lib, dry_run=False)
    return backup_dir


def register_resource(resource_map: Path, resource_id: int, slot: str, stdmode: str, shape: str, note: str) -> None:
    resource_map.parent.mkdir(parents=True, exist_ok=True)
    fields = ["资源编号", "部位", "StdMode", "Looks", "Shape", "Items", "DnItems", "StateItem", "Weapon", "Hum", "状态", "备注"]
    rows: list[dict[str, str]] = []
    if resource_map.exists():
        with resource_map.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or fields
            rows = [dict(row) for row in reader]
    for row in rows:
        if row.get("资源编号", "").strip() == str(resource_id) and row.get("部位", "").strip() == slot:
            return
    new_row = {key: "" for key in fields}
    new_row.update({
        "资源编号": str(resource_id),
        "部位": slot,
        "StdMode": stdmode,
        "Looks": str(resource_id),
        "Shape": shape,
        "Items": str(resource_id),
        "DnItems": str(resource_id),
        "StateItem": str(resource_id),
        "状态": "工具自动导入待验证",
        "备注": note,
    })
    rows.append(new_row)
    with resource_map.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, object]:
    base_out_dir = args.output_dir / f"static_icon_from_wzl_{now_stamp()}"
    out_dir = base_out_dir
    suffix = 1
    while out_dir.exists():
        out_dir = base_out_dir.with_name(f"{base_out_dir.name}_{suffix:02d}")
        suffix += 1
    source_libs = sibling_source_libraries(args.source_wzl)
    extract_info_by_lib: dict[str, object] = {}
    source_pngs: dict[str, Path] = {}
    for lib, source_wzl in source_libs.items():
        source_png = out_dir / f"source_{lib}.png"
        extract_info_by_lib[lib] = extract_frame_to_png(source_wzl, args.source_id, source_png)
        source_pngs[lib] = source_png
    package_dir, target_id, counts = build_package(args.client_data, source_pngs, extract_info_by_lib, out_dir, args.name)
    backup_dir = append_to_client(args.client_data, package_dir, args.backup_root, args.no_backup, args.dry_run)
    client_state_after = {} if args.dry_run else inspect_client_static_state(args.client_data, target_id)
    if args.register_resource and not args.dry_run:
        register_resource(
            args.resource_map,
            target_id,
            args.slot,
            args.stdmode or "",
            args.shape or "",
            f"从 {args.source_wzl} 编号 {args.source_id} 自动提取",
        )
    result = {
        "target_id": target_id,
        "counts_before": counts,
        "backup_dir": backup_dir,
        "output_dir": str(out_dir),
        "package_dir": str(package_dir),
        "extract": extract_info_by_lib,
        "client_state_after": client_state_after,
        "dry_run": args.dry_run,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract one WZL frame and append it to static equipment icon libraries.")
    parser.add_argument("--source-wzl", type=Path, required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--slot", default="")
    parser.add_argument("--stdmode", default="")
    parser.add_argument("--shape", default="")
    parser.add_argument("--client-data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--resource-map", type=Path, default=DEFAULT_RESOURCE_MAP)
    parser.add_argument("--register-resource", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)
    result = run(args)
    print(f"LOOKS={result['target_id']}")
    print(f"OUTPUT_DIR={result['output_dir']}")
    if result.get("backup_dir"):
        print(f"BACKUP_DIR={result['backup_dir']}")
    print("DRY_RUN=YES" if result["dry_run"] else "DRY_RUN=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
