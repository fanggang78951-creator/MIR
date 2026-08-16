from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import zlib
from collections import Counter
from datetime import datetime
from pathlib import Path


DATA = Path(r"D:\11周年\data")
BACKUP_ROOT = Path(r"D:\MirServer\Backup")
KNOWN_ORIGINAL = BACKUP_ROOT / "XY_EXEC_SHAPE9_MARKER_INHERIT_20260804_191830" / "before"
EXPORT_ROOT = Path(r"C:\Users\Administrator\Desktop\新建文件夹 (6)\Hum")
MAGIC = b"www.shandagames.com\x00"

EXPECTED_ORIGINAL = {
    "Hum.wzl": "CBB0C27CF648132D4C4E647981F1ADDB124F5538BE6AF4341A036DBD975DE1BE",
    "Hum.wzx": "AE9653FF8BE0EC8489BD46F5E0B8B28747DC62D387A2659F399D67CE8D2D0605",
}

SHAPE9_START = 5400
SHAPE9_COUNT = 600
SOURCE_BY_DIRECTION = (4139, 4147, 4155, 4163, 4171, 4179, 4187, 4195)
ACTION_BLOCKS = (
    (0, 192, 8),
    (192, 200, 1),
    (200, 456, 8),
    (456, 472, 2),
    (472, 600, 8),
)


class Pair:
    def __init__(self, wzl: bytes, wzx: bytes) -> None:
        if len(wzl) < 48 or len(wzx) < 48 or not wzl.startswith(MAGIC) or not wzx.startswith(MAGIC):
            raise ValueError("invalid Shanda WZL/WZX pair")
        if (len(wzx) - 48) % 4:
            raise ValueError("invalid WZX length")
        self.wzl = wzl
        self.wzx = wzx
        self.count = struct.unpack_from("<I", wzx, 44)[0]
        if struct.unpack_from("<I", wzl, 44)[0] != self.count:
            raise ValueError("WZL/WZX count mismatch")
        if (len(wzx) - 48) // 4 != self.count:
            raise ValueError("WZX offset count mismatch")
        self.offsets = tuple(struct.unpack_from(f"<{self.count}I", wzx, 48))
        positive = sorted(set(offset for offset in self.offsets if offset > 0))
        if not positive or positive[0] < 48:
            raise ValueError("invalid first frame offset")
        ends = {
            start: positive[index + 1] if index + 1 < len(positive) else len(wzl)
            for index, start in enumerate(positive)
        }
        self.frames = {start: wzl[start:ends[start]] for start in positive}

    def frame(self, image_id: int) -> bytes | None:
        offset = self.offsets[image_id]
        return None if offset == 0 else self.frames[offset]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_pair(wzl_path: Path, wzx_path: Path) -> Pair:
    return Pair(wzl_path.read_bytes(), wzx_path.read_bytes())


def direction_for(local_id: int) -> int:
    for start, end, stride in ACTION_BLOCKS:
        if start <= local_id < end:
            return ((local_id - start) // stride) % 8
    raise ValueError(f"shape9 local id outside action map: {local_id}")


def verify_export(pair: Pair, image_id: int) -> dict[str, object]:
    frame = pair.frame(image_id)
    if frame is None or len(frame) < 16:
        raise ValueError(f"source frame missing/short: {image_id}")
    frame_type, width, height, x, y, compressed_size = struct.unpack_from("<IHHhhI", frame)
    if frame_type & 0xFFFF != 259 or compressed_size != len(frame) - 16:
        raise ValueError(f"unexpected source frame contract: {image_id}")
    pixels = zlib.decompress(frame[16:])
    if len(pixels) != width * height:
        raise ValueError(f"source decompressed length mismatch: {image_id}")

    stem = f"{image_id:05d}"
    bmp_path = EXPORT_ROOT / f"{stem}.BMP"
    placement_path = EXPORT_ROOT / "Placements" / f"{stem}.txt"
    bmp = bmp_path.read_bytes()
    if bmp[:2] != b"BM":
        raise ValueError(f"invalid exported BMP: {bmp_path}")
    pixel_offset = struct.unpack_from("<I", bmp, 10)[0]
    bmp_width, bmp_height = struct.unpack_from("<ii", bmp, 18)
    bpp = struct.unpack_from("<H", bmp, 28)[0]
    compression = struct.unpack_from("<I", bmp, 30)[0]
    if bmp_width != width or bmp_height != height or bpp != 8 or compression != 0:
        raise ValueError(f"exported BMP format mismatch: {image_id}")
    stride = ((bmp_width * bpp + 31) // 32) * 4
    exported_pixels = b"".join(
        bmp[pixel_offset + row * stride:pixel_offset + row * stride + bmp_width]
        for row in range(bmp_height)
    )
    if exported_pixels != pixels:
        raise ValueError(f"exported BMP pixels do not match native frame: {image_id}")

    placement_values = [int(value.strip()) for value in placement_path.read_text(encoding="ascii").splitlines() if value.strip()]
    if placement_values != [x, y]:
        raise ValueError(f"exported placement does not match native frame: {image_id}")
    return {
        "image_id": image_id,
        "type_low16": frame_type & 0xFFFF,
        "type_high16": frame_type >> 16,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "raw_frame_sha256": sha256_bytes(frame),
        "export_bmp_sha256": sha256(bmp_path),
        "native_export_exact": True,
    }


def build_pair(target: Pair) -> tuple[bytes, bytes, dict[str, object]]:
    if target.count < SHAPE9_START + SHAPE9_COUNT:
        raise ValueError("Hum frame count is too small for Shape9")
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
        key: tuple[str, int]

        in_shape9 = SHAPE9_START <= image_id < SHAPE9_START + SHAPE9_COUNT
        is_native_character_frame = (
            selected_frame is not None
            and len(selected_frame) >= 4
            and struct.unpack_from("<H", selected_frame, 0)[0] == 259
        )
        if in_shape9 and is_native_character_frame:
            local_id = image_id - SHAPE9_START
            direction = direction_for(local_id)
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
        raise RuntimeError("output frame count changed")
    outside_preserved = 0
    inside_preserved = 0
    replaced = 0
    direction_mismatches: list[int] = []
    for image_id in range(original.count):
        before = original.frame(image_id)
        after = output.frame(image_id)
        in_shape9 = SHAPE9_START <= image_id < SHAPE9_START + SHAPE9_COUNT
        is_native_character_frame = (
            before is not None and len(before) >= 4 and struct.unpack_from("<H", before, 0)[0] == 259
        )
        if not in_shape9:
            if after != before:
                raise RuntimeError(f"outside Shape9 frame changed: {image_id}")
            outside_preserved += 1
        elif not is_native_character_frame:
            if after != before:
                raise RuntimeError(f"Shape9 non-character frame changed: {image_id}")
            inside_preserved += 1
        else:
            expected = original.frame(SOURCE_BY_DIRECTION[direction_for(image_id - SHAPE9_START)])
            if after != expected:
                direction_mismatches.append(image_id)
            replaced += 1
    if direction_mismatches:
        raise RuntimeError(f"direction replacement mismatch: {direction_mismatches[:10]}")
    return {
        "outside_shape9_frames_byte_preserved": outside_preserved,
        "inside_shape9_non_character_frames_byte_preserved": inside_preserved,
        "inside_shape9_native_frames_raw_cloned": replaced,
        "direction_mismatches": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()

    for name, expected_hash in EXPECTED_ORIGINAL.items():
        path = KNOWN_ORIGINAL / name
        if sha256(path) != expected_hash:
            raise RuntimeError(f"known original backup drifted: {path}")
    source = load_pair(KNOWN_ORIGINAL / "Hum.wzl", KNOWN_ORIGINAL / "Hum.wzx")
    export_verification = [verify_export(source, image_id) for image_id in SOURCE_BY_DIRECTION]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = (args.output_root or (BACKUP_ROOT / f"XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_{stamp}")).resolve()
    prefix = str(BACKUP_ROOT / "XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_").casefold()
    if not str(root).casefold().startswith(prefix):
        raise ValueError(f"unexpected output root: {root}")
    before = root / "before"
    stage = root / "stage"
    before.mkdir(parents=True, exist_ok=False)
    stage.mkdir(parents=False, exist_ok=False)

    for name in EXPECTED_ORIGINAL:
        shutil.copy2(KNOWN_ORIGINAL / name, before / name)
        if sha256(before / name) != EXPECTED_ORIGINAL[name]:
            raise RuntimeError(f"new backup hash mismatch: {name}")

    output_wzl, output_wzx, build_report = build_pair(source)
    output_pair = Pair(output_wzl, output_wzx)
    validation = validate_output(source, output_pair)
    outputs = {"Hum.wzl": output_wzl, "Hum.wzx": output_wzx}
    for name, data in outputs.items():
        (stage / name).write_bytes(data)
        if sha256(stage / name) != sha256_bytes(data):
            raise RuntimeError(f"stage write verification failed: {name}")

    report = {
        "schema": "xy-execution-shape9-native-knockdown-stage/1",
        "status": "STAGED_STATIC_PASS_NOT_COMMITTED",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root),
        "source_pose": "native Hum heavy-armor knockdown final frame",
        "source_by_direction": list(SOURCE_BY_DIRECTION),
        "export_verification": export_verification,
        "before": EXPECTED_ORIGINAL,
        "stage": {name: sha256(stage / name) for name in outputs},
        "build": build_report,
        "validation": validation,
        "target_client_committed": False,
        "platform_updated": False,
        "server_scripts_updated": False,
        "engine_or_m2_operated": False,
    }
    (root / "stage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
