from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zlib
from collections import Counter
from datetime import datetime
from pathlib import Path

from stage_execution_shape9_native_hum import Pair, frame, load_pair, load_pair_bytes


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def native_type_words(raw: bytes) -> tuple[int, int]:
    if len(raw) < 16:
        raise ValueError("short frame")
    return struct.unpack_from("<HH", raw)


def inherit_native_type(source: bytes, target: bytes) -> bytes:
    source_low, _source_high = native_type_words(source)
    target_low, target_high = native_type_words(target)
    if source_low != 259 or target_low != 259:
        raise ValueError(f"type inheritance requires 259/259, got {source_low}/{target_low}")
    result = bytearray(source)
    struct.pack_into("<H", result, 2, target_high)
    width, height = struct.unpack_from("<HH", result, 4)
    decoded = zlib.decompress(result[16:])
    stride = (width + 3) & ~3
    if len(decoded) != stride * height:
        raise ValueError(f"custom payload is not a valid aligned indexed frame: {len(decoded)} != {stride}*{height}")
    return bytes(result)


def merge_pair(target: Pair, source: Pair, start: int) -> tuple[bytes, bytes, dict[str, object]]:
    if start < 0 or start + source.count > target.count:
        raise ValueError("replacement range outside target")
    target_prefix = min(offset for offset in target.offsets if offset > 0)
    output = bytearray(target.wzl[:target_prefix])
    new_offsets: list[int] = []
    written: dict[tuple[str, bytes], int] = {}
    replaced = 0
    preserved_inside = 0
    target_markers: Counter[int] = Counter()

    for image_id in range(target.count):
        target_raw = frame(target, image_id)
        selected: bytes | None = target_raw
        key_kind = "target"
        if start <= image_id < start + source.count and target_raw is not None:
            target_low, target_high = native_type_words(target_raw)
            if target_low == 259:
                source_raw = frame(source, image_id - start)
                if source_raw is None:
                    raise RuntimeError(f"source frame is empty: {image_id - start}")
                selected = inherit_native_type(source_raw, target_raw)
                key_kind = "source-with-native-type"
                replaced += 1
                target_markers[target_high] += 1
            else:
                preserved_inside += 1
        elif start <= image_id < start + source.count:
            preserved_inside += 1

        if selected is None:
            new_offsets.append(0)
            continue
        key = (key_kind, selected)
        new_offset = written.get(key)
        if new_offset is None:
            new_offset = len(output)
            output.extend(selected)
            written[key] = new_offset
        new_offsets.append(new_offset)

    struct.pack_into("<I", output, 44, target.count)
    wzx_header = bytearray(target.wzx[:48])
    struct.pack_into("<I", wzx_header, 44, target.count)
    output_wzx = bytes(wzx_header) + struct.pack(f"<{target.count}I", *new_offsets)
    return bytes(output), output_wzx, {
        "target_count": target.count,
        "source_count": source.count,
        "replacement_start": start,
        "replacement_end": start + source.count - 1,
        "type259_frames_replaced": replaced,
        "non_type259_or_empty_frames_preserved_inside_range": preserved_inside,
        "inherited_high_words": dict(sorted(target_markers.items())),
        "output_wzl_bytes": len(output),
        "output_wzx_bytes": len(output_wzx),
    }


def validate(target: Pair, source: Pair, output_wzl: bytes, output_wzx: bytes, start: int) -> dict[str, object]:
    output = load_pair_bytes(output_wzl, output_wzx)
    if output.count != target.count:
        raise RuntimeError("logical frame count changed")
    replaced = preserved_inside = preserved_outside = 0
    for image_id in range(target.count):
        actual = frame(output, image_id)
        target_raw = frame(target, image_id)
        if start <= image_id < start + source.count and target_raw is not None and native_type_words(target_raw)[0] == 259:
            source_raw = frame(source, image_id - start)
            if source_raw is None:
                raise RuntimeError(f"source frame missing: {image_id}")
            expected = inherit_native_type(source_raw, target_raw)
            if actual != expected:
                raise RuntimeError(f"replacement mismatch: {image_id}")
            if native_type_words(actual) != native_type_words(target_raw):
                raise RuntimeError(f"native type words not inherited: {image_id}")
            replaced += 1
        else:
            if actual != target_raw:
                raise RuntimeError(f"preserved frame changed: {image_id}")
            if start <= image_id < start + source.count:
                preserved_inside += 1
            else:
                preserved_outside += 1
    return {
        "replacements_verified": replaced,
        "inside_range_non_type259_preserved": preserved_inside,
        "outside_range_frames_byte_preserved": preserved_outside,
    }


def main() -> None:
    for name, expected_hash in EXPECTED.items():
        actual = sha256(DATA / name)
        if actual != expected_hash:
            raise RuntimeError(f"source/target hash drifted: {name}: {actual} != {expected_hash}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = BACKUP_ROOT / f"XY_EXEC_SHAPE9_MARKER_INHERIT_{stamp}"
    before = root / "before"
    stage = root / "stage"
    before.mkdir(parents=True, exist_ok=False)
    stage.mkdir(parents=False, exist_ok=False)
    target_names = ("Hum.wzl", "Hum.wzx", "cbohum.wzl", "cbohum.wzx")
    for name in target_names:
        shutil.copy2(DATA / name, before / name)
        if sha256(before / name) != EXPECTED[name]:
            raise RuntimeError(f"backup mismatch: {name}")

    normal_target = load_pair(DATA / "Hum.wzl", DATA / "Hum.wzx")
    normal_source = load_pair(DATA / "XYExecKneel.wzl", DATA / "XYExecKneel.wzx")
    series_target = load_pair(DATA / "cbohum.wzl", DATA / "cbohum.wzx")
    series_source = load_pair(DATA / "XYExecKneelS.wzl", DATA / "XYExecKneelS.wzx")

    normal_wzl, normal_wzx, normal_report = merge_pair(normal_target, normal_source, 5400)
    series_wzl, series_wzx, series_report = merge_pair(series_target, series_source, 18000)
    normal_validation = validate(normal_target, normal_source, normal_wzl, normal_wzx, 5400)
    series_validation = validate(series_target, series_source, series_wzl, series_wzx, 18000)

    outputs = {
        "Hum.wzl": normal_wzl,
        "Hum.wzx": normal_wzx,
        "cbohum.wzl": series_wzl,
        "cbohum.wzx": series_wzx,
    }
    for name, data in outputs.items():
        (stage / name).write_bytes(data)
        if sha256(stage / name) != sha256_bytes(data):
            raise RuntimeError(f"stage write mismatch: {name}")

    report = {
        "schema": "xy-execution-shape9-marker-inherit-stage/1",
        "status": "STAGED_NATIVE_TYPE_INHERIT_PASS_NOT_COMMITTED",
        "root": str(root),
        "before": {name: EXPECTED[name] for name in target_names},
        "sources": {name: EXPECTED[name] for name in EXPECTED if name.startswith("XYExec")},
        "stage": {name: sha256(stage / name) for name in outputs},
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
