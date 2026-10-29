from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangeRange:
    kind: str
    before_start: int
    before_end: int
    after_start: int
    after_end: int


@dataclass(frozen=True)
class BinaryDiffReport:
    before_path: str
    after_path: str
    before_size: int
    after_size: int
    before_sha256: str
    after_sha256: str
    ranges: tuple[ChangeRange, ...]

    @property
    def identical(self) -> bool:
        return self.before_sha256 == self.after_sha256


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _same_length_ranges(before: bytes, after: bytes) -> tuple[ChangeRange, ...]:
    ranges: list[ChangeRange] = []
    start: int | None = None
    for index, (left, right) in enumerate(zip(before, after)):
        if left != right and start is None:
            start = index
        elif left == right and start is not None:
            ranges.append(ChangeRange("replace", start, index, start, index))
            start = None
    if start is not None:
        ranges.append(ChangeRange("replace", start, len(before), start, len(after)))
    return tuple(ranges)


def _changed_middle(before: bytes, after: bytes) -> tuple[ChangeRange, ...]:
    prefix = 0
    limit = min(len(before), len(after))
    while prefix < limit and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    before_remaining = len(before) - prefix
    after_remaining = len(after) - prefix
    while (
        suffix < before_remaining
        and suffix < after_remaining
        and before[len(before) - 1 - suffix] == after[len(after) - 1 - suffix]
    ):
        suffix += 1
    before_end = len(before) - suffix
    after_end = len(after) - suffix
    if before_end == prefix:
        kind = "insert"
    elif after_end == prefix:
        kind = "delete"
    else:
        kind = "replace"
    return (ChangeRange(kind, prefix, before_end, prefix, after_end),)


def compare_files(before_path: Path, after_path: Path) -> BinaryDiffReport:
    before_path = Path(before_path)
    after_path = Path(after_path)
    before = before_path.read_bytes()
    after = after_path.read_bytes()
    before_hash = _sha256(before)
    after_hash = _sha256(after)
    if before_hash == after_hash:
        ranges: tuple[ChangeRange, ...] = ()
    elif len(before) == len(after):
        ranges = _same_length_ranges(before, after)
    else:
        ranges = _changed_middle(before, after)
    return BinaryDiffReport(
        str(before_path.resolve()),
        str(after_path.resolve()),
        len(before),
        len(after),
        before_hash,
        after_hash,
        ranges,
    )
