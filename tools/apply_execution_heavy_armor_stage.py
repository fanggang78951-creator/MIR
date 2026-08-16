from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def expected_target(relative: str, server: Path, client: Path) -> Path:
    path = Path(relative)
    parts = path.parts
    if not parts:
        raise ValueError("empty staged relative path")
    if parts[0] == "server":
        target = server.joinpath(*parts[1:])
        root = server
    elif parts[0] == "client":
        target = client.joinpath(*parts[1:])
        root = client
    else:
        raise ValueError(f"unsupported staged root: {relative}")
    if not within(target, root):
        raise ValueError(f"target escapes root: {relative}")
    return target


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.xydp-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        if sha256(temporary) != sha256(source):
            raise IOError(f"temporary copy hash mismatch: {target}")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the statically verified execution heavy-armor stage transactionally.")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("refusing apply without --yes")

    stage = Path(args.stage).resolve()
    server = Path(args.server).resolve()
    client = Path(args.client).resolve()
    manifest_path = stage / "stage_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "candidate-static-stage-passed":
        raise ValueError("stage is not marked candidate-static-stage-passed")

    entries: list[dict[str, object]] = []
    for source_entry in manifest["files"]:
        entry = dict(source_entry)
        source = (stage / str(entry["relative"])).resolve()
        if not within(source, stage) or not source.is_file():
            raise FileNotFoundError(f"invalid staged file: {source}")
        if sha256(source) != entry["after_sha256"]:
            raise ValueError(f"staged file hash changed: {source}")
        target = expected_target(str(entry["relative"]), server, client)
        manifest_target = Path(str(entry["target"])).resolve(strict=False)
        if target.resolve(strict=False) != manifest_target:
            raise ValueError(f"manifest target mismatch: {entry['relative']}")
        if bool(entry["target_exists"]):
            if not target.is_file():
                raise FileNotFoundError(f"live target missing: {target}")
            if sha256(target) != entry["before_sha256"]:
                raise ValueError(f"live target changed after preflight: {target}")
        elif target.exists():
            raise FileExistsError(f"new target appeared after preflight: {target}")
        entry["source_path"] = str(source)
        entry["target_path"] = str(target)
        entries.append(entry)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = server / "Backup" / f"XY_EXEC_HEAVY_ARMOR_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    receipt_path = backup / "transaction_receipt.json"
    receipt: dict[str, object] = {
        "schema": "xy-execution-heavy-armor-transaction/1",
        "status": "backup-prepared",
        "operation": "candidate-test-install",
        "created_at": datetime.now().astimezone().isoformat(),
        "stage": str(stage),
        "server": str(server),
        "client": str(client),
        "shape_id": manifest["shape_id"],
        "files": [],
    }

    for entry in entries:
        item = {
            "relative": entry["relative"],
            "target": entry["target_path"],
            "existed_before": entry["target_exists"],
            "before_sha256": entry["before_sha256"],
            "after_sha256": entry["after_sha256"],
            "backup": None,
        }
        if bool(entry["target_exists"]):
            backup_file = backup / "before" / str(entry["relative"])
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(entry["target_path"]), backup_file)
            if sha256(backup_file) != entry["before_sha256"]:
                raise IOError(f"backup hash mismatch: {entry['target_path']}")
            item["backup"] = str(backup_file)
        receipt["files"].append(item)
    write_receipt(receipt_path, receipt)

    applied: list[dict[str, object]] = []
    try:
        for entry in entries:
            atomic_copy(Path(str(entry["source_path"])), Path(str(entry["target_path"])))
            target = Path(str(entry["target_path"]))
            if sha256(target) != entry["after_sha256"]:
                raise IOError(f"installed hash mismatch: {target}")
            applied.append(entry)
        receipt["status"] = "candidate-installed-static-verified"
        receipt["installed_at"] = datetime.now().astimezone().isoformat()
        write_receipt(receipt_path, receipt)
    except Exception as error:
        rollback_errors: list[str] = []
        for entry in reversed(applied):
            target = Path(str(entry["target_path"]))
            try:
                if bool(entry["target_exists"]):
                    source = backup / "before" / str(entry["relative"])
                    atomic_copy(source, target)
                elif target.exists():
                    target.unlink()
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        receipt["status"] = "apply-failed-rollback-attempted"
        receipt["error"] = str(error)
        receipt["rollback_errors"] = rollback_errors
        write_receipt(receipt_path, receipt)
        if rollback_errors:
            raise RuntimeError(f"apply failed and rollback had errors: {rollback_errors}") from error
        raise

    print(json.dumps({
        "status": receipt["status"],
        "backup": str(backup),
        "receipt": str(receipt_path),
        "installed_files": len(entries),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
