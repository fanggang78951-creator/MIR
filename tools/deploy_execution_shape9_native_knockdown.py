from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


DATA = Path(r"D:\11周年\data")
BACKUP_ROOT = Path(r"D:\MirServer\Backup")
FILES = ("Hum.wzl", "Hum.wzx")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def assert_hashes(folder: Path, expected: dict[str, str], label: str) -> None:
    for name, expected_hash in expected.items():
        path = folder / name
        if not path.is_file():
            raise FileNotFoundError(f"{label} missing: {path}")
        actual = sha256(path)
        if actual != expected_hash:
            raise RuntimeError(f"{label} hash drifted: {name} {actual} != {expected_hash}")


def assert_exclusive_open(path: Path) -> None:
    generic_read = 0x80000000
    generic_write = 0x40000000
    open_existing = 3
    file_attribute_normal = 0x80
    invalid_handle = ctypes.c_void_p(-1).value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(str(path), generic_read | generic_write, 0, None, open_existing, file_attribute_normal, None)
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        raise PermissionError(error, f"target is locked, no files changed: {path}")
    if not kernel32.CloseHandle(ctypes.c_void_p(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def copy_and_sync(source: Path, destination: Path, expected_hash: str) -> None:
    destination.unlink(missing_ok=True)
    with source.open("rb") as read_stream, destination.open("xb") as write_stream:
        shutil.copyfileobj(read_stream, write_stream, length=8 * 1024 * 1024)
        write_stream.flush()
        os.fsync(write_stream.fileno())
    if sha256(destination) != expected_hash:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"temporary write hash mismatch: {destination}")


def restore(root: Path, before_hashes: dict[str, str], committed: list[str]) -> dict[str, str]:
    restored: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in reversed(committed):
        target = DATA / name
        temp = DATA / f".{name}.xy_exec_restore.tmp"
        try:
            copy_and_sync(root / "before" / name, temp, before_hashes[name])
            os.replace(temp, target)
            actual = sha256(target)
            if actual != before_hashes[name]:
                raise RuntimeError(f"restore verification failed: {actual}")
            restored[name] = actual
        except Exception as exc:  # emergency rollback evidence
            errors[name] = repr(exc)
            temp.unlink(missing_ok=True)
    if errors:
        raise RuntimeError(f"rollback incomplete: restored={restored}, errors={errors}")
    return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    expected_prefix = str(BACKUP_ROOT / "XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_").casefold()
    if not str(root).casefold().startswith(expected_prefix):
        raise ValueError(f"unexpected candidate root: {root}")

    report_path = root / "stage_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "xy-execution-shape9-native-knockdown-stage/1":
        raise RuntimeError("unexpected stage schema")
    if report.get("status") != "STAGED_STATIC_PASS_NOT_COMMITTED":
        raise RuntimeError(f"unexpected stage status: {report.get('status')}")
    before_hashes = report["before"]
    stage_hashes = report["stage"]
    if tuple(before_hashes) != FILES or tuple(stage_hashes) != FILES:
        raise RuntimeError("unexpected candidate file set")

    assert_hashes(DATA, before_hashes, "target")
    assert_hashes(root / "before", before_hashes, "backup")
    assert_hashes(root / "stage", stage_hashes, "stage")
    for name in FILES:
        assert_exclusive_open(DATA / name)

    temps: dict[str, Path] = {}
    committed: list[str] = []
    try:
        for name in FILES:
            temp = DATA / f".{name}.xy_exec_native_knockdown.tmp"
            copy_and_sync(root / "stage" / name, temp, stage_hashes[name])
            temps[name] = temp
        assert_hashes(DATA, before_hashes, "target-before-commit")
        for name in FILES:
            assert_exclusive_open(DATA / name)
        for name in FILES:
            os.replace(temps[name], DATA / name)
            committed.append(name)
        assert_hashes(DATA, stage_hashes, "deployed")
    except Exception:
        for temp in temps.values():
            temp.unlink(missing_ok=True)
        if committed:
            restore(root, before_hashes, committed)
        raise

    receipt = {
        "schema": "xy-execution-shape9-native-knockdown-deployment/1",
        "status": "DEPLOYED_PENDING_GAME_ACCEPTANCE",
        "deployed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": str(DATA),
        "files": stage_hashes,
        "backup": str(root / "before"),
        "backup_hashes": before_hashes,
        "stage_report": str(report_path),
        "platform_updated": False,
        "server_scripts_updated": False,
        "engine_or_m2_operated": False,
    }
    receipt_path = root / "deployment_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
