from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path


FILES = (
    "dress.txt",
    "XYExecKneel.wzl",
    "XYExecKneel.wzx",
    "XYExecKneelS.wzl",
    "XYExecKneelS.wzx",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transactionally deploy the execution character libraries.")
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()

    stage = args.stage.resolve()
    target = args.target.resolve()
    backup = args.backup.resolve()
    if str(target).casefold() != r"d:\11周年\data".casefold():
        raise ValueError(f"unexpected target directory: {target}")
    allowed_backup_prefixes = (
        r"d:\mirserver\backup\xy_exec_character_series_fix_",
        r"d:\mirserver\backup\xy_exec_character_marker163_",
    )
    if not any(str(backup).casefold().startswith(prefix.casefold()) for prefix in allowed_backup_prefixes):
        raise ValueError(f"unexpected backup directory: {backup}")

    before: dict[str, str] = {}
    staged: dict[str, str] = {}
    existed: dict[str, bool] = {}
    temp: dict[str, Path] = {}
    committed: list[str] = []
    for name in FILES:
        source = stage / name
        destination = target / name
        if not source.is_file():
            raise FileNotFoundError(source)
        existed[name] = destination.exists()
        before[name] = sha256(destination) if destination.exists() else "ABSENT"
        staged[name] = sha256(source)
        candidate = target / f".{name}.xy-exec-{uuid.uuid4().hex}.tmp"
        shutil.copy2(source, candidate)
        if sha256(candidate) != staged[name]:
            raise RuntimeError(f"staged copy hash mismatch: {name}")
        temp[name] = candidate

    try:
        for name in FILES:
            os.replace(temp[name], target / name)
            committed.append(name)
    except Exception as deploy_error:
        rollback_errors: list[str] = []
        for name in reversed(committed):
            destination = target / name
            try:
                if existed[name]:
                    source = backup / name
                    rollback_temp = target / f".{name}.rollback-{uuid.uuid4().hex}.tmp"
                    shutil.copy2(source, rollback_temp)
                    os.replace(rollback_temp, destination)
                else:
                    os.replace(destination, backup / f"failed-new-{name}")
            except Exception as rollback_error:
                rollback_errors.append(f"{name}: {rollback_error}")
        for name, candidate in temp.items():
            if candidate.exists():
                try:
                    os.replace(candidate, backup / f"uncommitted-{name}-{uuid.uuid4().hex}.tmp")
                except Exception as cleanup_error:
                    rollback_errors.append(f"temp {name}: {cleanup_error}")
        if rollback_errors:
            raise RuntimeError(
                f"deployment failed: {deploy_error}; rollback failures: {rollback_errors}"
            ) from deploy_error
        raise RuntimeError(f"deployment failed and was rolled back: {deploy_error}") from deploy_error

    after = {name: sha256(target / name) for name in FILES}
    if after != staged:
        raise RuntimeError(f"post-deployment hash mismatch: staged={staged}, actual={after}")
    receipt = {
        "schema": "xy-execution-character-deployment/1",
        "status": "committed-static-verification-pending",
        "stage": str(stage),
        "target": str(target),
        "backup": str(backup),
        "before": before,
        "after": after,
    }
    (backup / "deployment_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
