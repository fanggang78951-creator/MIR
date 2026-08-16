from __future__ import annotations

import argparse
import json
import shutil
import struct
import zlib
from collections import Counter
from datetime import datetime
from pathlib import Path

from stage_execution_shape9_native_knockdown import Pair, sha256, sha256_bytes


BACKUP_ROOT = Path(r"D:\MirServer\Backup")
KNOWN_ORIGINAL = BACKUP_ROOT / "XY_EXEC_SHAPE9_MARKER_INHERIT_20260804_191830" / "before"

EXPECTED_ORIGINAL = {
    "cbohum.wzl": "142EF6CFAFAF60CB10ECE5169960858F3CDA3858E9BF8BCE1A8A8E3687B3E51B",
    "cbohum.wzx": "8D3BC10057F0F8BAC2BB663C38B64CC0895AFA9E293AFFAB27587F8A7D421F16",
}

SHAPE9_START = 18000
SHAPE9_COUNT = 2000
SOURCE_BY_DIRECTION = (12084, 12094, 12104, 12114, 12124, 12134, 12144, 12154)
ACTION_BLOCKS = (
    (0, 80, 10),
    (80, 160, 10),
    (160, 320, 20),
    (320, 400, 10),
    (400, 560, 20),
    (560, 640, 10),
    (640, 800, 20),
    (800, 880, 10),
    (880, 1040, 20),
    (1040, 1200, 20),
    (1200, 1360, 20),
    (1360, 1440, 10),
    (1440, 1600, 20),
    (1600, 1760, 20),
    (1760, 1920, 20),
    (1920, 2000, 10),
)


def load_pair(wzl_path: Path, wzx_path: Path) -> Pair:
    return Pair(wzl_path.read_bytes(), wzx_path.read_bytes())


def direction_for(local_id: int) -> int:
    for start, end, stride in ACTION_BLOCKS:
        if start <= local_id < end:
            return ((local_id - start) // stride) % 8
    raise ValueError(f"cbohum Shape9 local id outside action map: {local_id}")


def inspect_sources(pair: Pair) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for direction, image_id in enumerate(SOURCE_BY_DIRECTION):
        frame = pair.frame(image_id)
        if frame is None or len(frame) < 16:
            raise ValueError(f"native cbohum source frame missing/short: {image_id}")
        frame_type, width, height, x, y, compressed_size = struct.unpack_from("<IHHhhI", frame)
        if frame_type & 0xFFFF != 259 or compressed_size != len(frame) - 16:
            raise ValueError(f"unexpected native cbohum source contract: {image_id}")
        decoded = zlib.decompress(frame[16:])
        stride = (width + 3) // 4 * 4
        if len(decoded) != stride * height:
            raise ValueError(f"native cbohum decoded length mismatch: {image_id}")
        results.append({
            "direction": direction,
            "image_id": image_id,
            "type_low16": frame_type & 0xFFFF,
            "type_high16": frame_type >> 16,
            "width": width,
            "height": height,
            "stride": stride,
            "x": x,
            "y": y,
            "raw_frame_sha256": sha256_bytes(frame),
            "native_frame_valid": True,
        })
    return results


def build_pair(target: Pair) -> tuple[bytes, bytes, dict[str, object]]:
    if target.count < SHAPE9_START + SHAPE9_COUNT:
        raise ValueError("cbohum frame count is too small for Shape9")
    prefix = min(offset for offset in target.offsets if offset > 0)
    output = bytearray(target.wzl[:prefix])
    output_offsets: list[int] = []
    written: dict[tuple[str, int], int] = {}
    replaced = 0
    preserved_inside = 0
    directions: Counter[int] = Counter()

    for image_id in range(target.count):
        original_offset = target.offsets[image_id]
        selected_offset = original_offset
        selected_frame = target.frame(image_id)
        in_shape9 = SHAPE9_START <= image_id < SHAPE9_START + SHAPE9_COUNT
        is_native_character_frame = (
            selected_frame is not None
            and len(selected_frame) >= 4
            and struct.unpack_from("<H", selected_frame, 0)[0] == 259
        )
        if in_shape9 and is_native_character_frame:
            direction = direction_for(image_id - SHAPE9_START)
            source_id = SOURCE_BY_DIRECTION[direction]
            selected_offset = target.offsets[source_id]
            selected_frame = target.frame(source_id)
            key = ("source", selected_offset)
            replaced += 1
            directions[direction] += 1
        else:
            key = ("target", selected_offset)
            if in_shape9:
                preserved_inside += 1

        if selected_frame is None or selected_offset == 0:
            output_offsets.append(0)
            continue
        new_offset = written.get(key)
        if new_offset is None:
            new_offset = len(output)
            output.extend(selected_frame)
            written[key] = new_offset
        output_offsets.append(new_offset)

    struct.pack_into("<I", output, 44, target.count)
    wzx_header = bytearray(target.wzx[:48])
    struct.pack_into("<I", wzx_header, 44, target.count)
    output_wzx = bytes(wzx_header) + struct.pack(f"<{target.count}I", *output_offsets)
    return bytes(output), output_wzx, {
        "shape9_start": SHAPE9_START,
        "shape9_end": SHAPE9_START + SHAPE9_COUNT - 1,
        "native_frames_replaced": replaced,
        "non_character_or_empty_frames_preserved_inside": preserved_inside,
        "direction_replacement_counts": {str(key): value for key, value in sorted(directions.items())},
    }


def validate_output(original: Pair, output: Pair) -> dict[str, object]:
    if output.count != original.count:
        raise RuntimeError("output cbohum frame count changed")
    outside_preserved = 0
    inside_preserved = 0
    replaced = 0
    errors: list[int] = []
    for image_id in range(original.count):
        before = original.frame(image_id)
        after = output.frame(image_id)
        in_shape9 = SHAPE9_START <= image_id < SHAPE9_START + SHAPE9_COUNT
        is_native_character_frame = (
            before is not None and len(before) >= 4 and struct.unpack_from("<H", before, 0)[0] == 259
        )
        if not in_shape9:
            expected = before
            outside_preserved += 1
        elif not is_native_character_frame:
            expected = before
            inside_preserved += 1
        else:
            expected = original.frame(SOURCE_BY_DIRECTION[direction_for(image_id - SHAPE9_START)])
            replaced += 1
        if after != expected:
            errors.append(image_id)
    if errors:
        raise RuntimeError(f"cbohum validation mismatches: {errors[:10]}")
    return {
        "outside_shape9_frames_byte_preserved": outside_preserved,
        "inside_shape9_non_character_frames_byte_preserved": inside_preserved,
        "inside_shape9_native_frames_raw_cloned": replaced,
        "mismatches": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()

    for name, expected_hash in EXPECTED_ORIGINAL.items():
        if sha256(KNOWN_ORIGINAL / name) != expected_hash:
            raise RuntimeError(f"known original cbohum backup drifted: {name}")
    source = load_pair(KNOWN_ORIGINAL / "cbohum.wzl", KNOWN_ORIGINAL / "cbohum.wzx")
    source_report = inspect_sources(source)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = (args.output_root or (BACKUP_ROOT / f"XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_CBOHUM_{stamp}")).resolve()
    prefix = str(BACKUP_ROOT / "XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_CBOHUM_").casefold()
    if not str(root).casefold().startswith(prefix):
        raise ValueError(f"unexpected output root: {root}")
    before = root / "before"
    stage = root / "stage"
    before.mkdir(parents=True, exist_ok=False)
    stage.mkdir(parents=False, exist_ok=False)
    for name in EXPECTED_ORIGINAL:
        shutil.copy2(KNOWN_ORIGINAL / name, before / name)
        if sha256(before / name) != EXPECTED_ORIGINAL[name]:
            raise RuntimeError(f"new cbohum backup hash mismatch: {name}")

    output_wzl, output_wzx, build_report = build_pair(source)
    output_pair = Pair(output_wzl, output_wzx)
    validation = validate_output(source, output_pair)
    outputs = {"cbohum.wzl": output_wzl, "cbohum.wzx": output_wzx}
    for name, data in outputs.items():
        (stage / name).write_bytes(data)
        if sha256(stage / name) != sha256_bytes(data):
            raise RuntimeError(f"cbohum stage write verification failed: {name}")

    report = {
        "schema": "xy-execution-shape9-native-knockdown-cbohum-stage/1",
        "status": "STAGED_STATIC_PASS_NOT_COMMITTED",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root),
        "source_pose": "native cbohum green-heavy-armor knockdown phase4",
        "source_by_direction": list(SOURCE_BY_DIRECTION),
        "source_verification": source_report,
        "before": EXPECTED_ORIGINAL,
        "stage": {name: sha256(stage / name) for name in outputs},
        "build": build_report,
        "validation": validation,
        "target_client_committed": False,
        "normal_hum_candidate_already_deployed": True,
        "platform_updated": False,
        "server_scripts_updated": False,
        "engine_or_m2_operated": False,
    }
    (root / "stage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
