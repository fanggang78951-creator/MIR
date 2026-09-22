#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Raw-clone one static item frame across selected client libraries.

This intentionally does not decode WZL pixels. If the client can display the
source frame, the cloned frame remains byte-identical and should display too.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import struct
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parent
EQUIPMENT_ROOT = TOOL_DIR.parents[2]
DEFAULT_OUTPUT = EQUIPMENT_ROOT / "outputs" / "resources"
DEFAULT_BACKUP_ROOT = EQUIPMENT_ROOT / "backups" / "resources"
DEFAULT_RESOURCE_MAP = EQUIPMENT_ROOT / "profiles" / "装备资源映射表.csv"
LIBS = ("Items", "StateItem", "DnItems")


class RawCloneError(RuntimeError):
    pass


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_name(name: str) -> str:
    return "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in name)


def read_offsets(wzx_path: Path) -> list[int]:
    data = wzx_path.read_bytes()
    if len(data) < 48:
        raise RawCloneError(f"WZX too small: {wzx_path}")
    declared = struct.unpack_from("<I", data, 44)[0]
    if (len(data) - 48) % 4:
        raise RawCloneError(f"WZX offset table length is not divisible by 4: {wzx_path}")
    count = (len(data) - 48) // 4
    if len(data) != 48 + count * 4:
        raise RawCloneError(f"WZX length {len(data)} != 48 + count*4: {wzx_path}")
    return [struct.unpack_from("<I", data, 48 + i * 4)[0] for i in range(count)]


def read_wzl_header_count(wzl_path: Path) -> int:
    data = wzl_path.read_bytes()
    if len(data) < 48:
        raise RawCloneError(f"WZL too small: {wzl_path}")
    return struct.unpack_from("<I", data, 44)[0]


def write_header_count(path: Path, count: int) -> None:
    data = bytearray(path.read_bytes())
    if len(data) < 48:
        raise RawCloneError(f"file too small: {path}")
    struct.pack_into("<I", data, 44, count)
    path.write_bytes(data)


def frame_bounds(offsets: list[int], image_id: int, file_size: int) -> tuple[int, int]:
    if image_id < 0 or image_id >= len(offsets):
        raise RawCloneError(f"source id {image_id} out of range 0-{len(offsets) - 1}")
    start = offsets[image_id]
    if start <= 0:
        raise RawCloneError(f"source id {image_id} has empty offset")
    candidates = [off for off in offsets[image_id + 1 :] if off > start]
    end = candidates[0] if candidates else file_size
    if start + 16 > end or end > file_size:
        raise RawCloneError(f"invalid frame bounds: start={start}, end={end}, size={file_size}")
    return start, end


def parse_frame_header(frame: bytes) -> dict[str, int | str]:
    if len(frame) < 16:
        raise RawCloneError("frame too small")
    frame_type, zero, width, height, x, y, payload_len, unk = struct.unpack_from("<HHHHhhhh", frame, 0)
    return {
        "type": frame_type,
        "zero": zero,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "payload_len": payload_len,
        "unk": unk,
        "length": len(frame),
        "sha256": hashlib.sha256(frame).hexdigest(),
    }


def inspect_library(client_data: Path, lib: str, image_id: int) -> tuple[dict[str, object], bytes]:
    wzx_path = client_data / f"{lib}.wzx"
    wzl_path = client_data / f"{lib}.wzl"
    if not wzx_path.exists() or not wzl_path.exists():
        raise RawCloneError(f"missing library files: {wzl_path} / {wzx_path}")
    offsets = read_offsets(wzx_path)
    wzl_header_count = read_wzl_header_count(wzl_path)
    wzx_data = wzx_path.read_bytes()
    wzx_declared_count = struct.unpack_from("<I", wzx_data, 44)[0]
    data = wzl_path.read_bytes()
    start, end = frame_bounds(offsets, image_id, len(data))
    frame = data[start:end]
    info = {
        "lib": lib,
        "wzx": str(wzx_path),
        "wzl": str(wzl_path),
        "count": len(offsets),
        "wzx_declared_count": wzx_declared_count,
        "wzl_header_count": wzl_header_count,
        "source_id": image_id,
        "source_offset": start,
        "source_end": end,
        "frame": parse_frame_header(frame),
    }
    return info, frame


def inspect_target(client_data: Path, lib: str, target_id: int) -> dict[str, object]:
    info, _frame = inspect_library(client_data, lib, target_id)
    return info


def selected_libraries(args: argparse.Namespace) -> tuple[str, ...]:
    requested = getattr(args, "libraries", None)
    libraries = tuple(requested) if requested else LIBS
    if not libraries:
        raise RawCloneError("at least one client library is required")
    if len(set(libraries)) != len(libraries):
        raise RawCloneError(f"duplicate client libraries: {libraries}")
    unknown = [lib for lib in libraries if lib not in LIBS]
    if unknown:
        raise RawCloneError(f"unsupported client libraries: {unknown}")
    return libraries


def make_backup(client_data: Path, backup_root: Path, libraries: tuple[str, ...] = LIBS) -> Path:
    backup_dir = backup_root / f"XuanYuan_WZL_RawClone_{now_stamp()}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = backup_dir.with_name(f"{backup_dir.name}_{suffix:02d}")
        suffix += 1
    backup_dir.mkdir(parents=True, exist_ok=False)
    for lib in libraries:
        for ext in (".wzl", ".wzx"):
            src = client_data / f"{lib}{ext}"
            if src.exists():
                shutil.copy2(src, backup_dir / src.name)
    return backup_dir


def restore_backup(client_data: Path, backup_dir: Path, libraries: tuple[str, ...] = LIBS) -> None:
    for lib in libraries:
        for ext in (".wzl", ".wzx"):
            backup = backup_dir / f"{lib}{ext}"
            if backup.exists():
                shutil.copy2(backup, client_data / backup.name)


def append_raw_frame(client_data: Path, lib: str, target_id: int, frame: bytes) -> int:
    wzx_path = client_data / f"{lib}.wzx"
    wzl_path = client_data / f"{lib}.wzl"
    offsets = read_offsets(wzx_path)
    if target_id < len(offsets):
        raise RawCloneError(f"{lib} target id {target_id} is below current physical slot count {len(offsets)}")
    if target_id > len(offsets):
        with wzx_path.open("ab") as f:
            for _index in range(len(offsets), target_id):
                f.write(struct.pack("<I", 0))
    target_offset = wzl_path.stat().st_size
    with wzl_path.open("ab") as f:
        f.write(frame)
    with wzx_path.open("ab") as f:
        f.write(struct.pack("<I", target_offset))
    new_count = target_id + 1
    write_header_count(wzx_path, new_count)
    write_header_count(wzl_path, new_count)
    return target_offset


def register_resource(
    resource_map: Path,
    resource_id: int,
    slot: str,
    stdmode: str,
    shape: str,
    note: str,
    libraries: tuple[str, ...] = LIBS,
) -> None:
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
        "状态": "raw_clone自动导入待验证",
        "备注": note,
    })
    for library in libraries:
        new_row[library] = str(resource_id)
    rows.append(new_row)
    with resource_map.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, object]:
    libraries = selected_libraries(args)
    out_dir = args.output_dir / f"raw_clone_wzl_{now_stamp()}"
    suffix = 1
    while out_dir.exists():
        out_dir = out_dir.with_name(f"{out_dir.name}_{suffix:02d}")
        suffix += 1
    out_dir.mkdir(parents=True, exist_ok=True)

    sources: dict[str, dict[str, object]] = {}
    frames: dict[str, bytes] = {}
    counts = []
    for lib in libraries:
        info, frame = inspect_library(args.client_data, lib, args.source_id)
        sources[lib] = info
        frames[lib] = frame
        counts.append(int(info["count"]))
    target_id = max(counts)

    backup_dir = ""
    append_offsets: dict[str, int] = {}
    client_state_after: dict[str, object] = {}
    verify: dict[str, object] = {}
    if not args.dry_run:
        backup_path = make_backup(args.client_data, args.backup_root, libraries)
        backup_dir = str(backup_path)
        try:
            for lib in libraries:
                append_offsets[lib] = append_raw_frame(args.client_data, lib, target_id, frames[lib])
            for lib in libraries:
                after = inspect_target(args.client_data, lib, target_id)
                client_state_after[lib] = after
                source_sha = str(sources[lib]["frame"]["sha256"])  # type: ignore[index]
                target_sha = str(after["frame"]["sha256"])  # type: ignore[index]
                if source_sha != target_sha:
                    raise RawCloneError(f"{lib} cloned frame sha mismatch: {source_sha} != {target_sha}")
                if int(after["count"]) != target_id + 1:
                    raise RawCloneError(f"{lib} count after clone mismatch")
                verify[lib] = {
                    "source_sha256": source_sha,
                    "target_sha256": target_sha,
                    "byte_identical": True,
                    "target_offset": append_offsets[lib],
                }
            if args.register_resource:
                register_resource(
                    args.resource_map,
                    target_id,
                    args.slot,
                    args.stdmode or "",
                    args.shape or "",
                    f"raw clone from client static libraries source id {args.source_id}",
                    libraries,
                )
        except Exception:
            restore_backup(args.client_data, backup_path, libraries)
            raise

    result = {
        "mode": "raw_clone",
        "target_id": target_id,
        "source_id": args.source_id,
        "libraries": list(libraries),
        "counts_before": dict(zip(libraries, counts)),
        "backup_dir": backup_dir,
        "output_dir": str(out_dir),
        "sources": sources,
        "append_offsets": append_offsets,
        "client_state_after": client_state_after,
        "verify": verify,
        "dry_run": args.dry_run,
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Raw-clone one WZL frame across selected client libraries.")
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--name", default="raw_clone_item")
    parser.add_argument("--client-data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--register-resource", action="store_true")
    parser.add_argument("--resource-map", type=Path, default=DEFAULT_RESOURCE_MAP)
    parser.add_argument("--slot", default="")
    parser.add_argument("--stdmode", default="")
    parser.add_argument("--shape", default="")
    parser.add_argument("--libraries", nargs="+", choices=LIBS, default=list(LIBS))
    args = parser.parse_args(argv)
    result = run(args)
    print(f"LOOKS={result['target_id']}")
    print(f"OUTPUT_DIR={result['output_dir']}")
    print(f"BACKUP_DIR={result['backup_dir']}")
    print(f"DRY_RUN={'YES' if result['dry_run'] else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
