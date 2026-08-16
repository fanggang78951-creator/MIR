from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DATA = Path(r"D:\11周年\data")
BACKUP_ROOT = Path(r"D:\MirServer\Backup")
MAGIC = b"www.shandagames.com\x00"

EXPECTED = {
    "Hum.wzl": "CBB0C27CF648132D4C4E647981F1ADDB124F5538BE6AF4341A036DBD975DE1BE",
    "Hum.wzx": "AE9653FF8BE0EC8489BD46F5E0B8B28747DC62D387A2659F399D67CE8D2D0605",
    "cbohum.wzl": "142EF6CFAFAF60CB10ECE5169960858F3CDA3858E9BF8BCE1A8A8E3687B3E51B",
    "cbohum.wzx": "8D3BC10057F0F8BAC2BB663C38B64CC0895AFA9E293AFFAB27587F8A7D421F16",
    "XYExecKneel.wzl": "8ED41829D87D9B07FC8301B3126F506146244CABA36108DDAEB1041555FA18EF",
    "XYExecKneel.wzx": "AE5F623A5DB69A45D9F998A7F43E260697C04D6506BF6BC1A2456698556C4118",
    "XYExecKneelS.wzl": "A43BCE5348365F5414B187ABA63C64522E25CC9F9B7F281CD5548878E4BF7AFC",
    "XYExecKneelS.wzx": "FB25FDA46A68F7FA2725DF5D34E19412CB5514533E4349CB5DF895AC389603B0",
}


@dataclass(frozen=True)
class Pair:
    wzl: bytes
    wzx: bytes
    count: int
    offsets: tuple[int, ...]
    frames: dict[int, bytes]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_pair(wzl_path: Path, wzx_path: Path) -> Pair:
    wzl = wzl_path.read_bytes()
    wzx = wzx_path.read_bytes()
    if len(wzl) < 48 or len(wzx) < 48 or not wzl.startswith(MAGIC) or not wzx.startswith(MAGIC):
        raise ValueError(f"invalid Shanda pair: {wzl_path.name}/{wzx_path.name}")
    if (len(wzx) - 48) % 4:
        raise ValueError(f"invalid WZX length: {wzx_path}")
    count = struct.unpack_from("<I", wzx, 44)[0]
    if struct.unpack_from("<I", wzl, 44)[0] != count or (len(wzx) - 48) // 4 != count:
        raise ValueError(f"count mismatch: {wzl_path.name}")
    offsets = tuple(struct.unpack_from(f"<{count}I", wzx, 48))
    positive = sorted(set(offset for offset in offsets if offset > 0))
    if not positive or positive[0] < 48:
        raise ValueError(f"unexpected first frame offset: {wzl_path.name} {positive[:1]}")
    ends = {
        start: positive[index + 1] if index + 1 < len(positive) else len(wzl)
        for index, start in enumerate(positive)
    }
    frames: dict[int, bytes] = {}
    for start in positive:
        end = ends[start]
        if start + 16 > end or end > len(wzl):
            raise ValueError(f"invalid frame bounds: {wzl_path.name} {start}-{end}")
        frames[start] = wzl[start:end]
    return Pair(wzl, wzx, count, offsets, frames)


def frame(pair: Pair, image_id: int) -> bytes | None:
    offset = pair.offsets[image_id]
    return None if offset == 0 else pair.frames[offset]


def merge_pair(target: Pair, source: Pair, start: int, expected_source_count: int) -> tuple[bytes, bytes, dict[str, object]]:
    if source.count != expected_source_count:
        raise ValueError(f"source frame count mismatch: {source.count} != {expected_source_count}")
    if start < 0 or start + source.count > target.count:
        raise ValueError("replacement range outside target")

    target_prefix = min(offset for offset in target.offsets if offset > 0)
    output = bytearray(target.wzl[:target_prefix])
    new_offsets: list[int] = []
    written: dict[tuple[str, int], int] = {}
    for image_id in range(target.count):
        in_replacement = start <= image_id < start + source.count
        selected = source if in_replacement else target
        selected_id = image_id - start if in_replacement else image_id
        old_offset = selected.offsets[selected_id]
        if old_offset == 0:
            new_offsets.append(0)
            continue
        key = ("source" if in_replacement else "target", old_offset)
        new_offset = written.get(key)
        if new_offset is None:
            new_offset = len(output)
            output.extend(selected.frames[old_offset])
            written[key] = new_offset
        new_offsets.append(new_offset)

    struct.pack_into("<I", output, 44, target.count)
    wzx_header = bytearray(target.wzx[:48])
    struct.pack_into("<I", wzx_header, 44, target.count)
    output_wzx = bytes(wzx_header) + struct.pack(f"<{target.count}I", *new_offsets)
    report = {
        "target_count": target.count,
        "source_count": source.count,
        "replacement_start": start,
        "replacement_end": start + source.count - 1,
        "output_wzl_bytes": len(output),
        "output_wzx_bytes": len(output_wzx),
    }
    return bytes(output), output_wzx, report


def validate_merge(
    target: Pair,
    source: Pair,
    output_wzl: bytes,
    output_wzx: bytes,
    start: int,
) -> dict[str, object]:
    temp_pair = load_pair_bytes(output_wzl, output_wzx)
    if temp_pair.count != target.count:
        raise RuntimeError("output count changed")
    changed = 0
    preserved = 0
    type_counts: dict[int, int] = {}
    marker_counts: dict[int, int] = {}
    for image_id in range(target.count):
        actual = frame(temp_pair, image_id)
        if start <= image_id < start + source.count:
            expected = frame(source, image_id - start)
            changed += 1
            if actual != expected:
                raise RuntimeError(f"replacement frame mismatch: {image_id}")
            if actual is None or len(actual) < 16:
                raise RuntimeError(f"replacement frame empty/short: {image_id}")
            frame_type, marker = struct.unpack_from("<HH", actual)
            type_counts[frame_type] = type_counts.get(frame_type, 0) + 1
            marker_counts[marker] = marker_counts.get(marker, 0) + 1
        else:
            expected = frame(target, image_id)
            preserved += 1
            if actual != expected:
                raise RuntimeError(f"outside frame changed: {image_id}")
    if set(type_counts) != {259} or set(marker_counts) != {163}:
        raise RuntimeError(f"replacement character contract mismatch: type={type_counts}, marker={marker_counts}")
    return {
        "replacement_frames_verified": changed,
        "outside_frames_byte_preserved": preserved,
        "replacement_frame_types": type_counts,
        "replacement_markers": marker_counts,
        "output_positive_offsets": len({offset for offset in temp_pair.offsets if offset > 0}),
    }


def load_pair_bytes(wzl: bytes, wzx: bytes) -> Pair:
    if len(wzl) < 48 or len(wzx) < 48 or not wzl.startswith(MAGIC) or not wzx.startswith(MAGIC):
        raise ValueError("invalid staged pair")
    if (len(wzx) - 48) % 4:
        raise ValueError("invalid staged WZX length")
    count = struct.unpack_from("<I", wzx, 44)[0]
    if struct.unpack_from("<I", wzl, 44)[0] != count or (len(wzx) - 48) // 4 != count:
        raise ValueError("staged count mismatch")
    offsets = tuple(struct.unpack_from(f"<{count}I", wzx, 48))
    positive = sorted(set(offset for offset in offsets if offset > 0))
    if not positive or positive[0] < 48:
        raise ValueError("staged first offset mismatch")
    ends = {
        start: positive[index + 1] if index + 1 < len(positive) else len(wzl)
        for index, start in enumerate(positive)
    }
    frames = {start: wzl[start:ends[start]] for start in positive}
    return Pair(wzl, wzx, count, offsets, frames)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse-root", type=Path)
    args = parser.parse_args()
    for name, expected in EXPECTED.items():
        actual = sha256(DATA / name)
        if actual != expected:
            raise ValueError(f"source/target drifted: {name} {actual}")

    if args.reuse_root is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = BACKUP_ROOT / f"XY_EXEC_SHAPE9_NATIVE_HUM_{stamp}"
    else:
        root = args.reuse_root.resolve()
        expected_prefix = str(BACKUP_ROOT / "XY_EXEC_SHAPE9_NATIVE_HUM_").casefold()
        if not str(root).casefold().startswith(expected_prefix):
            raise ValueError(f"unexpected reuse root: {root}")
    before_dir = root / "before"
    stage_dir = root / "stage"
    if args.reuse_root is None:
        before_dir.mkdir(parents=True, exist_ok=False)
        stage_dir.mkdir(parents=False, exist_ok=False)
    else:
        if not before_dir.is_dir() or not stage_dir.is_dir() or (root / "stage_report.json").exists():
            raise ValueError(f"reuse root is not an uncommitted failed-stage directory: {root}")

    target_names = ("Hum.wzl", "Hum.wzx", "cbohum.wzl", "cbohum.wzx")
    for name in target_names:
        if args.reuse_root is None:
            shutil.copy2(DATA / name, before_dir / name)
        if sha256(before_dir / name) != EXPECTED[name]:
            raise RuntimeError(f"backup hash mismatch: {name}")

    normal_target = load_pair(DATA / "Hum.wzl", DATA / "Hum.wzx")
    normal_source = load_pair(DATA / "XYExecKneel.wzl", DATA / "XYExecKneel.wzx")
    series_target = load_pair(DATA / "cbohum.wzl", DATA / "cbohum.wzx")
    series_source = load_pair(DATA / "XYExecKneelS.wzl", DATA / "XYExecKneelS.wzx")

    normal_wzl, normal_wzx, normal_report = merge_pair(normal_target, normal_source, 5400, 600)
    series_wzl, series_wzx, series_report = merge_pair(series_target, series_source, 18000, 2000)
    normal_validation = validate_merge(normal_target, normal_source, normal_wzl, normal_wzx, 5400)
    series_validation = validate_merge(series_target, series_source, series_wzl, series_wzx, 18000)

    outputs = {
        "Hum.wzl": normal_wzl,
        "Hum.wzx": normal_wzx,
        "cbohum.wzl": series_wzl,
        "cbohum.wzx": series_wzx,
    }
    for name, data in outputs.items():
        (stage_dir / name).write_bytes(data)
        if sha256(stage_dir / name) != sha256_bytes(data):
            raise RuntimeError(f"stage write hash mismatch: {name}")

    report = {
        "schema": "xy-execution-shape9-native-hum-stage/1",
        "status": "STAGED_STATIC_PASS_NOT_COMMITTED",
        "root": str(root),
        "before": {name: EXPECTED[name] for name in target_names},
        "sources": {
            name: EXPECTED[name]
            for name in ("XYExecKneel.wzl", "XYExecKneel.wzx", "XYExecKneelS.wzl", "XYExecKneelS.wzx")
        },
        "stage": {name: sha256(stage_dir / name) for name in outputs},
        "normal": {**normal_report, **normal_validation},
        "series": {**series_report, **series_validation},
        "platform_updated": False,
        "server_scripts_updated": False,
        "engine_or_m2_operated": False,
    }
    (root / "stage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
