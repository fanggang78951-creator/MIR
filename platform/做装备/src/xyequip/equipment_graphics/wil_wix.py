"""Read-only structural parser for legacy Mir2 WIL/WIX pairs.

This module intentionally has no writer.  It exists to compare files emitted
by the user-approved WIL editor before any future batch-generation work.
"""

from __future__ import annotations

import struct
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image


WIL_WIX_HEADER_BYTES = 48
WIL_FRAME_HEADER_BYTES = 8
WIL_IMAGE_START = 1080


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def _save_bmp(image: Image.Image, path: Path) -> None:
    buffer = BytesIO()
    image.save(buffer, format="BMP")
    path.write_bytes(buffer.getvalue())


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def read_wil_wix(wil_path: Path, wix_path: Path) -> dict:
    """Return frame geometry and byte-boundary evidence without modifying data."""
    wil = wil_path.read_bytes()
    wix = wix_path.read_bytes()
    if len(wix) < WIL_WIX_HEADER_BYTES:
        raise ValueError("WIX header is truncated")
    count = _u32(wix, 44)
    expected_wix_size = WIL_WIX_HEADER_BYTES + count * 4
    if len(wix) != expected_wix_size:
        raise ValueError(f"WIX length {len(wix)} does not match count {count}")
    if len(wil) < 56:
        raise ValueError("WIL header is truncated")
    # The tested LFM2 editor stores a length-prefixed title and metadata in
    # bytes 0..43; both WIL and WIX place their 32-bit image count at 44.
    wil_count = _u32(wil, 44)
    if wil_count != count:
        raise ValueError(f"WIL/WIX count mismatch: {wil_count} != {count}")

    offsets = [_u32(wix, WIL_WIX_HEADER_BYTES + index * 4) for index in range(count)]
    if not offsets:
        return {"count": 0, "first_image_offset": None, "nonempty_frames": [], "frames": []}
    if any(offset <= 0 or offset >= len(wil) for offset in offsets):
        raise ValueError("WIX contains an out-of-bounds frame offset")
    if offsets != sorted(offsets):
        raise ValueError("WIX frame offsets are not monotonic")

    frames = []
    for index, offset in enumerate(offsets):
        next_offset = offsets[index + 1] if index + 1 < count else len(wil)
        if offset + WIL_FRAME_HEADER_BYTES > next_offset:
            raise ValueError(f"frame {index} header exceeds its byte range")
        width = _u16(wil, offset)
        height = _u16(wil, offset + 2)
        pixel_bytes = width * height
        if offset + WIL_FRAME_HEADER_BYTES + pixel_bytes > next_offset:
            raise ValueError(f"frame {index} pixel data exceeds its byte range")
        pixels = wil[offset + WIL_FRAME_HEADER_BYTES : offset + WIL_FRAME_HEADER_BYTES + pixel_bytes]
        frames.append(
            {
                "index": index,
                "offset": offset,
                "next_offset": next_offset,
                "width": width,
                "height": height,
                "x": _i16(wil, offset + 4),
                "y": _i16(wil, offset + 6),
                "pixel_bytes": pixel_bytes,
                "has_visible_pixels": any(pixels),
                "record_bytes": next_offset - offset,
            }
        )
    return {
        "count": count,
        "first_image_offset": offsets[0],
        "nonempty_frames": [frame for frame in frames if frame["width"] and frame["height"]],
        "visible_frames": [frame for frame in frames if frame["has_visible_pixels"]],
        "frames": frames,
    }


def _build_palette_tree(points: list[tuple[int, tuple[int, int, int]]], depth: int = 0):
    if not points:
        return None
    axis = depth % 3
    ordered = sorted(points, key=lambda value: (value[1][axis], value[0]))
    middle = len(ordered) // 2
    index, color = ordered[middle]
    return (axis, index, color, _build_palette_tree(ordered[:middle], depth + 1), _build_palette_tree(ordered[middle + 1 :], depth + 1))


def _nearest_palette_index(rgb: tuple[int, int, int], tree) -> int:
    best_distance = float("inf")
    best_index = 0

    def visit(node) -> None:
        nonlocal best_distance, best_index
        if node is None:
            return
        axis, index, color, left, right = node
        distance = sum((rgb[channel] - color[channel]) ** 2 for channel in range(3))
        if distance < best_distance or (distance == best_distance and index < best_index):
            best_distance, best_index = distance, index
        delta = rgb[axis] - color[axis]
        near, far = (left, right) if delta <= 0 else (right, left)
        visit(near)
        if delta * delta <= best_distance:
            visit(far)

    visit(tree)
    return best_index


def _read_bmp_frame(image_path: Path, placement_path: Path, palette_tree, color_cache: dict[tuple[int, int, int], int]) -> bytes:
    with Image.open(image_path) as image:
        if image.mode != "P":
            raise ValueError(f"{image_path} is not an 8-bit indexed BMP")
        width, height = image.size
        source_indices = list(image.get_flattened_data())
        source_palette = image.getpalette()
    if source_palette is None:
        raise ValueError(f"{image_path} does not contain a palette")
    lines = placement_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2:
        raise ValueError(f"{placement_path} must contain exactly X and Y")
    x, y = (int(value) for value in lines)
    aligned_width = ((width + 3) // 4) * 4
    pixels = bytearray()
    for row in range(height - 1, -1, -1):
        start = row * width
        for source_index in source_indices[start : start + width]:
            palette_offset = source_index * 3
            rgb = tuple(source_palette[palette_offset : palette_offset + 3])
            target_index = color_cache.get(rgb)
            if target_index is None:
                target_index = _nearest_palette_index(rgb, palette_tree)
                color_cache[rgb] = target_index
            pixels.append(target_index)
        pixels.extend(b"\0" * (aligned_width - width))
    return struct.pack("<HHhh", aligned_width, height, x, y) + bytes(pixels)


def write_wil_wix_from_bmp_directory(
    *,
    source_directory: Path,
    template_wil: Path,
    template_wix: Path,
    output_wil: Path,
    output_wix: Path,
    frame_count: int = 1200,
) -> None:
    """Emit one candidate WIL/WIX using a manually accepted pair as contract.

    Intended only for isolated candidate generation.  The template supplies the
    exact LFM2 header, fixed 256-color palette, and WIX metadata prefix.
    """
    template_wil_bytes = template_wil.read_bytes()
    template_wix_bytes = template_wix.read_bytes()
    template = read_wil_wix(template_wil, template_wix)
    if template["count"] != 1200 or template["first_image_offset"] != WIL_IMAGE_START:
        raise ValueError("template is not a 1200-slot LFM2 Graphics WIL/WIX pair")
    if not (0 < int(frame_count) <= template["count"]):
        raise ValueError("frame_count must be within the accepted template count")
    if len(template_wil_bytes) < WIL_IMAGE_START or len(template_wix_bytes) < WIL_WIX_HEADER_BYTES:
        raise ValueError("template header is truncated")
    palette_bytes = template_wil_bytes[56:WIL_IMAGE_START]
    if len(palette_bytes) != 1024:
        raise ValueError("template palette is not 256 RGBQUAD entries")
    palette = [
        (palette_bytes[index * 4 + 2], palette_bytes[index * 4 + 1], palette_bytes[index * 4])
        for index in range(256)
    ]
    palette_tree = _build_palette_tree(list(enumerate(palette)))
    color_cache: dict[tuple[int, int, int], int] = {}

    output_wil.parent.mkdir(parents=True, exist_ok=True)
    output_wix.parent.mkdir(parents=True, exist_ok=True)
    image_records = []
    for index in range(int(frame_count)):
        image_path = source_directory / f"{index:05d}.BMP"
        placement_path = source_directory / "Placements" / f"{index:05d}.txt"
        if not image_path.is_file() or not placement_path.is_file():
            raise ValueError(f"source frame {index:05d} or its placement is missing")
        image_records.append(_read_bmp_frame(image_path, placement_path, palette_tree, color_cache))

    offsets = []
    current_offset = WIL_IMAGE_START
    for record in image_records:
        offsets.append(current_offset)
        current_offset += len(record)
    wil_header = bytearray(template_wil_bytes[:WIL_IMAGE_START])
    struct.pack_into("<I", wil_header, 44, len(image_records))
    wix_header = bytearray(template_wix_bytes[:WIL_WIX_HEADER_BYTES])
    struct.pack_into("<I", wix_header, 44, len(image_records))
    output_wil.write_bytes(bytes(wil_header) + b"".join(image_records))
    output_wix.write_bytes(bytes(wix_header) + b"".join(struct.pack("<I", offset) for offset in offsets))


def prepare_bmp8_from_png_directory(
    *, source_directory: Path, template_wil: Path, output_directory: Path,
    frame_count: int = 1200, source_filename_digits: int = 5,
    treat_one_by_one_as_empty: bool = False,
    alpha_cutoff: int = 0,
) -> None:
    """Create an indexed BMP + Placement directory without overwriting output.

    Source PNG alpha becomes palette index 0.  All opaque pixels are mapped to
    the fixed palette proven by a game-accepted Graphics WIL sample.
    """
    if output_directory.exists():
        raise ValueError(f"output directory already exists: {output_directory}")
    template = template_wil.read_bytes()
    if len(template) < WIL_IMAGE_START:
        raise ValueError("template WIL header is truncated")
    if not (0 < int(frame_count) <= 1200):
        raise ValueError("frame_count must be 1..1200")
    if int(source_filename_digits) < 1:
        raise ValueError("source_filename_digits must be positive")
    if not (0 <= int(alpha_cutoff) <= 255):
        raise ValueError("alpha_cutoff must be 0..255")
    palette_bytes = template[56:WIL_IMAGE_START]
    if len(palette_bytes) != 1024:
        raise ValueError("template palette is not 256 RGBQUAD entries")
    palette_rgb = [
        (palette_bytes[index * 4 + 2], palette_bytes[index * 4 + 1], palette_bytes[index * 4])
        for index in range(256)
    ]
    palette_for_pillow = [channel for color in palette_rgb for channel in color]
    palette_tree = _build_palette_tree(list(enumerate(palette_rgb)))
    color_cache: dict[tuple[int, int, int], int] = {}
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.staging-", dir=output_directory.parent))
    try:
        placements = staging / "Placements"
        placements.mkdir()
        for index in range(int(frame_count)):
            source_name = f"{index:0{int(source_filename_digits)}d}"
            target_name = f"{index:05d}"
            source_image = source_directory / f"{source_name}.PNG"
            source_placement = source_directory / "Placements" / f"{source_name}.txt"
            target_image = staging / f"{target_name}.BMP"
            target_placement = placements / f"{target_name}.txt"
            if not source_image.is_file():
                raise ValueError(f"source PNG is missing: {source_image}")
            if source_image.stat().st_size == 0:
                image = Image.new("P", (1, 1), 0)
                image.putpalette(palette_for_pillow)
                _save_bmp(image, target_image)
                image.close()
                target_placement.write_text("0\n0\n", encoding="utf-8")
                continue
            if not source_placement.is_file():
                raise ValueError(f"source placement is missing: {source_placement}")
            with Image.open(source_image) as opened:
                rgba = opened.convert("RGBA")
                if treat_one_by_one_as_empty and rgba.size == (1, 1):
                    image = Image.new("P", (1, 1), 0)
                else:
                    indices = bytearray()
                    for red, green, blue, alpha in rgba.get_flattened_data():
                        if alpha == 0 or alpha < int(alpha_cutoff):
                            indices.append(0)
                            continue
                        rgb = (red, green, blue)
                        target_index = color_cache.get(rgb)
                        if target_index is None:
                            target_index = _nearest_palette_index(rgb, palette_tree)
                            color_cache[rgb] = target_index
                        indices.append(target_index)
                    image = Image.frombytes("P", rgba.size, bytes(indices))
            image.putpalette(palette_for_pillow)
            _save_bmp(image, target_image)
            image.close()
            shutil.copyfile(source_placement, target_placement)
        staging.replace(output_directory)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
