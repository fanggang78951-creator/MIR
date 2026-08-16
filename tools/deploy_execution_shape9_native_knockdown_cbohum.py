from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from deploy_execution_shape9_native_knockdown import assert_exclusive_open, assert_hashes, copy_and_sync, sha256


DATA = Path(r"D:\11周年\data")
BACKUP_ROOT = Path(r"D:\MirServer\Backup")
FILES = ("cbohum.wzl", "cbohum.wzx")


def restore(root: Path, before_hashes: dict[str, str], committed: list[str]) -> dict[str, str]:
    restored: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in reversed(committed):
        target = DATA / name
        temp = DATA / f".{name}.xy_exec_cbohum_restore.tmp"
        try:
            copy_and_sync(root / "before" / name, temp, before_hashes[name])
            os.replace(temp, target)
            actual = sha256(target)
            if actual != before_hashes[name]:
                raise RuntimeError(f"cbohum restore verification failed: {actual}")
            restored[name] = actual
        except Exception as exc:
            errors[name] = repr(exc)
            temp.unlink(missing_ok=True)
    if errors:
        raise RuntimeError(f"cbohum rollback incomplete: restored={restored}, errors={errors}")
    return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    expected_prefix = str(BACKUP_ROOT / "XY_EXEC_SHAPE9_NATIVE_KNOCKDOWN_CBOHUM_").casefold()
    if not str(root).casefold().startswith(expected_prefix):
        raise ValueError(f"unexpected cbohum candidate root: {root}")
    report_path = root / "stage_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "xy-execution-shape9-native-knockdown-cbohum-stage/1":
        raise RuntimeError("unexpected cbohum stage schema")
    if report.get("status") != "STAGED_STATIC_PASS_NOT_COMMITTED":
        raise RuntimeError(f"unexpected cbohum stage status: {report.get('status')}")
    before_hashes = report["before"]
    stage_hashes = report["stage"]
    if tuple(before_hashes) != FILES or tuple(stage_hashes) != FILES:
        raise RuntimeError("unexpected cbohum candidate file set")

    assert_hashes(DATA, before_hashes, "cbohum target")
    assert_hashes(root / "before", before_hashes, "cbohum backup")
    assert_hashes(root / "stage", stage_hashes, "cbohum stage")
    for name in FILES:
        assert_exclusive_open(DATA / name)

    temps: dict[str, Path] = {}
    committed: list[str] = []
    try:
        for name in FILES:
            temp = DATA / f".{name}.xy_exec_native_knockdown.tmp"
            copy_and_sync(root / "stage" / name, temp, stage_hashes[name])
            temps[name] = temp
        assert_hashes(DATA, before_hashes, "cbohum target-before-commit")
        for name in FILES:
            assert_exclusive_open(DATA / name)
        for name in FILES:
            os.replace(temps[name], DATA / name)
            committed.append(name)
        assert_hashes(DATA, stage_hashes, "deployed cbohum")
    except Exception:
        for temp in temps.values():
            temp.unlink(missing_ok=True)
        if committed:
            restore(root, before_hashes, committed)
        raise

    receipt = {
        "schema": "xy-execution-shape9-native-knockdown-cbohum-deployment/1",
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
    (root / "deployment_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
