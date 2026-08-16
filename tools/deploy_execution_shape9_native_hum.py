from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


DATA = Path(r"D:\11周年\data")
ROOT = Path(r"D:\MirServer\Backup\XY_EXEC_SHAPE9_NATIVE_HUM_20260804_184447")
BEFORE = ROOT / "before"
STAGE = ROOT / "stage"

ORIGINAL = {
    "Hum.wzl": "CBB0C27CF648132D4C4E647981F1ADDB124F5538BE6AF4341A036DBD975DE1BE",
    "Hum.wzx": "AE9653FF8BE0EC8489BD46F5E0B8B28747DC62D387A2659F399D67CE8D2D0605",
    "cbohum.wzl": "142EF6CFAFAF60CB10ECE5169960858F3CDA3858E9BF8BCE1A8A8E3687B3E51B",
    "cbohum.wzx": "8D3BC10057F0F8BAC2BB663C38B64CC0895AFA9E293AFFAB27587F8A7D421F16",
}

STAGED = {
    "Hum.wzl": "44DA7372E16A9C34CE41FE71392A4DDEF096AFB7525F1DCF4B36A1F653DF6F4D",
    "Hum.wzx": "672BFCE6C2B11583617B6A6301DC51B5E6048E5019B9E07A84C960DC0AA0BC80",
    "cbohum.wzl": "ED86E47874BD157516262F7559643FCE6170F715050C4529E6327FD478D52065",
    "cbohum.wzx": "5BC8579875EFBCD621830CCE71409BF08526B6A4A0C15C28D72CD1A81E9F6B8A",
}

FILES = tuple(ORIGINAL)


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
    # Probe exactly what commit needs: no other process may keep this file open.
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
    handle = create_file(
        str(path),
        generic_read | generic_write,
        0,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        raise PermissionError(error, f"target is locked, no files changed: {path}")
    if not kernel32.CloseHandle(ctypes.c_void_p(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def copy_and_sync(source: Path, destination: Path, expected_hash: str) -> None:
    if destination.exists():
        destination.unlink()
    with source.open("rb") as read_stream, destination.open("xb") as write_stream:
        shutil.copyfileobj(read_stream, write_stream, length=8 * 1024 * 1024)
        write_stream.flush()
        os.fsync(write_stream.fileno())
    if sha256(destination) != expected_hash:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"temporary write hash mismatch: {destination}")


def restore(committed: list[str]) -> dict[str, str]:
    restored: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in reversed(committed):
        target = DATA / name
        temp = DATA / f".{name}.xy_exec_restore.tmp"
        try:
            copy_and_sync(BEFORE / name, temp, ORIGINAL[name])
            os.replace(temp, target)
            actual = sha256(target)
            if actual != ORIGINAL[name]:
                raise RuntimeError(f"restore verification failed: {actual}")
            restored[name] = actual
        except Exception as exc:  # pragma: no cover - emergency path
            errors[name] = repr(exc)
            temp.unlink(missing_ok=True)
    if errors:
        raise RuntimeError(f"rollback incomplete: restored={restored}, errors={errors}")
    return restored


def main() -> None:
    report_path = ROOT / "stage_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "STAGED_STATIC_PASS_NOT_COMMITTED":
        raise RuntimeError(f"unexpected stage status: {report.get('status')}")
    if report.get("stage") != STAGED or report.get("before") != ORIGINAL:
        raise RuntimeError("stage report hashes do not match the approved deployment contract")

    assert_hashes(DATA, ORIGINAL, "target")
    assert_hashes(BEFORE, ORIGINAL, "backup")
    assert_hashes(STAGE, STAGED, "stage")
    for name in FILES:
        assert_exclusive_open(DATA / name)

    temps: dict[str, Path] = {}
    committed: list[str] = []
    try:
        for name in FILES:
            temp = DATA / f".{name}.xy_exec_shape9.tmp"
            copy_and_sync(STAGE / name, temp, STAGED[name])
            temps[name] = temp

        # Recheck target hashes after preparation to detect concurrent edits.
        assert_hashes(DATA, ORIGINAL, "target-before-commit")
        for name in FILES:
            assert_exclusive_open(DATA / name)

        for name in FILES:
            os.replace(temps[name], DATA / name)
            committed.append(name)

        assert_hashes(DATA, STAGED, "deployed")
    except Exception:
        for temp in temps.values():
            temp.unlink(missing_ok=True)
        if committed:
            restore(committed)
        raise

    receipt = {
        "schema": "xy-execution-shape9-native-hum-deployment/1",
        "status": "DEPLOYED_PENDING_GAME_ACCEPTANCE",
        "deployed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": str(DATA),
        "files": STAGED,
        "backup": str(BEFORE),
        "backup_hashes": ORIGINAL,
        "stage_report": str(report_path),
        "rollback_verified_during_commit": False,
        "platform_updated": False,
        "server_scripts_updated": False,
        "engine_or_m2_operated": False,
    }
    receipt_path = ROOT / "deployment_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
