"""Self-contained 8-bit indexed Graphics WIL/WIX candidate builder.

The embedded 1080-byte WIL headers carry the game-accepted palette and
metadata from the verified Graphics templates.  No workspace script or full
template WIL is required at run time.
"""
from __future__ import annotations

from pathlib import Path
import struct

from PIL import Image

from .wil_wix import _build_palette_tree, _nearest_palette_index


HEADER_BYTES = 1080
WIX_HEADER_BYTES = 48
_DATA = Path(__file__).with_name("data")
HUMAN_WIX_TEMPLATE_WORD = 0x0A9A


def _header(kind: str) -> bytes:
    names = {"weapon": "weapon_header_palette.bin", "human": "human_header_palette.bin"}
    try:
        header = (_DATA / names[kind]).read_bytes()
    except KeyError as exc:
        raise ValueError(f"unsupported action library kind: {kind}") from exc
    if len(header) != HEADER_BYTES:
        raise ValueError("embedded WIL header/palette is truncated")
    return header


def _wix_header(kind: str) -> bytearray:
    """Return the verified WIX template header for the requested Graphics kind."""
    if kind not in {"weapon", "human"}:
        raise ValueError(f"unsupported action library kind: {kind}")
    header = bytearray((_DATA / "wix_header.bin").read_bytes())
    if len(header) != WIX_HEADER_BYTES:
        raise ValueError("embedded WIX header is truncated")
    # The verified Human template differs from Weapon only in these two
    # unaligned header words; generated offsets and the frame count follow.
    if kind == "human":
        struct.pack_into("<H", header, 34, HUMAN_WIX_TEMPLATE_WORD)
        struct.pack_into("<H", header, 38, HUMAN_WIX_TEMPLATE_WORD)
    return header


def build_action_wil_wix(
    *,
    kind: str,
    source_root: Path,
    output_wil: Path,
    output_wix: Path,
    frame_count: int,
    source_filename_digits: int,
    alpha_cutoff: int,
    treat_one_by_one_as_empty: bool,
) -> dict[str, int]:
    """Build exactly the manifest-declared frame count without source writes."""
    if frame_count < 1 or source_filename_digits < 1 or not 0 <= alpha_cutoff <= 255:
        raise ValueError("invalid frame or alpha contract")
    if output_wil.exists() or output_wix.exists():
        raise FileExistsError("refuse to overwrite candidate WIL/WIX")
    header = _header(kind)
    palette_bytes = header[56:HEADER_BYTES]
    palette = [(palette_bytes[i * 4 + 2], palette_bytes[i * 4 + 1], palette_bytes[i * 4]) for i in range(256)]
    tree = _build_palette_tree(list(enumerate(palette)))
    cache: dict[tuple[int, int, int], int] = {}
    records: list[bytes] = []
    visible = empty = 0
    for index in range(frame_count):
        name = f"{index:0{source_filename_digits}d}"
        image_path = source_root / f"{name}.png"
        if not image_path.is_file():
            image_path = source_root / f"{name}.PNG"
        placement = source_root / "Placements" / f"{name}.txt"
        if not image_path.is_file() or not placement.is_file():
            raise ValueError(f"source frame or placement missing: {name}")
        values = placement.read_text(encoding="utf-8").splitlines()
        if len(values) != 2:
            raise ValueError(f"invalid placement: {placement}")
        x, y = (int(value) for value in values)
        with Image.open(image_path) as opened:
            rgba = opened.convert("RGBA")
            if treat_one_by_one_as_empty and rgba.size == (1, 1):
                rgba = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
                empty += 1
            else:
                visible += 1
            width, height = rgba.size
            aligned_width = ((width + 3) // 4) * 4
            pixels = bytearray()
            flat = list(rgba.get_flattened_data())
            for row in range(height - 1, -1, -1):
                start = row * width
                for red, green, blue, alpha in flat[start:start + width]:
                    if alpha < alpha_cutoff:
                        pixels.append(0)
                    else:
                        rgb = (red, green, blue)
                        target = cache.get(rgb)
                        if target is None:
                            target = _nearest_palette_index(rgb, tree)
                            cache[rgb] = target
                        pixels.append(target)
                pixels.extend(b"\0" * (aligned_width - width))
        records.append(struct.pack("<HHhh", aligned_width, height, x, y) + bytes(pixels))
    offsets: list[int] = []
    position = HEADER_BYTES
    for record in records:
        offsets.append(position)
        position += len(record)
    wil_header = bytearray(header)
    struct.pack_into("<I", wil_header, 44, frame_count)
    wix_header = _wix_header(kind)
    struct.pack_into("<I", wix_header, 44, frame_count)
    output_wil.parent.mkdir(parents=True, exist_ok=True)
    output_wix.parent.mkdir(parents=True, exist_ok=True)
    output_wil.write_bytes(bytes(wil_header) + b"".join(records))
    output_wix.write_bytes(bytes(wix_header) + b"".join(struct.pack("<I", value) for value in offsets))
    return {"frameCount": frame_count, "visibleFrames": visible, "emptyFrames": empty}
