from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
from pathlib import Path

from PIL import Image


NORMAL_ACTION_BLOCKS = (
    (0, 192, 8),
    (192, 200, 1),
    (200, 456, 8),
    (456, 472, 2),
    (472, 600, 8),
)

# Read back from the first 2,000 frames of the client's cbohum library.  Every
# segment contains eight direction groups; stride is the number of logical
# frames reserved for each direction in that segment.
SERIES_ACTION_BLOCKS = (
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_encoder(path: Path):
    spec = importlib.util.spec_from_file_location("xy_type259_encoder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load type259 encoder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normal_direction(frame: int) -> int:
    for start, end, stride in NORMAL_ACTION_BLOCKS:
        if start <= frame < end:
            return ((frame - start) // stride) % 8
    raise ValueError(f"normal frame outside 0..599: {frame}")


def series_direction(frame: int) -> int:
    for start, end, stride in SERIES_ACTION_BLOCKS:
        if start <= frame < end:
            return ((frame - start) // stride) % 8
    raise ValueError(f"series frame outside 0..1999: {frame}")


def padded_sprites(sprites: Path, output: Path) -> dict[int, dict[str, object]]:
    metadata = json.loads((sprites / "cells.json").read_text(encoding="utf-8"))
    directions = {int(item["direction"]): dict(item) for item in metadata["directions"]}
    if set(directions) != set(range(8)):
        raise ValueError("eight direction sprites are required")
    padded = output / "padded"
    padded.mkdir(parents=True, exist_ok=False)
    for direction, item in directions.items():
        source = sprites / str(item["file"])
        with Image.open(source) as opened:
            rgba = opened.convert("RGBA")
        width, height = rgba.size
        padded_width = (width + 3) // 4 * 4
        canvas = Image.new("RGBA", (padded_width, height), (0, 0, 0, 0))
        canvas.alpha_composite(rgba, (0, 0))
        target = padded / f"direction_{direction}.png"
        canvas.save(target)
        item["padded_file"] = str(target)
        item["padded_size"] = [padded_width, height]
    return directions


def build_library(
    *,
    name: str,
    frame_count: int,
    direction_for_frame,
    directions: dict[int, dict[str, object]],
    template_wzl: Path,
    template_wzx: Path,
    output: Path,
    encoder,
) -> tuple[Path, Path]:
    wzl_header = bytearray(template_wzl.read_bytes()[:64])
    wzx_header = bytearray(template_wzx.read_bytes()[:48])
    magic = b"www.shandagames.com\x00"
    if not wzl_header.startswith(magic) or not wzx_header.startswith(magic):
        raise ValueError("template library does not have the expected Shanda header")
    struct.pack_into("<I", wzl_header, 44, frame_count)
    struct.pack_into("<I", wzx_header, 44, frame_count)

    output_wzl = output / f"{name}.wzl"
    output_wzx = output / f"{name}.wzx"
    data = bytearray(wzl_header)
    offsets: list[int] = []
    for frame in range(frame_count):
        direction = direction_for_frame(frame)
        item = directions[direction]
        offsets.append(len(data))
        encoded, _, _ = encoder.encode_type259(
            Path(str(item["padded_file"])),
            x=int(item["offset_x"]),
            y=int(item["offset_y"]),
        )
        # LFM2's character renderer expects the second WORD in a native
        # type259 human frame to carry the human-frame marker.  The map-image
        # encoder leaves it at zero, which is accepted by map/UI rendering but
        # produces a transparent/invalid body in the human renderer.  Native
        # Hum/cbohum frames use 163 for normal character frames.
        character_frame = bytearray(encoded)
        struct.pack_into("<H", character_frame, 2, 163)
        data.extend(character_frame)
    output_wzl.write_bytes(data)
    output_wzx.write_bytes(bytes(wzx_header) + struct.pack(f"<{frame_count}I", *offsets))
    return output_wzl, output_wzx


def inspect_library(wzl: Path, wzx: Path, frame_count: int) -> dict[str, object]:
    import sys

    sys.path.insert(0, r"D:\XuanYuanDevPlatform\wzl编辑\src")
    from wzl_blackbox.inspector import inspect_pair

    report = inspect_pair(wzl, wzx)
    if len(report.entries) != frame_count:
        raise RuntimeError(f"{wzl.name}: expected {frame_count} frames, got {len(report.entries)}")
    bad = [entry.image_id for entry in report.entries if entry.frame_type != 259]
    if bad:
        raise RuntimeError(f"{wzl.name}: non-type259 frames: {bad[:10]}")
    unaligned = [entry.image_id for entry in report.entries if entry.width % 4]
    if unaligned:
        raise RuntimeError(f"{wzl.name}: unaligned frame widths: {unaligned[:10]}")
    return {
        "frames": frame_count,
        "frame_type": 259,
        "character_frame_marker": 163,
        "width_alignment": 4,
        "first_offset": report.entries[0].offset,
        "wzl_sha256": sha256(wzl),
        "wzx_sha256": sha256(wzx),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build normal and series LFM2 kneeling character libraries.")
    parser.add_argument("--sprites", type=Path, required=True)
    parser.add_argument("--normal-template-wzl", type=Path, required=True)
    parser.add_argument("--normal-template-wzx", type=Path, required=True)
    parser.add_argument("--series-template-wzl", type=Path, required=True)
    parser.add_argument("--series-template-wzx", type=Path, required=True)
    parser.add_argument("--encoder-script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    encoder = load_encoder(args.encoder_script)
    directions = padded_sprites(args.sprites, args.output)
    normal_wzl, normal_wzx = build_library(
        name="XYExecKneel",
        frame_count=600,
        direction_for_frame=normal_direction,
        directions=directions,
        template_wzl=args.normal_template_wzl,
        template_wzx=args.normal_template_wzx,
        output=args.output,
        encoder=encoder,
    )
    series_wzl, series_wzx = build_library(
        name="XYExecKneelS",
        frame_count=2000,
        direction_for_frame=series_direction,
        directions=directions,
        template_wzl=args.series_template_wzl,
        template_wzx=args.series_template_wzx,
        output=args.output,
        encoder=encoder,
    )
    receipt = {
        "schema": "xy-execution-character-libraries/1",
        "status": "candidate-static-readback-passed",
        "normal_action_blocks": [list(item) for item in NORMAL_ACTION_BLOCKS],
        "series_action_blocks": [list(item) for item in SERIES_ACTION_BLOCKS],
        "normal": inspect_library(normal_wzl, normal_wzx, 600),
        "series": inspect_library(series_wzl, series_wzx, 2000),
        "directions": {
            str(key): {
                "name": item["name"],
                "size": item["padded_size"],
                "offset_x": item["offset_x"],
                "offset_y": item["offset_y"],
            }
            for key, item in directions.items()
        },
    }
    (args.output / "build_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
