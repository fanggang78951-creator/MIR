"""Recoverable manifest file/Shape transaction for equipment graphics."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime


class TransactionError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")


def _restore_and_verify(registered: list[dict[str, object]], db: dict[str, object]) -> bool:
    try:
        for item in reversed(registered):
            live = Path(str(item["target"]))
            if bool(item["existed"]):
                shutil.copy2(Path(str(item["backup"])), live)
            elif live.exists():
                live.unlink()
        database = Path(str(db["target"]))
        shutil.copy2(Path(str(db["backup"])), database)
        for item in registered:
            live = Path(str(item["target"]))
            if bool(item["existed"]):
                if not live.is_file() or sha256(live) != item["before"]:
                    return False
            elif live.exists():
                return False
        return database.is_file() and sha256(database) == db["before"]
    except (OSError, ValueError):
        return False


def _expected_files(preflight: dict[str, object], registered: list[dict[str, object]]) -> list[dict[str, object]]:
    source = preflight.get("expectedFiles")
    if not isinstance(source, list):
        source = registered
    return [{"target": str(item["target"]), "after": item.get("after"), "role": item.get("role")}
            for item in source]


def apply_prepared(*, manifest_path: Path, preflight: dict[str, object]) -> dict[str, object]:
    """Apply prepared files and declared Shape changes as one recoverable transaction."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("preparedFiles")
    if not isinstance(files, list):
        raise TransactionError("preparedFiles 必须为数组")
    updates = [update for update in preflight.get("shapeUpdates", [])
               if update.get("oldShape") != update.get("newShape")]
    target = manifest.get("target", {})
    database = Path(target.get("database", ""))
    if not database.is_file():
        raise TransactionError("目标数据库不存在")
    for suffix in ("-wal", "-journal"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.is_file() and sidecar.stat().st_size:
            raise TransactionError(f"数据库存在非空{suffix}，拒绝文件备份事务")
    expected_db = preflight.get("dbHash")
    if expected_db and sha256(database) != expected_db:
        raise TransactionError("数据库预检后漂移")
    if not files and not updates:
        out = Path(manifest["outputRoot"]) / "transactions" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out.mkdir(parents=True, exist_ok=False)
        receipt_path = out / "receipt.json"
        _write_receipt(receipt_path, {
            "manifest": str(manifest_path), "configHash": preflight.get("configHash"),
            "sourceHashes": preflight.get("sourceHashes", {}),
            "shapeUpdates": [], "files": [], "expectedFiles": _expected_files(preflight, []),
            "database": {"target": str(database), "before": sha256(database), "after": sha256(database)},
            "status": "noop",
        })
        return {"receiptPath": str(receipt_path), "status": "noop"}
    for entry in files:
        candidate, live = Path(entry["candidate"]), Path(entry["target"])
        if not candidate.is_file():
            raise TransactionError(f"候选不存在: {candidate}")
        if entry.get("candidateSha256") != sha256(candidate):
            raise TransactionError(f"候选哈希漂移: {candidate}")
        if live.exists() and entry.get("targetSha256") != sha256(live):
            raise TransactionError(f"目标预检后漂移: {live}")
        if not live.exists() and entry.get("targetSha256") not in (None, ""):
            raise TransactionError(f"目标应不存在但基线声明非空: {live}")

    out = Path(manifest["outputRoot"]) / "transactions" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out.mkdir(parents=True, exist_ok=False)
    originals = out / "original"; originals.mkdir()
    registered: list[dict[str, object]] = []
    for number, entry in enumerate(files):
        candidate, live = Path(entry["candidate"]), Path(entry["target"])
        existed = live.exists(); backup = originals / f"{number:02d}_{live.name}"
        if existed: shutil.copy2(live, backup)
        registered.append({"target": str(live), "backup": str(backup), "existed": existed,
                           "before": sha256(live) if existed else None,
                           "after": sha256(candidate), "role": entry.get("role")})
    db_backup = originals / database.name; shutil.copy2(database, db_backup)
    db_before = sha256(database)
    receipt = {"manifest": str(manifest_path), "configHash": preflight.get("configHash"),
               "sourceHashes": preflight.get("sourceHashes", {}),
               "shapeUpdates": updates, "files": registered,
               "expectedFiles": _expected_files(preflight, registered),
               "database": {"target": str(database), "backup": str(db_backup), "before": db_before},
               "status": "registered"}
    receipt_path = out / "receipt.json"; _write_receipt(receipt_path, receipt)
    connection = None
    writes_started = False
    try:
        connection = sqlite3.connect(database, isolation_level=None)
        connection.execute("BEGIN IMMEDIATE")
        if expected_db and sha256(database) != expected_db:
            raise TransactionError("数据库锁定后基线漂移")
        if sha256(database) != db_before:
            raise TransactionError("数据库锁定后基线漂移")
        writes_started = True
        changed_files = []
        for entry in files:
            candidate, live = Path(entry["candidate"]), Path(entry["target"])
            if live.exists() and sha256(live) == entry["candidateSha256"]: continue
            live.parent.mkdir(parents=True, exist_ok=True)
            temporary = live.with_name(f".{live.name}.equipment-graphics.tmp")
            shutil.copy2(candidate, temporary); os.replace(temporary, live)
            if sha256(live) != entry["candidateSha256"]: raise TransactionError(f"文件回读失败: {live}")
            changed_files.append(live)
        for update in updates:
            row = connection.execute("SELECT Idx, Name, StdMode, Looks, Shape FROM StdItems WHERE Idx=?", (update["idx"],)).fetchone()
            if row is None or row[4] != update["oldShape"]: raise TransactionError(f"数据库Shape漂移: Idx={update['idx']}")
            old_row = update.get("oldRow")
            if old_row is not None and list(row) != list(old_row): raise TransactionError(f"数据库行漂移: Idx={update['idx']}")
            if row[4] != update["newShape"]: connection.execute("UPDATE StdItems SET Shape=? WHERE Idx=?", (update["newShape"], update["idx"]))
        connection.commit()
        receipt["database"]["after"] = sha256(database); receipt["status"] = "applied"
    except Exception:
        if connection is not None:
            try: connection.rollback()
            except sqlite3.Error: pass
        restored = _restore_and_verify(registered, receipt["database"]) if writes_started else True
        receipt["status"] = "failed-restored" if restored else "failed-rollback-incomplete"
        _write_receipt(receipt_path, receipt); raise
    finally:
        if connection is not None: connection.close()
    if not changed_files and not updates: receipt["status"] = "noop"
    _write_receipt(receipt_path, receipt)
    return {"receiptPath": str(receipt_path), "status": receipt["status"]}


def rollback_receipt(receipt_path: Path) -> dict[str, object]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "applied": raise TransactionError("只允许回滚已完成事务")
    for item in receipt["files"]:
        live, backup = Path(item["target"]), Path(item["backup"])
        if bool(item["existed"]):
            if not live.is_file() or sha256(live) != item["after"]: raise TransactionError(f"拒绝覆盖外部变更: {live}")
            if not backup.is_file() or sha256(backup) != item["before"]: raise TransactionError(f"备份哈希异常: {backup}")
        elif not live.is_file() or sha256(live) != item["after"]:
            raise TransactionError(f"拒绝覆盖外部变更: {live}")
    database, db_backup = Path(receipt["database"]["target"]), Path(receipt["database"]["backup"])
    if not database.is_file() or sha256(database) != receipt["database"].get("after"): raise TransactionError("拒绝覆盖数据库外部变更")
    if not db_backup.is_file() or sha256(db_backup) != receipt["database"].get("before"): raise TransactionError("数据库备份哈希异常")
    try:
        for item in reversed(receipt["files"]):
            live = Path(item["target"])
            if bool(item["existed"]): shutil.copy2(Path(item["backup"]), live)
            elif live.exists(): live.unlink()
        shutil.copy2(db_backup, database); receipt["status"] = "rolled-back"; _write_receipt(receipt_path, receipt)
        if not _restore_and_verify(receipt["files"], receipt["database"]):
            receipt["status"] = "failed-rollback-incomplete"; _write_receipt(receipt_path, receipt)
            raise TransactionError("回滚后核验失败")
        _write_receipt(receipt_path, receipt)
        return {"receiptPath": str(receipt_path), "status": "rolled-back"}
    except Exception:
        receipt["status"] = "failed-rollback-incomplete"; _write_receipt(receipt_path, receipt); raise


def _restore_files(registered: list[dict[str, object]]) -> bool:
    try:
        for item in reversed(registered):
            target = Path(str(item["target"]))
            if bool(item["existed"]):
                shutil.copy2(Path(str(item["backup"])), target)
            elif target.exists():
                target.unlink()
        return all(
            (Path(str(item["target"])).is_file() and sha256(Path(str(item["target"]))) == item["before"])
            if bool(item["existed"]) else not Path(str(item["target"])).exists()
            for item in registered
        )
    except OSError:
        return False


def _atomic_copy(candidate: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.equipment-graphics-append.tmp")
    shutil.copy2(candidate, temporary)
    os.replace(temporary, target)


def apply_append_prepared(
    *, output_root: Path, config_hash: str, source_hashes: dict[str, str],
    resource_map: list[dict[str, object]], prepared: list[dict[str, object]],
    static_reports: list[dict[str, object]],
) -> dict[str, object]:
    """Apply append candidates as one recoverable file-only transaction."""
    if not prepared:
        raise TransactionError("append transaction has no prepared files")
    seen: set[str] = set()
    for entry in prepared:
        candidate, target = Path(str(entry["candidate"])), Path(str(entry["target"]))
        key = str(target.resolve())
        if key in seen:
            raise TransactionError(f"duplicate append target: {target}")
        seen.add(key)
        if not candidate.is_file() or sha256(candidate) != entry.get("candidateSha256"):
            raise TransactionError(f"candidate hash drift: {candidate}")
        if target.exists() and sha256(target) != entry.get("targetSha256"):
            raise TransactionError(f"target hash drift: {target}")
        if not target.exists() and entry.get("targetSha256") not in (None, ""):
            raise TransactionError(f"target unexpectedly missing: {target}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    root = Path(output_root) / "transactions" / stamp
    originals = root / "original"
    originals.mkdir(parents=True, exist_ok=False)
    registered: list[dict[str, object]] = []
    for index, entry in enumerate(prepared):
        target = Path(str(entry["target"]))
        existed = target.is_file()
        backup = originals / f"{index:03d}_{target.name}"
        before = sha256(target) if existed else None
        if existed:
            shutil.copy2(target, backup)
        registered.append({
            "target": str(target), "backup": str(backup), "existed": existed,
            "before": before, "after": entry["candidateSha256"], "role": entry.get("role"),
        })
    receipt = {
        "operation": "equipment-graphics-append", "configHash": config_hash,
        "sourceHashes": source_hashes, "resourceMap": resource_map,
        "files": registered, "expectedFiles": [dict(item) for item in registered],
        "staticAppendReports": static_reports, "databaseAccess": [], "status": "registered",
    }
    receipt_path = root / "receipt.json"
    _write_receipt(receipt_path, receipt)
    try:
        for entry in prepared:
            candidate, target = Path(str(entry["candidate"])), Path(str(entry["target"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_copy(candidate, target)
            if sha256(target) != entry["candidateSha256"]:
                raise TransactionError(f"append target readback failed: {target}")
    except Exception:
        receipt["status"] = "failed-restored" if _restore_files(registered) else "failed-rollback-incomplete"
        _write_receipt(receipt_path, receipt)
        raise
    receipt["status"] = "applied"
    _write_receipt(receipt_path, receipt)
    return {"receiptPath": str(receipt_path), "status": "applied"}


def rollback_append_receipt(receipt_path: Path) -> dict[str, object]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if receipt.get("operation") != "equipment-graphics-append" or receipt.get("status") != "applied":
        raise TransactionError("only an applied append receipt may be rolled back")
    files = receipt.get("files")
    if not isinstance(files, list):
        raise TransactionError("append receipt files is invalid")
    for item in files:
        target = Path(str(item["target"]))
        if not target.is_file() or sha256(target) != item.get("after"):
            raise TransactionError(f"refuse to overwrite changed append target: {target}")
        if bool(item.get("existed")):
            backup = Path(str(item["backup"]))
            if not backup.is_file() or sha256(backup) != item.get("before"):
                raise TransactionError(f"append backup hash drift: {backup}")
    if not _restore_files(files):
        receipt["status"] = "failed-rollback-incomplete"; _write_receipt(Path(receipt_path), receipt)
        raise TransactionError("append rollback verification failed")
    receipt["status"] = "rolled-back"
    _write_receipt(Path(receipt_path), receipt)
    return {"receiptPath": str(receipt_path), "status": "rolled-back"}
