from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.xydp-rollback-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        if sha256(temporary) != sha256(source):
            raise IOError(f"rollback temporary copy hash mismatch: {target}")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Byte-restore an execution heavy-armor candidate transaction.")
    parser.add_argument("--backup", required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("refusing rollback without --yes")

    backup = Path(args.backup).resolve()
    receipt_path = backup / "transaction_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    if receipt.get("schema") != "xy-execution-heavy-armor-transaction/1":
        raise ValueError("unsupported transaction receipt")
    if receipt.get("status") not in {"candidate-installed-static-verified", "rollback-failed"}:
        raise ValueError(f"receipt status does not allow rollback: {receipt.get('status')}")

    for entry in receipt["files"]:
        target = Path(entry["target"])
        if not target.is_file():
            raise FileNotFoundError(f"installed target missing: {target}")
        if sha256(target) != entry["after_sha256"]:
            raise ValueError(f"installed target was modified; rollback blocked: {target}")
        if entry["existed_before"]:
            source = Path(entry["backup"])
            if not source.is_file() or sha256(source) != entry["before_sha256"]:
                raise ValueError(f"backup invalid: {source}")

    changed: list[dict[str, object]] = []
    try:
        for entry in reversed(receipt["files"]):
            target = Path(entry["target"])
            if entry["existed_before"]:
                atomic_copy(Path(entry["backup"]), target)
                if sha256(target) != entry["before_sha256"]:
                    raise IOError(f"rollback read-back mismatch: {target}")
            else:
                target.unlink()
            changed.append(entry)
        receipt["status"] = "rolled-back-byte-exact"
        receipt["rolled_back_at"] = datetime.now().astimezone().isoformat()
    except Exception as error:
        receipt["status"] = "rollback-failed"
        receipt["rollback_error"] = str(error)
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": receipt["status"],
        "backup": str(backup),
        "restored_files": len(changed),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
