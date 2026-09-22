from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image


DEFAULT_SOURCES = {
    "Mon113": Path(r"D:\XuanYuanDevPlatform\怪物库\原始素材库\星辰剑歌\Mon113\Mon113"),
    "Mon116": Path(r"D:\XuanYuanDevPlatform\怪物库\原始素材库\星辰剑歌\Mon116\Mon116"),
}
DEFAULT_OUTPUT = Path(
    r"D:\XuanYuanDevPlatform\怪物库\simulation\20260813_0945_star-mon-pak-compat\repack-24bit"
)
FORBIDDEN_OUTPUT_ROOTS = (
    Path(r"D:\11周年"),
    Path(r"D:\MirServer"),
    Path(r"D:\星辰剑歌"),
    Path(r"D:\MirServer10"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把星辰怪PAK导出的16位BMP隔离转换为目标客户端兼容的24位BMP，保留编号和Placements。"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true", help="执行隔离转换；默认只做预检")
    parser.add_argument("--verify-existing", action="store_true", help="复核已有隔离输出并修正报告路径")
    return parser.parse_args()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def read_bmp_header(path: Path) -> tuple[int, int, int, int]:
    with path.open("rb") as handle:
        header = handle.read(54)
    if len(header) < 54 or header[:2] != b"BM":
        raise RuntimeError(f"不是有效BMP：{path}")
    width = struct.unpack_from("<i", header, 18)[0]
    height = abs(struct.unpack_from("<i", header, 22)[0])
    bpp = struct.unpack_from("<H", header, 28)[0]
    compression = struct.unpack_from("<I", header, 30)[0]
    return width, height, bpp, compression


def numbered_files(root: Path, suffix: str) -> list[Path]:
    files = [path for path in root.iterdir() if path.is_file() and path.suffix.casefold() == suffix.casefold()]
    return sorted(files, key=lambda path: int(path.stem))


def validate_source(name: str, root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise RuntimeError(f"源目录不存在：{root}")
    placements = root / "Placements"
    if not placements.is_dir():
        raise RuntimeError(f"Placements目录不存在：{placements}")
    bmps = numbered_files(root, ".bmp")
    position_files = numbered_files(placements, ".txt")
    if not bmps or len(bmps) != len(position_files):
        raise RuntimeError(f"{name}帧数与坐标数不一致：{len(bmps)}/{len(position_files)}")
    expected = list(range(len(bmps)))
    bmp_indexes = [int(path.stem) for path in bmps]
    placement_indexes = [int(path.stem) for path in position_files]
    if bmp_indexes != expected or placement_indexes != expected:
        raise RuntimeError(f"{name}编号不连续或不是从00000开始")
    formats: Counter[str] = Counter()
    dimensions: list[tuple[int, int]] = []
    for path in bmps:
        width, height, bpp, compression = read_bmp_header(path)
        formats[f"{bpp}bpp/compression{compression}"] += 1
        dimensions.append((width, height))
    return {
        "name": name,
        "root": str(root),
        "frames": len(bmps),
        "placements": len(position_files),
        "formats": dict(sorted(formats.items())),
        "max_width": max(width for width, _ in dimensions),
        "max_height": max(height for _, height in dimensions),
        "nonempty_frames": sum(1 for width, height in dimensions if (width, height) != (1, 1)),
    }


def convert_library(name: str, source: Path, target: Path) -> dict[str, object]:
    target.mkdir(parents=True, exist_ok=False)
    target_placements = target / "Placements"
    target_placements.mkdir()
    source_bmps = numbered_files(source, ".bmp")
    source_placements = numbered_files(source / "Placements", ".txt")
    pixel_manifest = hashlib.sha256()
    output_manifest = hashlib.sha256()
    for index, (source_bmp, source_placement) in enumerate(zip(source_bmps, source_placements, strict=True)):
        target_bmp = target / f"{index:05d}.BMP"
        target_placement = target_placements / f"{index:05d}.txt"
        with Image.open(source_bmp) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            raw_rgb = rgb.tobytes()
            pixel_manifest.update(index.to_bytes(4, "little"))
            pixel_manifest.update(width.to_bytes(4, "little"))
            pixel_manifest.update(height.to_bytes(4, "little"))
            pixel_manifest.update(raw_rgb)
            rgb.save(target_bmp, format="BMP")
        shutil.copy2(source_placement, target_placement)
        out_width, out_height, out_bpp, out_compression = read_bmp_header(target_bmp)
        if (out_width, out_height, out_bpp, out_compression) != (width, height, 24, 0):
            raise RuntimeError(
                f"{name}/{index:05d}输出格式异常："
                f"{out_width}x{out_height}/{out_bpp}/{out_compression}"
            )
        with Image.open(target_bmp) as check_image:
            if check_image.convert("RGB").tobytes() != raw_rgb:
                raise RuntimeError(f"{name}/{index:05d}像素回读不一致")
        output_manifest.update(index.to_bytes(4, "little"))
        output_manifest.update(hashlib.sha256(target_bmp.read_bytes()).digest())
        output_manifest.update(hashlib.sha256(target_placement.read_bytes()).digest())
    return {
        "name": name,
        "source": str(source),
        "target": str(target),
        "frames": len(source_bmps),
        "placements": len(source_placements),
        "output_format": "24bpp/compression0",
        "decoded_rgb_sha256": pixel_manifest.hexdigest(),
        "output_files_sha256": output_manifest.hexdigest(),
    }


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    for forbidden in FORBIDDEN_OUTPUT_ROOTS:
        if is_within(output, forbidden):
            raise RuntimeError(f"隔离输出禁止写入生产或供体目录：{output}")
    preflight = {name: validate_source(name, source) for name, source in DEFAULT_SOURCES.items()}
    report: dict[str, object] = {
        "schema": "xydp.star-monster-pak-compat-repack.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "mode": "verify-existing" if args.verify_existing else ("apply" if args.apply else "preflight"),
        "output": str(output),
        "reason": "星辰怪身体帧为16bpp BI_BITFIELDS；目标端已验证样本为8/24bpp compression0。",
        "preflight": preflight,
        "production_writes": 0,
    }
    if args.verify_existing:
        if not output.is_dir():
            raise RuntimeError(f"待复核输出目录不存在：{output}")
        report_path = output / "compat-repack-report.json"
        previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        libraries = previous.get("libraries", [])
        for library in libraries:
            name = str(library.get("name", ""))
            if name in DEFAULT_SOURCES:
                library["target"] = str(output / name)
        report["libraries"] = libraries
        report["postcheck"] = {name: validate_source(name, output / name) for name in DEFAULT_SOURCES}
        for name, item in report["postcheck"].items():
            item["root"] = str(output / name)
            if item["formats"] != {"24bpp/compression0": item["frames"]}:
                raise RuntimeError(f"{name}已有输出不是全24位未压缩BMP：{item['formats']}")
        temporary_report = report_path.with_suffix(".json.tmp")
        temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_report, report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError(f"输出目录已存在，拒绝覆盖：{output}")
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        temporary_root = Path(temporary)
        libraries = []
        for name, source in DEFAULT_SOURCES.items():
            libraries.append(convert_library(name, source, temporary_root / name))
        for library in libraries:
            library["target"] = str(output / str(library["name"]))
        report["libraries"] = libraries
        report["postcheck"] = {
            name: validate_source(name, temporary_root / name) for name in DEFAULT_SOURCES
        }
        for name, item in report["postcheck"].items():
            item["root"] = str(output / name)
        report_path = temporary_root / "compat-repack-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_root, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
