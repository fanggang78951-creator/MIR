from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from deploy_execution_shape9_native_knockdown import assert_exclusive_open, copy_and_sync, sha256


DATA = Path(r"D:\11周年\data")
RETIRE_ROOT = Path(r"D:\MirServer\Backup\XY_EXEC_VISUAL_RETIRE_20260805_091700")
HUM_ROOT = Path(r"D:\MirServer\Backup\XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_20260804_230158")
CBOHUM_ROOT = Path(r"D:\MirServer\Backup\XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_CBOHUM_20260804_232747")
FILES = ("Hum.wzl", "Hum.wzx", "cbohum.wzl", "cbohum.wzx")

CANDIDATE = {
    "Hum.wzl": "DB73E05B9A8E19C9CD0FFD9AB1E307A80B09ADED9056AA625459BBC2D3A31522",
    "Hum.wzx": "480BD453CC7696CA49C5B62E55CA9B489E491885BD08053375507419C4497F6E",
    "cbohum.wzl": "DD7E70AF621D463CFD5F4C54EF14C1A8D7612FB20C131B5F2072E75B388026DC",
    "cbohum.wzx": "288941A165951F050C0EA1C24E7AA57A59F665FBC0CE73D218B70EFC88ED84BB",
}

ORIGINAL = {
    "Hum.wzl": "CBB0C27CF648132D4C4E647981F1ADDB124F5538BE6AF4341A036DBD975DE1BE",
    "Hum.wzx": "AE9653FF8BE0EC8489BD46F5E0B8B28747DC62D387A2659F399D67CE8D2D0605",
    "cbohum.wzl": "142EF6CFAFAF60CB10ECE5169960858F3CDA3858E9BF8BCE1A8A8E3687B3E51B",
    "cbohum.wzx": "8D3BC10057F0F8BAC2BB663C38B64CC0895AFA9E293AFFAB27587F8A7D421F16",
}


def before_source(name: str) -> Path:
    root = HUM_ROOT if name.startswith("Hum.") else CBOHUM_ROOT
    return root / "before" / name


def candidate_source(name: str) -> Path:
    root = HUM_ROOT if name.startswith("Hum.") else CBOHUM_ROOT
    return root / "stage" / name


def assert_source_hashes() -> None:
    for name in FILES:
        if sha256(DATA / name) != CANDIDATE[name]:
            raise RuntimeError(f"target candidate drifted: {name}")
        if sha256(before_source(name)) != ORIGINAL[name]:
            raise RuntimeError(f"original backup drifted: {name}")
        if sha256(candidate_source(name)) != CANDIDATE[name]:
            raise RuntimeError(f"candidate rollback source drifted: {name}")


def roll_forward_candidate(committed: list[str]) -> dict[str, str]:
    restored: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in reversed(committed):
        target = DATA / name
        temp = DATA / f".{name}.xy_exec_retire_rollforward.tmp"
        try:
            copy_and_sync(candidate_source(name), temp, CANDIDATE[name])
            os.replace(temp, target)
            actual = sha256(target)
            if actual != CANDIDATE[name]:
                raise RuntimeError(f"candidate roll-forward verification failed: {actual}")
            restored[name] = actual
        except Exception as exc:
            errors[name] = repr(exc)
            temp.unlink(missing_ok=True)
    if errors:
        raise RuntimeError(f"rollback transaction recovery incomplete: restored={restored}, errors={errors}")
    return restored


def main() -> None:
    visual_receipt = RETIRE_ROOT / "receipt.json"
    if not visual_receipt.is_file():
        raise FileNotFoundError("visual retirement receipt missing")
    visual = json.loads(visual_receipt.read_text(encoding="utf-8"))
    if visual.get("status") != "VISUAL_APPLY_DISABLED_CLEAR_RESTORE_PRESERVED":
        raise RuntimeError("visual APPLY has not been safely disabled")

    assert_source_hashes()
    for name in FILES:
        assert_exclusive_open(DATA / name)

    temps: dict[str, Path] = {}
    committed: list[str] = []
    try:
        for name in FILES:
            temp = DATA / f".{name}.xy_exec_retire_original.tmp"
            copy_and_sync(before_source(name), temp, ORIGINAL[name])
            temps[name] = temp

        assert_source_hashes()
        for name in FILES:
            assert_exclusive_open(DATA / name)

        for name in FILES:
            os.replace(temps[name], DATA / name)
            committed.append(name)
        for name in FILES:
            actual = sha256(DATA / name)
            if actual != ORIGINAL[name]:
                raise RuntimeError(f"post-rollback hash mismatch: {name} {actual}")
    except Exception:
        for temp in temps.values():
            temp.unlink(missing_ok=True)
        if committed:
            roll_forward_candidate(committed)
        raise

    rolled_back_at = datetime.now().astimezone().isoformat(timespec="seconds")
    receipt = {
        "schema": "xy-execution-visual-library-retirement-rollback/1",
        "status": "ROLLED_BACK_BYTE_EXACT_PLAN_RETIRED",
        "rolled_back_at": rolled_back_at,
        "target": str(DATA),
        "retired_candidate_hashes": CANDIDATE,
        "restored_original_hashes": {name: sha256(DATA / name) for name in FILES},
        "sources": {name: str(before_source(name)) for name in FILES},
        "visual_apply_disabled_receipt": str(visual_receipt),
        "platform_updated": False,
        "engine_or_m2_operated": False,
    }
    (RETIRE_ROOT / "client_library_rollback_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    hum_receipt = dict(receipt, files=("Hum.wzl", "Hum.wzx"))
    cbohum_receipt = dict(receipt, files=("cbohum.wzl", "cbohum.wzx"))
    (HUM_ROOT / "rollback_receipt.json").write_text(json.dumps(hum_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    (CBOHUM_ROOT / "rollback_receipt.json").write_text(json.dumps(cbohum_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
