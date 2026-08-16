from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


SOURCE = Path(
    r"D:\XuanYuanDevPlatform\玄渊界面施工台\workspace"
    r"\star-xx371-382-pak-export-20260812\exports\mmap10\00143.bmp"
)
PALETTE_TEMPLATE = Path(
    r"D:\codex交班记录\备份\20260812_191842_XX371原生雷达9901门禁"
    r"\301.mmap.before"
)
OUTPUT = Path(
    r"D:\XuanYuanDevPlatform\玄渊界面施工台\workspace"
    r"\star-xx371-native-minimap-fixed-palette-20260812"
)
REPORT = Path(
    r"D:\XuanYuanDevPlatform\玄渊界面施工台\reports"
    r"\star-xx371-fixed-palette-candidates-20260812.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_mmap(image: Image.Image, target: Path) -> None:
    if image.mode != "P":
        raise ValueError("MMAP candidate must be indexed colour")
    width, height = image.size
    palette = (image.getpalette() or [])[:768]
    palette.extend([0] * (768 - len(palette)))
    rgb_quads = bytearray()
    for offset in range(0, 768, 3):
        red, green, blue = palette[offset : offset + 3]
        rgb_quads.extend((blue, green, red, 0))

    rows = image.tobytes()
    stride = (width + 3) & ~3
    pixels = bytearray()
    padding = b"\x00" * (stride - width)
    for row in range(height - 1, -1, -1):
        start = row * width
        pixels.extend(rows[start : start + width])
        pixels.extend(padding)

    pixel_offset = 14 + 40 + 1024
    image_size = len(pixels) + 2
    file_size = pixel_offset + image_size
    data = bytearray(struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset))
    data.extend(
        struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            height,
            1,
            8,
            0,
            image_size,
            2834,
            2834,
            0,
            0,
        )
    )
    data.extend(rgb_quads)
    data.extend(pixels)
    data.extend(b"\x00\x00")
    target.write_bytes(data)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as opened:
        source = opened.convert("RGB")
    with Image.open(PALETTE_TEMPLATE) as opened:
        palette_template = opened.convert("P")

    results: list[dict[str, object]] = []
    variants = [
        ("fixed-palette-no-dither", source, Image.Dither.NONE),
        ("fixed-palette-floyd-steinberg", source, Image.Dither.FLOYDSTEINBERG),
    ]

    target_size = (500, 300)
    scale = min(target_size[0] / source.width, target_size[1] / source.height)
    fitted_size = (
        max(1, round(source.width * scale)),
        max(1, round(source.height * scale)),
    )
    fitted = source.resize(fitted_size, Image.Resampling.LANCZOS)
    fitted_canvas = Image.new("RGB", target_size, (0, 0, 0))
    fitted_canvas.paste(
        fitted,
        ((target_size[0] - fitted.width) // 2, (target_size[1] - fitted.height) // 2),
    )
    variants.append(("fixed-palette-500x300-fit", fitted_canvas, Image.Dither.NONE))

    for name, prepared, dither in variants:
        indexed = prepared.quantize(palette=palette_template, dither=dither)
        mmap_path = OUTPUT / f"{name}.mmap"
        preview_path = OUTPUT / f"{name}.png"
        write_mmap(indexed, mmap_path)
        with Image.open(mmap_path) as reopened:
            rendered = reopened.convert("RGB")
        rendered.save(preview_path)
        reference = prepared
        difference = ImageChops.difference(reference, rendered)
        stats = ImageStat.Stat(difference)
        results.append(
            {
                "name": name,
                "size": list(rendered.size),
                "contentSize": list(fitted.size) if name.endswith("500x300-fit") else list(source.size),
                "mmapPath": str(mmap_path),
                "previewPath": str(preview_path),
                "mmapSha256": sha256(mmap_path),
                "meanAbsoluteErrorRgb": [round(value, 4) for value in stats.mean],
            }
        )

    report = {
        "schemaVersion": 1,
        "status": "candidate-not-deployed",
        "mapId": "XX371",
        "mapDimensions": [166, 194],
        "expectedRadarDimensions": [249, 194],
        "source": str(SOURCE),
        "sourceSha256": sha256(SOURCE),
        "paletteTemplate": str(PALETTE_TEMPLATE),
        "paletteTemplateSha256": sha256(PALETTE_TEMPLATE),
        "results": results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
