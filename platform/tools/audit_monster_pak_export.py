from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


IMAGE_SUFFIXES = {".bmp", ".png", ".jpg", ".jpeg"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def numeric_files(root: Path, suffixes: set[str]) -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if path.stem.isdigit():
            result.append((int(path.stem), path))
    return sorted(result)


def parse_placement(path: Path) -> tuple[int, int]:
    values = [int(value) for value in path.read_text(encoding="utf-8-sig").split()]
    if len(values) != 2:
        raise ValueError(f"坐标文件格式异常：{path}")
    return values[0], values[1]


def transparent_frame(path: Path) -> Image.Image:
    with Image.open(path) as source:
        rgb = source.convert("RGB")
    background = rgb.getpixel((0, 0))
    rgba = rgb.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            if pixels[x, y][:3] == background:
                pixels[x, y] = (*background, 0)
    bbox = rgba.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def build_contact_sheet(library: str, slots: list[dict], output: Path) -> None:
    cell_width, cell_height = 330, 220
    columns = 3
    rows = (len(slots) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), (36, 39, 46))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for slot in slots:
        index = slot["slot"]
        column, row = index % columns, index // columns
        left, top = column * cell_width, row * cell_height
        draw.rectangle((left + 2, top + 2, left + cell_width - 3, top + cell_height - 3), outline=(90, 98, 112), width=2)
        status = "FULL" if slot["frameCount"] == 360 else "PARTIAL"
        draw.text((left + 10, top + 8), f"{library} slot {index}  {slot['frameCount']}/360  {status}", fill=(245, 220, 120), font=font)
        samples = slot.get("previewFrames", [])
        sample_width = max(55, (cell_width - 16) // max(1, len(samples)))
        for sample_index, sample in enumerate(samples):
            image = transparent_frame(Path(sample["path"]))
            image.thumbnail((sample_width - 8, 150), Image.Resampling.LANCZOS)
            sample_left = left + 8 + sample_index * sample_width
            sample_top = top + 42 + max(0, (150 - image.height) // 2)
            canvas.paste(image, (sample_left + (sample_width - image.width) // 2, sample_top), image)
            draw.text((sample_left + 4, top + 195), f"#{sample['id']}", fill=(205, 210, 220), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def write_slot_previews(library: str, slots: list[dict], output_root: Path) -> None:
    preview_root = output_root / "previews"
    preview_root.mkdir(parents=True, exist_ok=True)
    for slot in slots:
        candidates = slot.get("previewFrames", [])
        if not candidates:
            slot["previewPath"] = None
            continue
        image = transparent_frame(Path(candidates[0]["path"]))
        image.thumbnail((240, 220), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        canvas.alpha_composite(image, ((256 - image.width) // 2, (232 - image.height) // 2 + 16))
        preview_path = preview_root / f"{library}-slot-{slot['slot']:02d}.png"
        canvas.save(preview_path)
        slot["previewPath"] = str(preview_path)


def audit_library(export_root: Path, output_root: Path) -> dict:
    library = export_root.name
    images = numeric_files(export_root, IMAGE_SUFFIXES)
    placements_root = export_root / "Placements"
    placements = numeric_files(placements_root, {".txt"}) if placements_root.is_dir() else []
    image_ids = [item[0] for item in images]
    placement_ids = [item[0] for item in placements]
    expected_ids = list(range(len(images)))
    if image_ids != expected_ids:
        raise ValueError(f"{library} 图片编号不连续或不是从0开始")
    if placement_ids != expected_ids:
        raise ValueError(f"{library} 坐标编号与图片不一一对应")

    slots: list[dict] = []
    dimension_counts: Counter[str] = Counter()
    placeholder_count = 0
    for slot_index in range((len(images) + 359) // 360):
        begin = slot_index * 360
        slot_images = images[begin : begin + 360]
        candidates: list[dict] = []
        dimensions: list[tuple[int, int]] = []
        slot_placeholders = 0
        placement_min_x = placement_max_x = placement_min_y = placement_max_y = None
        for (image_id, image_path), (_, placement_path) in zip(slot_images, placements[begin : begin + 360], strict=True):
            with Image.open(image_path) as image:
                width, height = image.size
            dimensions.append((width, height))
            dimension_counts[f"{width}x{height}"] += 1
            is_placeholder = width <= 1 and height <= 1
            if is_placeholder:
                placeholder_count += 1
                slot_placeholders += 1
            x, y = parse_placement(placement_path)
            placement_min_x = x if placement_min_x is None else min(placement_min_x, x)
            placement_max_x = x if placement_max_x is None else max(placement_max_x, x)
            placement_min_y = y if placement_min_y is None else min(placement_min_y, y)
            placement_max_y = y if placement_max_y is None else max(placement_max_y, y)
            if not is_placeholder:
                candidates.append({
                    "id": image_id,
                    "path": str(image_path),
                    "width": width,
                    "height": height,
                    "bytes": image_path.stat().st_size,
                    "placement": {"x": x, "y": y},
                })
        preview_candidates: list[dict] = []
        if candidates:
            preview_indexes = sorted({
                0,
                len(candidates) // 3,
                (len(candidates) * 2) // 3,
                len(candidates) - 1,
            })
            preview_candidates = [candidates[item] for item in preview_indexes]
        slots.append({
            "slot": slot_index,
            "frameStart": begin,
            "frameEnd": begin + len(slot_images) - 1,
            "frameCount": len(slot_images),
            "placeholderCount": slot_placeholders,
            "nonPlaceholderCount": len(slot_images) - slot_placeholders,
            "minWidth": min(width for width, _ in dimensions),
            "maxWidth": max(width for width, _ in dimensions),
            "minHeight": min(height for _, height in dimensions),
            "maxHeight": max(height for _, height in dimensions),
            "placementRange": {
                "x": [placement_min_x, placement_max_x],
                "y": [placement_min_y, placement_max_y],
            },
            "previewFrames": preview_candidates,
        })

    write_slot_previews(library, slots, output_root)
    report = {
        "schemaVersion": 1,
        "status": "export-audited",
        "auditedAt": datetime.now(timezone.utc).isoformat(),
        "library": library,
        "exportRoot": str(export_root),
        "imageCount": len(images),
        "placementCount": len(placements),
        "continuousRange": [0, len(images) - 1],
        "fullSlotCount": sum(slot["frameCount"] == 360 for slot in slots),
        "partialSlotCount": sum(slot["frameCount"] != 360 for slot in slots),
        "placeholderCount": placeholder_count,
        "topDimensions": dimension_counts.most_common(20),
        "slots": slots,
    }
    report_path = output_root / f"{library}-export-audit.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sheet_path = output_root / f"{library}-contact-sheet.png"
    build_contact_sheet(library, slots, sheet_path)
    report["reportPath"] = str(report_path)
    report["contactSheetPath"] = str(sheet_path)
    report["reportSha256"] = sha256(report_path)
    report["contactSheetSha256"] = sha256(sheet_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="核验怪物 PAK 完整导出并按每360帧生成槽位总览")
    parser.add_argument("--export", action="append", required=True, help="含编号图片和Placements的实际图库目录，可重复")
    parser.add_argument("--out", required=True, help="证据输出目录")
    args = parser.parse_args()
    output_root = Path(args.out).resolve()
    reports = [audit_library(Path(value).resolve(), output_root) for value in args.export]
    summary = {
        "status": "ok",
        "reports": [
            {
                "library": item["library"],
                "imageCount": item["imageCount"],
                "placementCount": item["placementCount"],
                "fullSlotCount": item["fullSlotCount"],
                "partialSlotCount": item["partialSlotCount"],
                "placeholderCount": item["placeholderCount"],
                "slotFrameCounts": [slot["frameCount"] for slot in item["slots"]],
                "reportPath": item["reportPath"],
                "contactSheetPath": item["contactSheetPath"],
            }
            for item in reports
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
