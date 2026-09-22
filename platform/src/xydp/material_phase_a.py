from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLATFORM_ROOT = Path(__file__).resolve().parents[2]
PROVIDER = PLATFORM_ROOT / "玄渊界面施工台" / "vendor" / "wzl-provider" / "v1" / "XuanYuanWzlProvider.exe"
BACKUP_ROOT = PLATFORM_ROOT / "backups" / "material-phase-a"
LOG_ROOT = PLATFORM_ROOT / "logs" / "material-phase-a"
PROTECTED_IDXS = (793, 794, 802)
RESERVED_RANGE = tuple(range(972, 984))
IMPORT_RANGE = tuple(range(907, 972))


class MaterialPhaseAError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MaterialPhaseAError(f"无法读取JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MaterialPhaseAError(f"JSON根节点必须是对象：{path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_icon_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    manifest_path = Path(manifest_path).resolve()
    raw = _load_json(manifest_path).get("materials")
    if not isinstance(raw, list):
        raise MaterialPhaseAError("图标清单缺少 materials 数组")
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MaterialPhaseAError("图标清单材料项必须是对象")
        idx = int(item.get("idx", item.get("actualIdx", -1)))
        library = str(item.get("library", "Items"))
        if library != "Items":
            raise MaterialPhaseAError(f"材料只允许写入 Items 图库：Idx={idx}, library={library}")
        raw_icon = Path(str(item.get("icon", "")))
        icon = raw_icon if raw_icon.is_absolute() else manifest_path.parent / raw_icon
        if not icon.is_file():
            raise MaterialPhaseAError(f"材料图标不存在：Idx={idx}, {icon}")
        rows.append({**item, "idx": idx, "name": str(item.get("name", "")).strip(), "library": library, "iconPath": str(icon.resolve())})
    if [row["idx"] for row in rows] != list(IMPORT_RANGE):
        raise MaterialPhaseAError("图标清单必须按 907-971 连续、升序且恰好 65 项")
    if any(not row["name"] for row in rows) or len({row["name"] for row in rows}) != 65:
        raise MaterialPhaseAError("材料名称必须非空且 65 项互不重复")
    if len({_sha256(Path(row["iconPath"])) for row in rows}) != 65:
        raise MaterialPhaseAError("65 个材料图标存在逐字节重复")
    return rows


def _provider(command: str, arguments: dict[str, Any], allowed_roots: list[Path] | None = None, timeout: int = 300) -> dict[str, Any]:
    if not PROVIDER.is_file():
        raise MaterialPhaseAError(f"WZL Provider 不存在：{PROVIDER}")
    request = {
        "schemaVersion": 1,
        "requestId": f"xymi-{uuid.uuid4().hex}",
        "command": command,
        "arguments": arguments,
        "policy": {"allowedWriteRoots": [str(path.resolve()) for path in (allowed_roots or [])]},
    }
    result = subprocess.run(
        [str(PROVIDER), "run", "--request-json", json.dumps(request, ensure_ascii=False)],
        cwd=str(PROVIDER.parent), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    output = result.stdout.strip()
    try:
        envelope = json.loads(output)
    except Exception as exc:
        raise MaterialPhaseAError(f"WZL Provider 返回非JSON：{result.stderr[-1000:]}") from exc
    if result.returncode != 0 or not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise MaterialPhaseAError(f"WZL Provider {command} 失败：{error.get('code')} {error.get('message')}")
    return envelope.get("data") or {}


def _pair_state(data_dir: Path) -> dict[str, Any]:
    wzl, wzx = data_dir / "Items.wzl", data_dir / "Items.wzx"
    if not wzl.is_file() or not wzx.is_file():
        raise MaterialPhaseAError(f"Items.wzl/.wzx 必须成对存在：{data_dir}")
    inspected = _provider("inspect", {"wzl": str(wzl), "wzx": str(wzx)})
    return {"wzl": str(wzl), "wzx": str(wzx), "wzlSha256": _sha256(wzl), "wzxSha256": _sha256(wzx), "count": int(inspected["count"])}


def preflight_icons(manifest_path: Path, data_dir: Path) -> dict[str, Any]:
    rows = validate_icon_manifest(manifest_path)
    before = _pair_state(Path(data_dir).resolve())
    return {
        "status": "preflight_ok", "operation": "material_icon_items_only", "count": len(rows),
        "targetLibrary": "Items", "untouchedLibraries": ["DnItems", "StateItem"],
        "expectedLooksRange": [before["count"], before["count"] + len(rows) - 1], "beforePair": before,
    }


def _pixel_bytes(path: Path) -> bytes:
    from PIL import Image
    # Provider 的 type6 回读会把 PNG alpha 预乘到黑底 RGB，并以黑色作为客户端透明键；
    # 因此比较客户端实际可见像素，而不是比较容器层 alpha 字节。
    image = Image.open(path).convert("RGBA")
    black = Image.new("RGBA", image.size, (0, 0, 0, 255))
    return Image.alpha_composite(black, image).convert("RGB").tobytes()


def apply_icon_transaction(manifest_path: Path, data_dir: Path) -> dict[str, Any]:
    manifest_path, data_dir = Path(manifest_path).resolve(), Path(data_dir).resolve()
    rows = validate_icon_manifest(manifest_path)
    before = _pair_state(data_dir)
    transaction_id = f"XYMI-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
    tx_root = BACKUP_ROOT / transaction_id
    backup = tx_root / "backup"
    staging = tx_root / "staging"
    provider_backups = tx_root / "provider-backups"
    readback = tx_root / "readback"
    for path in (backup, staging, provider_backups, readback):
        path.mkdir(parents=True, exist_ok=True)
    live_wzl, live_wzx = data_dir / "Items.wzl", data_dir / "Items.wzx"
    backup_wzl, backup_wzx = backup / "Items.wzl", backup / "Items.wzx"
    stage_wzl, stage_wzx = staging / "Items.wzl", staging / "Items.wzx"
    for source, backup_file, stage_file in ((live_wzl, backup_wzl, stage_wzl), (live_wzx, backup_wzx, stage_wzx)):
        shutil.copy2(source, backup_file)
        shutil.copy2(source, stage_file)
    appended: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        expected = before["count"] + offset
        result = _provider("append", {
            "wzl": str(stage_wzl), "wzx": str(stage_wzx), "image": row["iconPath"],
            "backupRoot": str(provider_backups / f"{expected}"),
        }, [tx_root])
        actual = int(result.get("image_id", result.get("imageId", -1)))
        if actual != expected or not result.get("readback", {}).get("ok"):
            raise MaterialPhaseAError(f"staging 追加编号异常：期望 {expected}，实际 {actual}")
        target = result.get("targetEntry") or {}
        if int(target.get("width", -1)) != 48 or int(target.get("height", -1)) != 48:
            raise MaterialPhaseAError(f"staging 回读尺寸异常：Idx={row['idx']}, Looks={actual}")
        appended.append({"idx": row["idx"], "name": row["name"], "looks": actual, "sourceIconSha256": _sha256(Path(row["iconPath"]))})
    staged = {"wzlSha256": _sha256(stage_wzl), "wzxSha256": _sha256(stage_wzx)}
    if _pair_state(data_dir) != before:
        raise MaterialPhaseAError("正式 Items 图库在预检后发生变化，事务已停止")
    temp_wzl, temp_wzx = data_dir / f"Items.wzl.{transaction_id}.tmp", data_dir / f"Items.wzx.{transaction_id}.tmp"
    try:
        shutil.copy2(stage_wzl, temp_wzl)
        shutil.copy2(stage_wzx, temp_wzx)
        os.replace(temp_wzl, live_wzl)
        os.replace(temp_wzx, live_wzx)
    except Exception as exc:
        for temp_path in (temp_wzl, temp_wzx):
            temp_path.unlink(missing_ok=True)
        shutil.copy2(backup_wzl, live_wzl)
        shutil.copy2(backup_wzx, live_wzx)
        raise MaterialPhaseAError(f"Items 正式提交失败，已恢复施工前双文件：{exc}") from exc
    after = _pair_state(data_dir)
    if after["count"] != before["count"] + 65 or after["wzlSha256"] != staged["wzlSha256"] or after["wzxSha256"] != staged["wzxSha256"]:
        shutil.copy2(backup_wzl, live_wzl)
        shutil.copy2(backup_wzx, live_wzx)
        raise MaterialPhaseAError("Items 正式回读不一致，已逐字节恢复")
    for item, row in zip(appended, rows, strict=True):
        exported = _provider("export", {
            "wzl": str(live_wzl), "wzx": str(live_wzx), "id": item["looks"], "output": str(readback / str(item["looks"])),
        }, [readback])
        png = Path(str(exported.get("png_path") or ""))
        if not png.is_file() or _pixel_bytes(png) != _pixel_bytes(Path(row["iconPath"])):
            shutil.copy2(backup_wzl, live_wzl)
            shutil.copy2(backup_wzx, live_wzx)
            raise MaterialPhaseAError(f"Looks={item['looks']} 图像逐像素回读失败，已恢复")
        item["readbackPng"] = str(png)
        item["readbackPngSha256"] = _sha256(png)
        item["readbackOk"] = True
    receipt = {
        "schemaVersion": 1, "transactionId": transaction_id, "status": "committed_verified",
        "operation": "material_icon_items_only", "createdAt": _now(), "manifest": str(manifest_path),
        "targetData": str(data_dir), "beforePair": before, "afterPair": after,
        "looksRange": [appended[0]["looks"], appended[-1]["looks"]], "count": len(appended),
        "untouchedLibraries": ["DnItems", "StateItem"], "backup": str(backup), "readbacks": appended,
    }
    receipt_path = LOG_ROOT / f"{transaction_id}.json"
    _write_json(receipt_path, receipt)
    receipt["receiptPath"] = str(receipt_path)
    return receipt


def _rows_as_dicts(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def preflight_database(database: Path, materials: list[dict[str, Any]]) -> dict[str, Any]:
    database = Path(database).resolve()
    if not database.is_file():
        raise MaterialPhaseAError(f"数据库不存在：{database}")
    idxs = [int(item.get("idx", item.get("actualIdx", -1))) for item in materials]
    names = [str(item.get("name", "")).strip() for item in materials]
    looks = [int(item.get("looks", -1)) for item in materials]
    if idxs != list(IMPORT_RANGE) or len(set(names)) != 65 or any(not name for name in names) or len(set(looks)) != 65:
        raise MaterialPhaseAError("数据库材料必须为 907-971 连续 65 项，且名称和 Looks 唯一")
    connection = sqlite3.connect(database)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(StdItems)")]
        if not columns:
            raise MaterialPhaseAError("数据库缺少 StdItems")
        occupied_import = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx BETWEEN 907 AND 971 ORDER BY Idx")
        occupied_reserved = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx BETWEEN 972 AND 983 ORDER BY Idx")
        duplicate_names = _rows_as_dicts(connection, f"SELECT Idx,Name FROM StdItems WHERE Name IN ({','.join('?' for _ in names)})", tuple(names))
        protected = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx IN (793,794,802) ORDER BY Idx")
    finally:
        connection.close()
    if occupied_import:
        raise MaterialPhaseAError(f"907-971 已被占用：{[row['Idx'] for row in occupied_import]}")
    if occupied_reserved:
        raise MaterialPhaseAError(f"预留位 972-983 已被占用：{[row['Idx'] for row in occupied_reserved]}")
    if duplicate_names:
        raise MaterialPhaseAError(f"材料名称已存在：{[row['Name'] for row in duplicate_names]}")
    if [int(row["Idx"]) for row in protected] != list(PROTECTED_IDXS):
        raise MaterialPhaseAError("三种保护材料 793/794/802 不完整")
    return {
        "status": "preflight_ok", "database": str(database), "databaseSha256": _sha256(database),
        "pendingCount": 65, "idxRange": [907, 971], "protectedIdx": list(PROTECTED_IDXS),
        "reservedRange": [972, 983], "columns": columns, "protectedRows": protected,
    }


def validate_database_manifest(path: Path) -> list[dict[str, Any]]:
    raw = _load_json(Path(path).resolve()).get("materials")
    if not isinstance(raw, list):
        raise MaterialPhaseAError("数据库清单缺少 materials 数组")
    return [{**item, "idx": int(item.get("idx", item.get("actualIdx", -1)))} for item in raw if int(item.get("idx", item.get("actualIdx", -1))) in IMPORT_RANGE]


def apply_database_transaction(manifest_path: Path, database: Path) -> dict[str, Any]:
    manifest_path, database = Path(manifest_path).resolve(), Path(database).resolve()
    materials = validate_database_manifest(manifest_path)
    before = preflight_database(database, materials)
    transaction_id = f"XYMD-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
    tx_root = BACKUP_ROOT / transaction_id
    backup_dir, staging_dir = tx_root / "backup", tx_root / "staging"
    backup_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    backup_db, stage_db = backup_dir / database.name, staging_dir / database.name
    shutil.copy2(database, backup_db)
    shutil.copy2(database, stage_db)
    connection = sqlite3.connect(stage_db)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(StdItems)")]
        placeholders = ",".join("?" for _ in columns)
        for item in materials:
            template_idx = int(item.get("templateIdx", 793))
            template = connection.execute("SELECT * FROM StdItems WHERE Idx=?", (template_idx,)).fetchone()
            if template is None:
                raise MaterialPhaseAError(f"模板材料不存在：{template_idx}")
            row = dict(zip(columns, template))
            overrides = {
                "Idx": item["idx"], "Name": str(item["name"]), "StdMode": 46, "Shape": 1,
                "Weight": int(item.get("weight", item.get("templateFields", {}).get("weight", 0))),
                "Anicount": 0, "Source": 0, "Reserved": 0, "Looks": int(item["looks"]),
                "DuraMax": 99999, "Need": 0, "NeedLevel": 0, "Price": 0, "Stock": 5,
                "Color": int(item.get("colorValue", 251)), "OverLap": 2,
            }
            row.update({key: value for key, value in overrides.items() if key in row})
            connection.execute(f"INSERT INTO StdItems ({','.join(columns)}) VALUES ({placeholders})", tuple(row[column] for column in columns))
        connection.commit()
        check = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx BETWEEN 907 AND 971 ORDER BY Idx")
        reserved = _rows_as_dicts(connection, "SELECT Idx FROM StdItems WHERE Idx BETWEEN 972 AND 983")
        protected_after = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx IN (793,794,802) ORDER BY Idx")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if len(check) != 65 or reserved or protected_after != before["protectedRows"] or integrity != "ok":
        raise MaterialPhaseAError("staging 数据库回读门禁失败")
    if _sha256(database) != before["databaseSha256"]:
        raise MaterialPhaseAError("正式数据库在预检后发生变化，事务已停止")
    temp_db = database.with_name(f"{database.name}.{transaction_id}.tmp")
    try:
        shutil.copy2(stage_db, temp_db)
        os.replace(temp_db, database)
    except Exception as exc:
        temp_db.unlink(missing_ok=True)
        shutil.copy2(backup_db, database)
        raise MaterialPhaseAError(f"数据库提交失败，已逐字节恢复：{exc}") from exc
    connection = sqlite3.connect(database)
    try:
        installed = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx BETWEEN 907 AND 971 ORDER BY Idx")
        protected_live = _rows_as_dicts(connection, "SELECT * FROM StdItems WHERE Idx IN (793,794,802) ORDER BY Idx")
        reserved_live = _rows_as_dicts(connection, "SELECT Idx FROM StdItems WHERE Idx BETWEEN 972 AND 983")
        integrity_live = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if len(installed) != 65 or protected_live != before["protectedRows"] or reserved_live or integrity_live != "ok":
        shutil.copy2(backup_db, database)
        raise MaterialPhaseAError("正式数据库回读失败，已逐字节恢复")
    receipt = {
        "schemaVersion": 1, "transactionId": transaction_id, "status": "committed_verified",
        "operation": "material_database_only", "createdAt": _now(), "manifest": str(manifest_path),
        "database": str(database), "beforeSha256": before["databaseSha256"], "afterSha256": _sha256(database),
        "count": 65, "idxRange": [907, 971], "protectedIdx": list(PROTECTED_IDXS),
        "reservedRange": [972, 983], "backup": str(backup_db), "installedRows": installed,
    }
    receipt_path = LOG_ROOT / f"{transaction_id}.json"
    _write_json(receipt_path, receipt)
    receipt["receiptPath"] = str(receipt_path)
    return receipt


def rollback(receipt_path: Path) -> dict[str, Any]:
    receipt_path = Path(receipt_path).resolve()
    receipt = _load_json(receipt_path)
    operation = receipt.get("operation")
    if operation == "material_icon_items_only":
        data_dir = Path(receipt["targetData"])
        current = _pair_state(data_dir)
        after = receipt["afterPair"]
        if current["wzlSha256"] != after["wzlSha256"] or current["wzxSha256"] != after["wzxSha256"]:
            raise MaterialPhaseAError("当前 Items 图库已发生变化，拒绝回滚覆盖")
        backup = Path(receipt["backup"])
        shutil.copy2(backup / "Items.wzl", data_dir / "Items.wzl")
        shutil.copy2(backup / "Items.wzx", data_dir / "Items.wzx")
        restored = _pair_state(data_dir)
        expected = receipt["beforePair"]
        ok = restored["wzlSha256"] == expected["wzlSha256"] and restored["wzxSha256"] == expected["wzxSha256"]
    elif operation == "material_database_only":
        database = Path(receipt["database"])
        if _sha256(database) != receipt["afterSha256"]:
            raise MaterialPhaseAError("当前数据库已发生变化，拒绝回滚覆盖")
        shutil.copy2(Path(receipt["backup"]), database)
        restored = {"databaseSha256": _sha256(database)}
        ok = restored["databaseSha256"] == receipt["beforeSha256"]
    else:
        raise MaterialPhaseAError(f"不支持的回滚操作：{operation}")
    if not ok:
        raise MaterialPhaseAError("逐字节回滚校验失败")
    return {"status": "rolled_back_verified", "transactionId": receipt["transactionId"], "restored": restored}


def _main() -> int:
    parser = argparse.ArgumentParser(description="玄渊平台 65 材料双事务接口")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("icon-preflight", "icon-apply"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--manifest", required=True, type=Path)
        cmd.add_argument("--client-data", required=True, type=Path)
    for name in ("db-preflight", "db-apply"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--manifest", required=True, type=Path)
        cmd.add_argument("--database", required=True, type=Path)
    rb = commands.add_parser("rollback")
    rb.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "icon-preflight":
            result = preflight_icons(args.manifest, args.client_data)
        elif args.command == "icon-apply":
            result = apply_icon_transaction(args.manifest, args.client_data)
        elif args.command == "db-preflight":
            rows = validate_database_manifest(args.manifest)
            result = preflight_database(args.database, rows)
        elif args.command == "db-apply":
            result = apply_database_transaction(args.manifest, args.database)
        else:
            result = rollback(args.receipt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
