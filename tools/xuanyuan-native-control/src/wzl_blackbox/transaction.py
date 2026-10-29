from __future__ import annotations

import os
import shutil
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from PIL import Image

from .type6 import encode_png_as_editor_type6


class TransactionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppendResult:
    image_id: int
    offset: int
    count_before: int
    count_after: int
    wzl_size_before: int
    wzl_size_after: int
    backup_dir: Path


@dataclass(frozen=True)
class PngSequenceFrame:
    # ``None`` is an intentional logical empty slot.  It avoids reopening a
    # shared transparent PNG for every empty action frame in a large sequence.
    png_path: Path | None
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class AppendSequenceResult:
    start_id: int
    end_id: int
    offsets: tuple[int, ...]
    count_before: int
    count_after: int
    wzl_size_before: int
    wzl_size_after: int
    backup_dir: Path


@dataclass(frozen=True)
class ReplaceResult:
    image_id: int
    old_offset: int
    new_offset: int
    count: int
    wzl_size_before: int
    wzl_size_after: int
    backup_dir: Path


@dataclass(frozen=True)
class InsertResult:
    image_id: int
    offset: int
    count_before: int
    count_after: int
    backup_dir: Path


@dataclass(frozen=True)
class ClearResult:
    image_id: int
    old_offset: int
    count: int
    backup_dir: Path


@dataclass(frozen=True)
class RemoveResult:
    image_id: int
    old_offset: int
    count_before: int
    count_after: int
    backup_dir: Path


@dataclass(frozen=True)
class RangeResult:
    start_id: int
    end_id: int
    count_before: int
    count_after: int
    backup_dir: Path


def _read_count(data: bytes, label: str) -> int:
    if len(data) < 48:
        raise TransactionError(f"{label} too small")
    return struct.unpack_from("<I", data, 44)[0]


def _is_fully_transparent(path: Path) -> bool:
    with Image.open(path) as source:
        image = source.convert("RGBA")
        alpha = image.getchannel("A")
        return alpha.getextrema() == (0, 0)


def _make_backup(wzl_path: Path, wzx_path: Path, backup_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = Path(backup_root) / f"type6_append_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(wzl_path, backup_dir / wzl_path.name)
    shutil.copy2(wzx_path, backup_dir / wzx_path.name)
    return backup_dir


def append_png_transaction(
    wzl_path: Path,
    wzx_path: Path,
    png_path: Path,
    *,
    x: int = 0,
    y: int = 0,
    backup_root: Path,
) -> AppendResult:
    wzl_path = Path(wzl_path)
    wzx_path = Path(wzx_path)
    png_path = Path(png_path)
    wzl_before = wzl_path.read_bytes()
    wzx_before = wzx_path.read_bytes()
    wzl_count = _read_count(wzl_before, "WZL")
    wzx_count = _read_count(wzx_before, "WZX")
    physical_count, remainder = divmod(len(wzx_before) - 48, 4)
    if remainder or wzl_count != wzx_count or wzx_count != physical_count:
        raise TransactionError(
            f"count mismatch: WZL={wzl_count}, WZX={wzx_count}, offsets={physical_count}"
        )

    image_id = physical_count
    empty = _is_fully_transparent(png_path)
    offset = 0 if empty else len(wzl_before)
    frame = b"" if empty else encode_png_as_editor_type6(png_path, x=x, y=y)
    count_after = physical_count + 1

    wzl_after = bytearray(wzl_before)
    struct.pack_into("<I", wzl_after, 44, count_after)
    wzl_after.extend(frame)
    wzx_after = bytearray(wzx_before)
    struct.pack_into("<I", wzx_after, 44, count_after)
    wzx_after.extend(struct.pack("<I", offset))

    if _read_count(wzl_after, "new WZL") != count_after:
        raise TransactionError("new WZL count verification failed")
    if _read_count(wzx_after, "new WZX") != count_after:
        raise TransactionError("new WZX count verification failed")
    if len(wzx_after) != 48 + count_after * 4:
        raise TransactionError("new WZX length verification failed")
    if offset and offset + len(frame) != len(wzl_after):
        raise TransactionError("new WZL frame boundary verification failed")

    backup_dir = _make_backup(wzl_path, wzx_path, backup_root)
    token = uuid.uuid4().hex
    wzl_temp = wzl_path.with_name(f".{wzl_path.name}.{token}.tmp")
    wzx_temp = wzx_path.with_name(f".{wzx_path.name}.{token}.tmp")
    try:
        wzl_temp.write_bytes(wzl_after)
        wzx_temp.write_bytes(wzx_after)
        os.replace(wzl_temp, wzl_path)
        os.replace(wzx_temp, wzx_path)
    except Exception:
        if wzl_temp.exists():
            wzl_temp.unlink()
        if wzx_temp.exists():
            wzx_temp.unlink()
        shutil.copy2(backup_dir / wzl_path.name, wzl_path)
        shutil.copy2(backup_dir / wzx_path.name, wzx_path)
        raise

    return AppendResult(
        image_id,
        offset,
        physical_count,
        count_after,
        len(wzl_before),
        len(wzl_after),
        backup_dir,
    )


def append_png_sequence_transaction(
    wzl_path: Path,
    wzx_path: Path,
    frames: Sequence[PngSequenceFrame],
    *,
    backup_root: Path,
) -> AppendSequenceResult:
    """Append PNG frames as one paired WZL/WZX transaction.

    Existing WZL bytes and WZX offsets are never rebuilt or reordered.  Each
    fully transparent input (or an explicit ``None`` slot) becomes one
    zero-offset logical slot; visible PNGs are encoded as normal
    editor-compatible type6 frames using their own X/Y.
    """
    if not frames:
        raise TransactionError("sequence append requires at least one frame")
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    wzl_size_before = wzl_path.stat().st_size
    with wzl_path.open("rb") as stream:
        wzl_header = stream.read(48)
    wzx_before = wzx_path.read_bytes()
    wzl_count = _read_count(wzl_header, "WZL")
    wzx_count = _read_count(wzx_before, "WZX")
    physical_count, remainder = divmod(len(wzx_before) - 48, 4)
    if remainder or wzl_count != wzx_count or wzx_count != physical_count:
        raise TransactionError(
            f"count mismatch: WZL={wzl_count}, WZX={wzx_count}, offsets={physical_count}"
        )

    count_after = physical_count + len(frames)
    token = uuid.uuid4().hex
    wzl_temp = wzl_path.with_name(f".{wzl_path.name}.{token}.tmp")
    offsets: list[int] = []
    try:
        # Do not retain 100k+ encoded frames in memory.  The formal pair is
        # untouched until every source frame has been encoded into this sibling
        # staging file and the WZX table has passed validation.
        shutil.copy2(wzl_path, wzl_temp)
        with wzl_temp.open("r+b") as stream:
            stream.seek(44)
            stream.write(struct.pack("<I", count_after))
            stream.seek(0, os.SEEK_END)
            for entry in frames:
                if entry.png_path is None:
                    frame = b""
                else:
                    png_path = Path(entry.png_path)
                    if not png_path.is_file():
                        raise TransactionError(f"sequence PNG is missing: {png_path}")
                    frame = (
                        b"" if _is_fully_transparent(png_path)
                        else encode_png_as_editor_type6(png_path, x=int(entry.x), y=int(entry.y))
                    )
                offset = 0 if not frame else stream.tell()
                if bool(frame) != bool(offset):
                    raise TransactionError("sequence offset/frame mismatch")
                offsets.append(offset)
                if frame:
                    stream.write(frame)
        wzl_size_after = wzl_temp.stat().st_size
        with wzl_temp.open("rb") as stream:
            if _read_count(stream.read(48), "new WZL") != count_after:
                raise TransactionError("new WZL count verification failed")
    except Exception:
        if wzl_temp.exists():
            wzl_temp.unlink()
        raise

    wzx_after = bytearray(wzx_before)
    struct.pack_into("<I", wzx_after, 44, count_after)
    for offset in offsets:
        wzx_after.extend(struct.pack("<I", offset))

    if _read_count(wzx_after, "new WZX") != count_after:
        raise TransactionError("new WZX count verification failed")
    if len(wzx_after) != 48 + count_after * 4:
        raise TransactionError("new WZX length verification failed")
    backup_dir = _commit_prepared_wzl_pair(
        wzl_path, wzx_path, wzl_temp, bytes(wzx_after), Path(backup_root)
    )
    return AppendSequenceResult(
        start_id=physical_count,
        end_id=count_after - 1,
        offsets=tuple(offsets),
        count_before=physical_count,
        count_after=count_after,
        wzl_size_before=wzl_size_before,
        wzl_size_after=wzl_size_after,
        backup_dir=backup_dir,
    )


def _offsets(wzx_data: bytes) -> list[int]:
    return [
        struct.unpack_from("<I", wzx_data, 48 + index * 4)[0]
        for index in range((len(wzx_data) - 48) // 4)
    ]


def _frame_ends(wzl_data: bytes, offsets: list[int]) -> dict[int, int]:
    positive = sorted({offset for offset in offsets if offset > 0})
    ends: dict[int, int] = {}
    for index, start in enumerate(positive):
        end = positive[index + 1] if index + 1 < len(positive) else len(wzl_data)
        if start < 48 or start + 16 > end or end > len(wzl_data):
            raise TransactionError(f"invalid frame bounds: {start}-{end}")
        ends[start] = end
    return ends


def _pack_pair(
    wzl_data: bytes, wzx_header: bytes, offsets: list[int]
) -> tuple[bytes, bytes]:
    count = len(offsets)
    wzl = bytearray(wzl_data)
    struct.pack_into("<I", wzl, 44, count)
    wzx = bytearray(wzx_header[:48])
    struct.pack_into("<I", wzx, 44, count)
    for offset in offsets:
        wzx.extend(struct.pack("<I", offset))
    return bytes(wzl), bytes(wzx)


def _replace_frame_bytes(
    wzl_data: bytes,
    offsets: list[int],
    image_id: int,
    frame: bytes,
) -> tuple[bytes, list[int]]:
    old_offset = offsets[image_id]
    new_offsets = list(offsets)

    if old_offset == 0:
        if not frame:
            return wzl_data, new_offsets
        following = [offset for offset in offsets[image_id + 1 :] if offset > 0]
        anchor = following[0] if following else len(wzl_data)
        wzl_after = wzl_data[:anchor] + frame + wzl_data[anchor:]
        new_offsets = [
            offset + len(frame) if offset > 0 and offset >= anchor else offset
            for offset in offsets
        ]
        new_offsets[image_id] = anchor
        return wzl_after, new_offsets

    if offsets.count(old_offset) > 1:
        if not frame:
            new_offsets[image_id] = 0
            return wzl_data, new_offsets
        new_offsets[image_id] = len(wzl_data)
        return wzl_data + frame, new_offsets

    end = _frame_ends(wzl_data, offsets)[old_offset]
    delta = len(frame) - (end - old_offset)
    wzl_after = wzl_data[:old_offset] + frame + wzl_data[end:]
    for index, offset in enumerate(offsets):
        if index == image_id:
            new_offsets[index] = old_offset if frame else 0
        elif offset > old_offset:
            new_offsets[index] = offset + delta
    return wzl_after, new_offsets


def _insert_frame_bytes(
    wzl_data: bytes,
    offsets: list[int],
    image_id: int,
    frame: bytes,
) -> tuple[bytes, list[int]]:
    if not frame:
        new_offsets = list(offsets)
        new_offsets.insert(image_id, 0)
        return wzl_data, new_offsets

    following = [offset for offset in offsets[image_id:] if offset > 0]
    anchor = following[0] if following else len(wzl_data)
    wzl_after = wzl_data[:anchor] + frame + wzl_data[anchor:]
    new_offsets = [
        offset + len(frame) if offset > 0 and offset >= anchor else offset
        for offset in offsets
    ]
    new_offsets.insert(image_id, anchor)
    return wzl_after, new_offsets


def _compact_unreferenced_frames(
    wzl_data: bytes,
    old_offsets: list[int],
    remaining_offsets: list[int],
) -> tuple[bytes, list[int]]:
    positive = sorted({offset for offset in old_offsets if offset > 0})
    if not positive:
        return wzl_data, remaining_offsets
    ends = _frame_ends(wzl_data, old_offsets)
    remaining = {offset for offset in remaining_offsets if offset > 0}
    rebuilt = bytearray(wzl_data[: positive[0]])
    mapped: dict[int, int] = {}
    for start in positive:
        if start not in remaining:
            continue
        mapped[start] = len(rebuilt)
        rebuilt.extend(wzl_data[start : ends[start]])
    new_offsets = [0 if offset == 0 else mapped[offset] for offset in remaining_offsets]
    return bytes(rebuilt), new_offsets


def _extract_frames(wzl_data: bytes, offsets: list[int]) -> tuple[bytes, list[bytes]]:
    positive = sorted({offset for offset in offsets if offset > 0})
    if not positive:
        return wzl_data, [b"" for _ in offsets]
    first_offset = positive[0]
    if first_offset < 48 or first_offset > len(wzl_data):
        raise TransactionError(f"invalid first frame offset: {first_offset}")
    end_by_offset: dict[int, int] = {}
    for index, start in enumerate(positive):
        end = positive[index + 1] if index + 1 < len(positive) else len(wzl_data)
        if start + 16 > end:
            raise TransactionError(f"invalid frame bounds: {start}-{end}")
        end_by_offset[start] = end
    frames = [
        b"" if offset == 0 else wzl_data[offset : end_by_offset[offset]]
        for offset in offsets
    ]
    return wzl_data[:first_offset], frames


def _build_pair(prefix: bytes, frames: list[bytes], wzx_header: bytes) -> tuple[bytes, bytes, list[int]]:
    count = len(frames)
    wzl = bytearray(prefix)
    offsets: list[int] = []
    for frame in frames:
        if not frame:
            offsets.append(0)
        else:
            offsets.append(len(wzl))
            wzl.extend(frame)
    struct.pack_into("<I", wzl, 44, count)
    wzx = bytearray(wzx_header[:48])
    struct.pack_into("<I", wzx, 44, count)
    for offset in offsets:
        wzx.extend(struct.pack("<I", offset))
    return bytes(wzl), bytes(wzx), offsets


def _commit_pair(
    wzl_path: Path, wzx_path: Path, wzl_after: bytes, wzx_after: bytes, backup_root: Path
) -> Path:
    backup_dir = _make_backup(wzl_path, wzx_path, backup_root)
    token = uuid.uuid4().hex
    wzl_temp = wzl_path.with_name(f".{wzl_path.name}.{token}.tmp")
    wzx_temp = wzx_path.with_name(f".{wzx_path.name}.{token}.tmp")
    try:
        wzl_temp.write_bytes(wzl_after)
        wzx_temp.write_bytes(wzx_after)
        os.replace(wzl_temp, wzl_path)
        os.replace(wzx_temp, wzx_path)
    except Exception:
        for temp in (wzl_temp, wzx_temp):
            if temp.exists():
                temp.unlink()
        shutil.copy2(backup_dir / wzl_path.name, wzl_path)
        shutil.copy2(backup_dir / wzx_path.name, wzx_path)
        raise
    return backup_dir


def _commit_prepared_wzl_pair(
    wzl_path: Path,
    wzx_path: Path,
    wzl_temp: Path,
    wzx_after: bytes,
    backup_root: Path,
) -> Path:
    """Commit a sibling WZL staging file plus a generated WZX file safely."""
    backup_dir = _make_backup(wzl_path, wzx_path, backup_root)
    token = uuid.uuid4().hex
    wzx_temp = wzx_path.with_name(f".{wzx_path.name}.{token}.tmp")
    try:
        wzx_temp.write_bytes(wzx_after)
        os.replace(wzl_temp, wzl_path)
        os.replace(wzx_temp, wzx_path)
    except Exception:
        for temp in (wzl_temp, wzx_temp):
            if temp.exists():
                temp.unlink()
        shutil.copy2(backup_dir / wzl_path.name, wzl_path)
        shutil.copy2(backup_dir / wzx_path.name, wzx_path)
        raise
    return backup_dir


def replace_png_transaction(
    wzl_path: Path,
    wzx_path: Path,
    image_id: int,
    png_path: Path,
    *,
    x: int = 0,
    y: int = 0,
    backup_root: Path,
) -> ReplaceResult:
    wzl_path = Path(wzl_path)
    wzx_path = Path(wzx_path)
    wzl_before = wzl_path.read_bytes()
    wzx_before = wzx_path.read_bytes()
    wzl_count = _read_count(wzl_before, "WZL")
    wzx_count = _read_count(wzx_before, "WZX")
    physical_count, remainder = divmod(len(wzx_before) - 48, 4)
    if remainder or wzl_count != wzx_count or wzx_count != physical_count:
        raise TransactionError(
            f"count mismatch: WZL={wzl_count}, WZX={wzx_count}, offsets={physical_count}"
        )
    if image_id < 0 or image_id >= physical_count:
        raise TransactionError(f"image id out of range: {image_id}")

    old_offsets = _offsets(wzx_before)
    old_offset = old_offsets[image_id]
    frame = (
        b"" if _is_fully_transparent(Path(png_path)) else encode_png_as_editor_type6(Path(png_path), x=x, y=y)
    )
    raw_wzl_after, new_offsets = _replace_frame_bytes(
        wzl_before, old_offsets, image_id, frame
    )
    wzl_after, wzx_after = _pack_pair(raw_wzl_after, wzx_before, new_offsets)
    backup_dir = _commit_pair(wzl_path, wzx_path, wzl_after, wzx_after, backup_root)

    return ReplaceResult(
        image_id,
        old_offset,
        new_offsets[image_id],
        physical_count,
        len(wzl_before),
        len(wzl_after),
        backup_dir,
    )


def insert_png_transaction(
    wzl_path: Path,
    wzx_path: Path,
    image_id: int,
    png_path: Path,
    *,
    x: int = 0,
    y: int = 0,
    backup_root: Path,
) -> InsertResult:
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    wzl_before, wzx_before = wzl_path.read_bytes(), wzx_path.read_bytes()
    count = _read_count(wzx_before, "WZX")
    if _read_count(wzl_before, "WZL") != count or len(wzx_before) != 48 + count * 4:
        raise TransactionError("count mismatch before insert")
    if image_id < 0 or image_id > count:
        raise TransactionError(f"insert id out of range: {image_id}")
    frame = b"" if _is_fully_transparent(Path(png_path)) else encode_png_as_editor_type6(Path(png_path), x=x, y=y)
    raw_wzl_after, new_offsets = _insert_frame_bytes(
        wzl_before, _offsets(wzx_before), image_id, frame
    )
    wzl_after, wzx_after = _pack_pair(raw_wzl_after, wzx_before, new_offsets)
    backup_dir = _commit_pair(wzl_path, wzx_path, wzl_after, wzx_after, backup_root)
    return InsertResult(image_id, new_offsets[image_id], count, count + 1, backup_dir)


def clear_slot_transaction(
    wzl_path: Path,
    wzx_path: Path,
    image_id: int,
    *,
    backup_root: Path,
) -> ClearResult:
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    wzl_before, wzx_before = wzl_path.read_bytes(), wzx_path.read_bytes()
    count = _read_count(wzx_before, "WZX")
    if _read_count(wzl_before, "WZL") != count or len(wzx_before) != 48 + count * 4:
        raise TransactionError("count mismatch before clear")
    if image_id < 0 or image_id >= count:
        raise TransactionError(f"clear id out of range: {image_id}")
    old_offsets = _offsets(wzx_before)
    old_offset = old_offsets[image_id]
    remaining_offsets = list(old_offsets)
    remaining_offsets[image_id] = 0
    raw_wzl_after, new_offsets = _compact_unreferenced_frames(
        wzl_before, old_offsets, remaining_offsets
    )
    wzl_after, wzx_after = _pack_pair(raw_wzl_after, wzx_before, new_offsets)
    backup_dir = _commit_pair(wzl_path, wzx_path, wzl_after, wzx_after, backup_root)
    return ClearResult(image_id, old_offset, count, backup_dir)


def remove_slot_transaction(
    wzl_path: Path,
    wzx_path: Path,
    image_id: int,
    *,
    backup_root: Path,
) -> RemoveResult:
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    wzl_before, wzx_before = wzl_path.read_bytes(), wzx_path.read_bytes()
    count = _read_count(wzx_before, "WZX")
    if _read_count(wzl_before, "WZL") != count or len(wzx_before) != 48 + count * 4:
        raise TransactionError("count mismatch before remove")
    if image_id < 0 or image_id >= count:
        raise TransactionError(f"remove id out of range: {image_id}")
    old_offsets = _offsets(wzx_before)
    old_offset = old_offsets[image_id]
    remaining_offsets = list(old_offsets)
    remaining_offsets.pop(image_id)
    raw_wzl_after, new_offsets = _compact_unreferenced_frames(
        wzl_before, old_offsets, remaining_offsets
    )
    wzl_after, wzx_after = _pack_pair(raw_wzl_after, wzx_before, new_offsets)
    backup_dir = _commit_pair(wzl_path, wzx_path, wzl_after, wzx_after, backup_root)
    return RemoveResult(image_id, old_offset, count, count - 1, backup_dir)


def _range_transaction(
    wzl_path: Path,
    wzx_path: Path,
    start_id: int,
    end_id: int,
    *,
    remove: bool,
    backup_root: Path,
) -> RangeResult:
    wzl_path, wzx_path = Path(wzl_path), Path(wzx_path)
    wzl_before, wzx_before = wzl_path.read_bytes(), wzx_path.read_bytes()
    count = _read_count(wzx_before, "WZX")
    if _read_count(wzl_before, "WZL") != count or len(wzx_before) != 48 + count * 4:
        raise TransactionError("count mismatch before range operation")
    if start_id < 0 or end_id < start_id or end_id >= count:
        raise TransactionError(f"range out of bounds: {start_id}-{end_id}")
    old_offsets = _offsets(wzx_before)
    remaining_offsets = list(old_offsets)
    if remove:
        del remaining_offsets[start_id : end_id + 1]
    else:
        remaining_offsets[start_id : end_id + 1] = [0] * (end_id - start_id + 1)
    raw_wzl_after, new_offsets = _compact_unreferenced_frames(
        wzl_before, old_offsets, remaining_offsets
    )
    wzl_after, wzx_after = _pack_pair(raw_wzl_after, wzx_before, new_offsets)
    backup_dir = _commit_pair(wzl_path, wzx_path, wzl_after, wzx_after, backup_root)
    return RangeResult(start_id, end_id, count, len(new_offsets), backup_dir)


def clear_range_transaction(
    wzl_path: Path, wzx_path: Path, start_id: int, end_id: int, *, backup_root: Path
) -> RangeResult:
    return _range_transaction(
        wzl_path, wzx_path, start_id, end_id, remove=False, backup_root=backup_root
    )


def remove_range_transaction(
    wzl_path: Path, wzx_path: Path, start_id: int, end_id: int, *, backup_root: Path
) -> RangeResult:
    return _range_transaction(
        wzl_path, wzx_path, start_id, end_id, remove=True, backup_root=backup_root
    )
