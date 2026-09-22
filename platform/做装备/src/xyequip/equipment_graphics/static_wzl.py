"""自包含静态 WZL/WZX sparse 替换器。

仅处理已核验的 type6 BGR24 记录：行按 bottom-up 写入，低于阈值的像素写黑色。
输入输出必须是同一槽位布局；未列出的槽位及旧 WZL 前缀保持逐字节不变。
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from PIL import Image


WZX_HEADER_BYTES = 48
FRAME_HEADER = struct.Struct("<HHHHhhhh")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _payload(image: Path, placement: tuple[int, int], alpha_cutoff: int) -> bytes:
    if not 0 <= int(alpha_cutoff) <= 255:
        raise ValueError("alpha_cutoff must be 0..255")
    with Image.open(image) as source:
        rgba = source.convert("RGBA")
        width, height = rgba.size
        pixels = bytearray()
        for y in range(height - 1, -1, -1):
            for x in range(width):
                r, g, b, alpha = rgba.getpixel((x, y))
                pixels.extend((b, g, r) if alpha >= alpha_cutoff else (0, 0, 0))
    return FRAME_HEADER.pack(6, 0, width, height, int(placement[0]), int(placement[1]), 0, 0) + bytes(pixels)


def _count(wzx: bytes) -> int:
    if len(wzx) < WZX_HEADER_BYTES:
        raise ValueError("WZX header is truncated")
    count = struct.unpack_from("<I", wzx, 44)[0]
    if len(wzx) != WZX_HEADER_BYTES + count * 4:
        raise ValueError("WZX length does not match slot count")
    return count


def _existing_payload(wzl: bytes, wzx: bytes, index: int) -> bytes | None:
    offset = struct.unpack_from("<I", wzx, WZX_HEADER_BYTES + index * 4)[0]
    if offset == 0:
        return None
    if offset < 0 or offset + FRAME_HEADER.size > len(wzl):
        raise ValueError(f"slot {index} offset is out of bounds")
    _kind, _reserved, width, height, *_ = FRAME_HEADER.unpack_from(wzl, offset)
    end = offset + FRAME_HEADER.size + width * height * 3
    if end > len(wzl):
        raise ValueError(f"slot {index} payload is truncated")
    return wzl[offset:end]


def build_static_pair(
    wzl: Path,
    wzx: Path,
    replacements: list[dict],
    out_wzl: Path,
    out_wzx: Path,
) -> dict:
    """Replace declared static slots and report sparse/no-op evidence.

    Each replacement has ``index``, ``image``, ``placement`` (x/y pair), and
    optional ``alpha_cutoff``. Existing identical semantic payloads are reused;
    they are never appended a second time.
    """
    old_wzl, old_wzx = Path(wzl).read_bytes(), Path(wzx).read_bytes()
    count = _count(old_wzx)
    if len(old_wzl) < WZX_HEADER_BYTES or struct.unpack_from("<I", old_wzl, 44)[0] != count:
        raise ValueError("WZL/WZX slot count mismatch")
    seen: set[int] = set()
    items = []
    for item in replacements:
        index = int(item["index"])
        if index in seen or not 0 <= index < count:
            raise ValueError(f"invalid or duplicate slot {index}")
        seen.add(index)
        placement = tuple(item.get("placement", (0, 0)))
        if len(placement) != 2:
            raise ValueError(f"slot {index} placement must contain x,y")
        desired = _payload(Path(item["image"]), (int(placement[0]), int(placement[1])), int(item.get("alpha_cutoff", 128)))
        items.append((index, desired, str(item["image"]), [int(placement[0]), int(placement[1])]))

    result_wzl = bytearray(old_wzl)
    result_wzx = bytearray(old_wzx)
    changed, noop, appended = [], [], []
    for index, desired, image, placement in sorted(items):
        current = _existing_payload(old_wzl, old_wzx, index)
        if current == desired:
            noop.append(index)
            continue
        offset = len(result_wzl)
        result_wzl.extend(desired)
        struct.pack_into("<I", result_wzx, WZX_HEADER_BYTES + index * 4, offset)
        changed.append(index)
        appended.append({"index": index, "offset": offset, "image": image, "placement": placement, "payloadSha256": _sha(desired)})

    out_wzl, out_wzx = Path(out_wzl), Path(out_wzx)
    out_wzl.parent.mkdir(parents=True, exist_ok=True)
    out_wzx.parent.mkdir(parents=True, exist_ok=True)
    out_wzl.write_bytes(bytes(result_wzl))
    out_wzx.write_bytes(bytes(result_wzx))
    return {
        "count": count,
        "before": {"wzlSha256": _sha(old_wzl), "wzxSha256": _sha(old_wzx)},
        "after": {"wzlSha256": _sha(bytes(result_wzl)), "wzxSha256": _sha(bytes(result_wzx))},
        "changed_slots": changed,
        "noop_slots": noop,
        "appended": appended,
        "other_slot_count": count - len(changed),
        "old_wzl_prefix_byte_identical": bytes(result_wzl[: len(old_wzl)]) == old_wzl,
    }


def append_static_pair(
    wzl: Path,
    wzx: Path,
    appends: list[dict],
    out_wzl: Path,
    out_wzx: Path,
    *,
    expected_count: int,
) -> dict:
    """Append new type6 slots without rewriting any existing frame or offset.

    The WZX count header is the only pre-existing WZX byte that changes.  All
    prior offset entries and the complete original WZL are retained verbatim,
    including unusual/non-monotonic physical frame ordering.
    """
    old_wzl, old_wzx = Path(wzl).read_bytes(), Path(wzx).read_bytes()
    count = _count(old_wzx)
    if count != int(expected_count):
        raise ValueError(f"unexpected WZX slot count: {count} != {expected_count}")
    if not appends:
        raise ValueError("append list must not be empty")
    result_wzl = bytearray(old_wzl)
    result_wzx = bytearray(old_wzx)
    # The verified WZL transaction stores the logical slot count at byte 44
    # in both paired headers.  The old WZL payload begins at byte 48.
    struct.pack_into("<I", result_wzl, 44, count + len(appends))
    struct.pack_into("<I", result_wzx, 44, count + len(appends))
    result_wzx.extend(b"\0" * (4 * len(appends)))
    added = []
    for position, item in enumerate(appends):
        placement = tuple(item.get("placement", (0, 0)))
        if len(placement) != 2:
            raise ValueError("append placement must contain x,y")
        payload = _payload(Path(item["image"]), (int(placement[0]), int(placement[1])), int(item.get("alpha_cutoff", 128)))
        offset = len(result_wzl)
        result_wzl.extend(payload)
        index = count + position
        struct.pack_into("<I", result_wzx, WZX_HEADER_BYTES + index * 4, offset)
        added.append({"index": index, "offset": offset, "payloadSha256": _sha(payload)})
    out_wzl, out_wzx = Path(out_wzl), Path(out_wzx)
    out_wzl.parent.mkdir(parents=True, exist_ok=True)
    out_wzx.parent.mkdir(parents=True, exist_ok=True)
    out_wzl.write_bytes(bytes(result_wzl))
    out_wzx.write_bytes(bytes(result_wzx))
    return {
        "beforeCount": count,
        "afterCount": count + len(appends),
        "before": {"wzlSha256": _sha(old_wzl), "wzxSha256": _sha(old_wzx)},
        "after": {"wzlSha256": _sha(bytes(result_wzl)), "wzxSha256": _sha(bytes(result_wzx))},
        "appended": added,
        "oldWzlPayloadByteIdentical": bytes(result_wzl[48:len(old_wzl)]) == old_wzl[48:],
        "oldWzxOffsetsByteIdentical": bytes(result_wzx[WZX_HEADER_BYTES:len(old_wzx)]) == old_wzx[WZX_HEADER_BYTES:],
    }
