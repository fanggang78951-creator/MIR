from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from .transaction import TransactionError


@dataclass(frozen=True)
class EntryInfo:
    image_id: int
    empty: bool
    offset: int
    length: int
    frame_type: int | None
    width: int | None
    height: int | None
    x: int | None
    y: int | None
    sha256: str | None


@dataclass(frozen=True)
class PairReport:
    wzl: str
    wzx: str
    count: int
    wzl_size: int
    wzx_size: int
    entries: tuple[EntryInfo, ...]


def inspect_pair(wzl_path: Path, wzx_path: Path) -> PairReport:
    return inspect_pair_selection(wzl_path, wzx_path, None)


def inspect_pair_selection(
    wzl_path: Path,
    wzx_path: Path,
    image_ids: tuple[int, ...] | None,
) -> PairReport:
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    wzl, wzx = wzl_path.read_bytes(), wzx_path.read_bytes()
    if len(wzl) < 48 or len(wzx) < 48 or (len(wzx) - 48) % 4:
        raise TransactionError("invalid WZL/WZX structure")
    count = struct.unpack_from("<I", wzx, 44)[0]
    wzl_count = struct.unpack_from("<I", wzl, 44)[0]
    physical = (len(wzx) - 48) // 4
    if count != wzl_count or count != physical:
        raise TransactionError(f"count mismatch: WZL={wzl_count}, WZX={count}, offsets={physical}")
    offsets = [struct.unpack_from("<I", wzx, 48 + i * 4)[0] for i in range(count)]
    positive = sorted(set(offset for offset in offsets if offset > 0))
    ends = {start: positive[i + 1] if i + 1 < len(positive) else len(wzl) for i, start in enumerate(positive)}
    selected_ids = tuple(range(count)) if image_ids is None else tuple(dict.fromkeys(image_ids))
    for image_id in selected_ids:
        if image_id < 0 or image_id >= count:
            raise TransactionError(f"image id out of range: {image_id}")
    entries = []
    for image_id in selected_ids:
        offset = offsets[image_id]
        if offset == 0:
            entries.append(EntryInfo(image_id, True, 0, 0, None, None, None, None, None, None))
            continue
        end = ends[offset]
        if offset < 48 or offset + 16 > end or end > len(wzl):
            raise TransactionError(f"invalid frame bounds at id {image_id}: {offset}-{end}")
        frame = wzl[offset:end]
        frame_type, _zero, width, height, x, y, _payload_len, _unk = struct.unpack_from("<HHHHhhhh", frame)
        entries.append(
            EntryInfo(
                image_id,
                False,
                offset,
                len(frame),
                frame_type,
                width,
                height,
                x,
                y,
                hashlib.sha256(frame).hexdigest().upper(),
            )
        )
    return PairReport(str(wzl_path.resolve()), str(wzx_path.resolve()), count, len(wzl), len(wzx), tuple(entries))
