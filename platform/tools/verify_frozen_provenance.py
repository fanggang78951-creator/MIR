from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


REQUIRED_PROVENANCE = (
    ("xydp/mingge_native_p2_install.py", Path("xydp/mingge_native_p2_install.py")),
    ("xydp/cli.py", Path("xydp/cli.py")),
    ("xydp/equipment_wash.py", Path("xydp/equipment_wash.py")),
    ("xydp/config_sync.py", Path("xydp/config_sync.py")),
    ("xydp/installer.py", Path("xydp/installer.py")),
    ("xydp/manifest.py", Path("xydp/manifest.py")),
    ("xydp/mingge_dual.py", Path("xydp/mingge_dual.py")),
    ("xydp/target_lock.py", Path("xydp/target_lock.py")),
    ("xydp/repository.py", Path("xydp/repository.py")),

)


class CArchiveFormatError(ValueError):
    pass


@dataclass(frozen=True)
class RawTocRecord:
    index: int
    raw_path: str
    entry_offset: int
    data_length: int
    uncompressed_length: int
    compression_flag: int
    typecode: str


@dataclass(frozen=True)
class RawCArchive:
    artifact: Path
    archive_start: int
    toc_offset: int
    records: tuple[RawTocRecord, ...]

    def extract(self, record: RawTocRecord) -> bytes:
        with self.artifact.open("rb") as stream:
            stream.seek(self.archive_start + record.entry_offset)
            data = stream.read(record.data_length)
        if len(data) != record.data_length:
            raise CArchiveFormatError(f"record {record.index} data is truncated")
        if record.compression_flag == 1:
            try:
                data = zlib.decompress(data)
            except zlib.error as exc:
                raise CArchiveFormatError(f"record {record.index} compressed data is invalid") from exc
        elif record.compression_flag != 0:
            raise CArchiveFormatError(f"record {record.index} has invalid compression flag")
        if len(data) != record.uncompressed_length:
            raise CArchiveFormatError(f"record {record.index} uncompressed length mismatch")
        return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _find_last_magic(stream, magic: bytes) -> int:
    stream.seek(0, 2)
    end_pos = stream.tell()
    chunk_size = 8192
    while end_pos >= len(magic):
        start_pos = max(end_pos - chunk_size, 0)
        stream.seek(start_pos)
        data = stream.read(end_pos - start_pos)
        position = data.rfind(magic)
        if position != -1:
            return start_pos + position
        end_pos = start_pos + len(magic) - 1
    return -1


def _read_raw_carchive(artifact: Path) -> RawCArchive:
    cookie_format = CArchiveReader._COOKIE_FORMAT
    cookie_length = CArchiveReader._COOKIE_LENGTH
    toc_format = CArchiveReader._TOC_ENTRY_FORMAT
    toc_header_length = CArchiveReader._TOC_ENTRY_LENGTH
    magic = CArchiveReader._COOKIE_MAGIC_PATTERN

    with artifact.open("rb") as stream:
        file_size = stream.seek(0, 2)
        cookie_offset = _find_last_magic(stream, magic)
        if cookie_offset < 0:
            raise CArchiveFormatError("could not find CArchive cookie magic")
        if cookie_offset + cookie_length > file_size:
            raise CArchiveFormatError("CArchive cookie is truncated")
        stream.seek(cookie_offset)
        cookie_data = stream.read(cookie_length)
        try:
            cookie_magic, archive_length, toc_offset, toc_length, _pyvers, pylib_name = struct.unpack(
                cookie_format, cookie_data
            )
        except struct.error as exc:
            raise CArchiveFormatError("CArchive cookie cannot be parsed") from exc
        if cookie_magic != magic or not pylib_name.rstrip(b"\0"):
            raise CArchiveFormatError("CArchive cookie is invalid")
        if archive_length < cookie_length:
            raise CArchiveFormatError("CArchive length is invalid")
        archive_end = cookie_offset + cookie_length
        archive_start = archive_end - archive_length
        if archive_start < 0:
            raise CArchiveFormatError("CArchive start is outside the artifact")
        if toc_length == 0 or toc_offset + toc_length != archive_length - cookie_length:
            raise CArchiveFormatError("CArchive TOC bounds are invalid")
        stream.seek(archive_start + toc_offset)
        toc_data = stream.read(toc_length)
        if len(toc_data) != toc_length:
            raise CArchiveFormatError("CArchive TOC is truncated")

    records: list[RawTocRecord] = []
    position = 0
    while position < len(toc_data):
        if len(toc_data) - position < toc_header_length:
            raise CArchiveFormatError("CArchive TOC entry header is truncated")
        try:
            entry_length, entry_offset, data_length, uncompressed_length, compression_flag, raw_typecode = (
                struct.unpack(toc_format, toc_data[position : position + toc_header_length])
            )
        except struct.error as exc:
            raise CArchiveFormatError("CArchive TOC entry header cannot be parsed") from exc
        if entry_length < toc_header_length + 1 or entry_length % 16 != 0:
            raise CArchiveFormatError("CArchive TOC entry length is invalid")
        entry_end = position + entry_length
        if entry_end > len(toc_data):
            raise CArchiveFormatError("CArchive TOC entry is truncated")
        name_blob = toc_data[position + toc_header_length : entry_end]
        terminator = name_blob.find(b"\0")
        if terminator < 0 or any(name_blob[terminator + 1 :]):
            raise CArchiveFormatError("CArchive TOC entry name padding is invalid")
        try:
            raw_path = name_blob[:terminator].decode("utf-8")
            typecode = raw_typecode.decode("ascii")
        except UnicodeDecodeError as exc:
            raise CArchiveFormatError("CArchive TOC entry text encoding is invalid") from exc
        if compression_flag not in (0, 1):
            raise CArchiveFormatError("CArchive TOC compression flag is invalid")
        if entry_offset + data_length > toc_offset:
            raise CArchiveFormatError("CArchive TOC entry data is outside the payload")
        records.append(
            RawTocRecord(
                index=len(records),
                raw_path=raw_path,
                entry_offset=entry_offset,
                data_length=data_length,
                uncompressed_length=uncompressed_length,
                compression_flag=compression_flag,
                typecode=typecode,
            )
        )
        position = entry_end

    return RawCArchive(artifact=artifact, archive_start=archive_start, toc_offset=toc_offset, records=tuple(records))


def _canonical_archive_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("/"):
        raise ValueError("absolute_path")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise ValueError("drive_path")
    segments = normalized.split("/")
    if any(segment == "" for segment in segments):
        raise ValueError("empty_segment")
    if any(segment == "." for segment in segments):
        raise ValueError("dot_segment")
    if any(segment == ".." for segment in segments):
        raise ValueError("parent_segment")
    if any(segment.endswith((" ", ".")) for segment in segments):
        raise ValueError("windows_noncanonical_trailing")
    return "/".join(segments)


def verify_artifact(artifact: Path, source_root: Path) -> dict[str, object]:
    artifact = artifact.resolve(strict=True)
    source_root = source_root.resolve(strict=True)
    archive = _read_raw_carchive(artifact)

    path_violations: list[dict[str, object]] = []
    records_by_key: dict[str, list[tuple[RawTocRecord, str]]] = {}
    path_record_count = 0
    option_count = 0
    for record in archive.records:
        if record.typecode == "o":
            option_count += 1
            continue
        path_record_count += 1
        try:
            canonical_path = _canonical_archive_path(record.raw_path)
        except ValueError as exc:
            path_violations.append(
                {
                    "record_index": record.index,
                    "raw_path": record.raw_path,
                    "typecode": record.typecode,
                    "reason": str(exc),
                }
            )
            continue
        records_by_key.setdefault(canonical_path.casefold(), []).append((record, canonical_path))

    path_collisions = [
        {
            "reason": "path_collision",
            "canonical_key": canonical_key,
            "records": [
                {
                    "record_index": record.index,
                    "raw_path": record.raw_path,
                    "canonical_path": canonical_path,
                    "typecode": record.typecode,
                }
                for record, canonical_path in matches
            ],
        }
        for canonical_key, matches in records_by_key.items()
        if len(matches) > 1
    ]

    results: list[dict[str, object]] = []
    required_ok = True
    for archive_path, source_relative in REQUIRED_PROVENANCE:
        source_path = source_root / source_relative
        source_bytes = source_path.read_bytes()
        matches = records_by_key.get(archive_path.casefold(), [])
        record = matches[0][0] if len(matches) == 1 else None
        embedded_bytes: bytes | None = None
        status = "ok"
        if not matches:
            status = "missing"
        elif len(matches) != 1:
            status = "duplicate"
        elif record is None or record.typecode != "b":
            status = "wrong_type"
        else:
            embedded_bytes = archive.extract(record)
            if embedded_bytes != source_bytes:
                status = "hash_mismatch"
        if status != "ok":
            required_ok = False
        results.append(
            {
                "archive_path": archive_path,
                "source_path": str(source_path),
                "source_sha256": _sha256(source_bytes),
                "record_count": len(matches),
                "record_index": record.index if record is not None else None,
                "raw_archive_path": record.raw_path if record is not None else None,
                "typecode": record.typecode if record is not None else None,
                "embedded_sha256": _sha256(embedded_bytes) if embedded_bytes is not None else None,
                "status": status,
            }
        )

    artifact_ok = required_ok and not path_violations and not path_collisions
    return {
        "artifact": str(artifact),
        "artifact_sha256": _sha256_path(artifact),
        "raw_toc_record_count": len(archive.records),
        "archive_path_record_count": path_record_count,
        "archive_option_count": option_count,
        "status": "ok" if artifact_ok else "failed",
        "path_violations": path_violations,
        "path_collisions": path_collisions,
        "required_provenance": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify exact provenance source bytes embedded in a PyInstaller onefile artifact."
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = verify_artifact(args.artifact, args.source_root)
    except Exception as exc:
        print(f"frozen provenance verification error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
