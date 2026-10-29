from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

from PIL import Image


def _encode_source_as_editor_type6(source: Image.Image, *, x: int = 0, y: int = 0) -> bytes:
    image = source.convert("RGBA")
    width, height = image.size
    stride = (width * 3 + 3) & ~3
    if image.getchannel("A").getextrema() != (255, 255):
        transparent = Image.new("RGBA", image.size, (0, 0, 0, 255))
        transparent.paste(image, mask=image.getchannel("A"))
        image = transparent
    payload = image.convert("RGB").tobytes("raw", "BGR", stride, -1)
    header = struct.pack("<HHHHhhhh", 6, 0, width, height, x, y, 0, 0)
    return header + payload


def encode_image_bytes_as_editor_type6(data: bytes, *, x: int = 0, y: int = 0) -> bytes:
    with Image.open(BytesIO(data)) as source:
        return _encode_source_as_editor_type6(source, x=x, y=y)


def encode_png_as_editor_type6(path: Path, *, x: int = 0, y: int = 0) -> bytes:
    return encode_image_bytes_as_editor_type6(Path(path).read_bytes(), x=x, y=y)
