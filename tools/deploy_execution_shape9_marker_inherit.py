from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import deploy_execution_shape9_native_hum as tx


DATA = Path(r"D:\11周年\data")
ROOT = Path(r"D:\MirServer\Backup\XY_EXEC_SHAPE9_MARKER_INHERIT_20260804_191830")
BEFORE = ROOT / "before"
STAGE = ROOT / "stage"
FILES = ("Hum.wzl", "Hum.wzx", "cbohum.wzl", "cbohum.wzx")

ORIGINAL = {
    "Hum.wzl": "CBB0C27CF648132D4C4E647981F1ADDB124F5538BE6AF4341A036DBD975DE1BE",
    "Hum.wzx": "AE9653FF8BE0EC8489BD46F5E0B8B28747DC62D387A2659F399D67CE8D2D0605",
    "cbohum.wzl": "142EF6CFAFAF60CB10ECE5169960858F3CDA3858E9BF8BCE1A8A8E3687B3E51B",
    "cbohum.wzx": "8D3BC10057F0F8BAC2BB663C38B64CC0895AFA9E293AFFAB27587F8A7D421F16",
}
STAGED = {
    "Hum.wzl": "FC142E3F454225DFAF3A9866D0CAEA23A9FD098804556F6576F6A2652A935B3B",
    "Hum.wzx": "1624527A8E0A03170F4BD47EE18B5D43B36877A3732AB842CC530DF96D3E59AD",
    "cbohum.wzl": "8E242183F2F1D633237AAC2862108D7C40A43EBBE508A7FF9DB9CEF14CC9C76D",
    "cbohum.wzx": "6D3F7C2DAF0BB29C396B969D8D021F8FDB290B897900881916829817832C2CFC",
}


def restore(committed: list[str]) -> None:
    errors: dict[str, str] = {}
    for name in reversed(committed):
        temp = DATA / f".{name}.xy_exec_marker_restore.tmp"
        try:
            tx.copy_and_sync(BEFORE / name, temp, ORIGINAL[name])
            os.replace(temp, DATA / name)
            if tx.sha256(DATA / name) != ORIGINAL[name]:
                raise RuntimeError("restored hash mismatch")
        except Exception as exc:  # pragma: no cover - emergency path
            errors[name] = repr(exc)
            temp.unlink(missing_ok=True)
    if errors:
        raise RuntimeError(f"rollback incomplete: {errors}")


def main() -> None:
    stage_report_path = ROOT / "stage_report.json"
    stage_report = json.loads(stage_report_path.read_text(encoding="utf-8"))
    if stage_report.get("status") != "STAGED_NATIVE_TYPE_INHERIT_PASS_NOT_COMMITTED":
        raise RuntimeError(f"unexpected stage status: {stage_report.get('status')}")
    if stage_report.get("before") != ORIGINAL or stage_report.get("stage") != STAGED:
        raise RuntimeError("stage report does not match deployment contract")

    tx.assert_hashes(DATA, ORIGINAL, "target")
    tx.assert_hashes(BEFORE, ORIGINAL, "backup")
    tx.assert_hashes(STAGE, STAGED, "stage")
    for name in FILES:
        tx.assert_exclusive_open(DATA / name)

    temps: dict[str, Path] = {}
    committed: list[str] = []
    try:
        for name in FILES:
            temp = DATA / f".{name}.xy_exec_marker.tmp"
            tx.copy_and_sync(STAGE / name, temp, STAGED[name])
            temps[name] = temp
        tx.assert_hashes(DATA, ORIGINAL, "target-before-commit")
        for name in FILES:
            tx.assert_exclusive_open(DATA / name)
        for name in FILES:
            os.replace(temps[name], DATA / name)
            committed.append(name)
        tx.assert_hashes(DATA, STAGED, "deployed")
    except Exception:
        for temp in temps.values():
            temp.unlink(missing_ok=True)
        if committed:
            restore(committed)
        raise

    receipt = {
        "schema": "xy-execution-shape9-marker-inherit-deployment/1",
        "status": "DEPLOYED_PENDING_GAME_ACCEPTANCE",
        "deployed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": str(DATA),
        "files": STAGED,
        "backup": str(BEFORE),
        "backup_hashes": ORIGINAL,
        "stage_report": str(stage_report_path),
        "platform_updated": False,
        "server_scripts_updated": False,
        "engine_or_m2_operated": False,
    }
    (ROOT / "deployment_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
