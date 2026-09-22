from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path


PLATFORM_ROOT = Path(r"D:\XuanYuanDevPlatform")
CLIENT_DATA = Path(r"D:\11周年\data")
SERVER_ROOT = Path(r"D:\MirServer")
GENERATOR_RULES = Path(r"D:\素材文件夹\LFM2[20260707]\登录器\pak.txt")
BUILD_ROOT = PLATFORM_ROOT / "怪物库" / "build" / "star-mon113-116-rebuild-20260813"
CANDIDATE_RECEIPT = BUILD_ROOT / "candidate-receipt.json"
NORMALIZED_RECEIPT = BUILD_ROOT / "normalized-Mon116" / "normalized-receipt.json"
AUDIT_ROOT = BUILD_ROOT / "audit"
LIBRARIES = (113, 116)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="事务部署星辰Mon113/116同号WZL修复")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def copy_verified(source: Path, target: Path, expected_hash: str | None = None) -> None:
    expected = expected_hash or sha256_file(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.staging-{uuid.uuid4().hex}")
    shutil.copy2(source, temporary)
    if sha256_file(temporary) != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"复制后哈希不一致：{source} -> {target}")
    os.replace(temporary, target)
    if sha256_file(target) != expected:
        raise RuntimeError(f"写后回读哈希不一致：{target}")


def decode_document(data: bytes) -> tuple[str, str, bytes, str]:
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom) :]
    for encoding in ("utf-8", "gb18030"):
        try:
            text = body.decode(encoding)
            newline = "\r\n" if "\r\n" in text else "\n"
            return text, encoding, bom, newline
        except UnicodeDecodeError:
            pass
    raise RuntimeError("pak.txt编码无法识别")


def remove_library_rules(path: Path) -> tuple[bytes, list[str]]:
    before = path.read_bytes()
    text, encoding, bom, newline = decode_document(before)
    had_final_newline = text.endswith(("\r\n", "\n", "\r"))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    removed: list[str] = []
    kept: list[str] = []
    wanted = {f"mon{number}.pak" for number in LIBRARIES}
    for line in lines:
        token = line.split("|", 1)[0].strip().replace("/", "\\")
        name = token.rsplit("\\", 1)[-1].casefold()
        if name in wanted:
            removed.append(line)
        else:
            kept.append(line)
    removed_names = [line.split("|", 1)[0].strip().replace("/", "\\").rsplit("\\", 1)[-1].casefold() for line in removed]
    for name in wanted:
        if removed_names.count(name) != 1:
            raise RuntimeError(f"{path}中{name}规则数量异常：{removed_names.count(name)}")
    merged = newline.join(kept) + (newline if had_final_newline else "")
    return bom + merged.encode(encoding), removed


def candidate_artifacts() -> dict[int, dict[str, object]]:
    candidate = json.loads(CANDIDATE_RECEIPT.read_text(encoding="utf-8"))
    normalized = json.loads(NORMALIZED_RECEIPT.read_text(encoding="utf-8"))
    if candidate.get("status") != "candidate-verified-not-deployed":
        raise RuntimeError("Mon113候选回执状态不允许部署")
    if normalized.get("status") != "normalized-candidate-verified-not-deployed":
        raise RuntimeError("Mon116规范化候选回执状态不允许部署")
    mon113 = next(item for item in candidate["results"] if int(item["library"][3:]) == 113)
    mon113_artifacts = {Path(item["fileName"]).suffix.casefold(): item for item in mon113["artifacts"]}
    result = {
        113: {
            "wzl": Path(mon113_artifacts[".wzl"]["sourcePath"]),
            "wzx": Path(mon113_artifacts[".wzx"]["sourcePath"]),
            "wzl_hash": str(mon113_artifacts[".wzl"]["sha256"]),
            "wzx_hash": str(mon113_artifacts[".wzx"]["sha256"]),
        },
        116: {
            "wzl": Path(normalized["output"]["wzl"]),
            "wzx": Path(normalized["output"]["wzx"]),
            "wzl_hash": str(normalized["output"]["wzlSha256"]),
            "wzx_hash": str(normalized["output"]["wzxSha256"]),
        },
    }
    for number, artifacts in result.items():
        for kind in ("wzl", "wzx"):
            source = artifacts[kind]
            expected = artifacts[f"{kind}_hash"]
            if not isinstance(source, Path) or not source.is_file() or sha256_file(source) != expected:
                raise RuntimeError(f"Mon{number}.{kind}候选缺失或哈希变化")
    return result


def assert_clients_stopped_and_files_exclusive() -> None:
    command = (
        "$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like 'D:\\11周年\\*' }; "
        "if($p){$p | Select-Object ProcessId,Name,ExecutablePath | ConvertTo-Json -Compress; exit 9}"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, encoding="utf-8")
    if result.returncode == 9:
        raise RuntimeError(f"目标客户端仍在运行：{result.stdout.strip()}")
    if result.returncode != 0:
        raise RuntimeError(f"客户端进程门禁执行失败：{result.stderr.strip()}")
    for number in LIBRARIES:
        pak = CLIENT_DATA / f"Mon{number}.pak"
        if not pak.is_file():
            raise RuntimeError(f"目标PAK不存在：{pak}")
        handle = os.open(pak, os.O_RDWR)
        os.close(handle)


def make_catalog_candidate(
    source_catalog: Path,
    temporary_catalog: Path,
    durable_assets: dict[int, dict[str, object]],
    durable_previews: dict[tuple[int, int], Path],
) -> None:
    shutil.copy2(source_catalog, temporary_catalog)
    connection = sqlite3.connect(temporary_catalog)
    try:
        for number, slots in ((113, range(10)), (116, range(7))):
            resource = durable_assets[number]
            for slot in slots:
                preview = durable_previews[(number, slot)]
                cursor = connection.execute(
                    """
                    UPDATE monsters SET
                        source_kind='wzl', resource_name=?, source_path=?, companion_path=?,
                        source_hash=?, companion_hash=?, source_size=?, pak_password=NULL,
                        preview_path=?, preview_state='indexed', status='ready', skip_reason=NULL
                    WHERE library_no=? AND slot_no=?
                    """,
                    (
                        f"Mon{number}.wzl", str(resource["wzl_target"]), str(resource["wzx_target"]),
                        resource["wzl_hash"], resource["wzx_hash"], resource["size"],
                        str(preview), number, slot,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"平台怪物库Mon{number}槽{slot}不是唯一记录：{cursor.rowcount}")
        invalid_reason = "供体槽不是完整360帧怪物动作，禁止进入默认随机池"
        for slot in (7, 8, 9):
            preview = durable_previews.get((116, slot))
            cursor = connection.execute(
                """
                UPDATE monsters SET preview_path=?, preview_state='invalid', status='skipped', skip_reason=?
                WHERE library_no=116 AND slot_no=?
                """,
                (str(preview) if preview else None, invalid_reason, slot),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"平台怪物库Mon116无效槽{slot}不是唯一记录：{cursor.rowcount}")
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
            ("star_mon113_116_verified_at", dt.datetime.now().isoformat(timespec="seconds")),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
            ("star_mon113_116_valid_slots", json.dumps({"113": list(range(10)), "116": list(range(7))})),
        )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError(f"平台怪物库候选完整性失败：{integrity}")
        connection.commit()
    finally:
        connection.close()


def verify_production(
    artifacts: dict[int, dict[str, object]],
    rule_paths: tuple[Path, Path],
    server_db_hash: str,
    mon_gen_hash: str,
) -> dict[str, object]:
    for number, resource in artifacts.items():
        if (CLIENT_DATA / f"Mon{number}.pak").exists():
            raise RuntimeError(f"部署后PAK仍存在：Mon{number}.pak")
        for kind in ("wzl", "wzx"):
            target = CLIENT_DATA / f"Mon{number}.{kind}"
            if not target.is_file() or sha256_file(target) != resource[f"{kind}_hash"]:
                raise RuntimeError(f"部署后回读失败：{target}")
    for path in rule_paths:
        text = decode_document(path.read_bytes())[0].casefold()
        if "mon113.pak" in text or "mon116.pak" in text:
            raise RuntimeError(f"部署后PAK规则仍残留：{path}")
    catalog = PLATFORM_ROOT / "怪物库" / "catalog.sqlite"
    connection = sqlite3.connect(catalog)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        ready = dict(connection.execute(
            "SELECT library_no,COUNT(*) FROM monsters WHERE status='ready' AND library_no IN (113,116) GROUP BY library_no"
        ))
        invalid = connection.execute(
            "SELECT COUNT(*) FROM monsters WHERE library_no=116 AND slot_no IN (7,8,9) AND status='skipped' AND preview_state='invalid'"
        ).fetchone()[0]
        indexed = connection.execute(
            "SELECT COUNT(*) FROM monsters WHERE library_no IN (113,116) AND status='ready' AND preview_state='indexed'"
        ).fetchone()[0]
    finally:
        connection.close()
    if integrity != "ok" or ready != {113: 10, 116: 7} or invalid != 3 or indexed != 17:
        raise RuntimeError(f"平台怪物库写后验证失败：integrity={integrity}, ready={ready}, invalid={invalid}, indexed={indexed}")
    server_db = SERVER_ROOT / "Mud2" / "DB" / "ApexM2.DB"
    mon_gen = SERVER_ROOT / "Mir200" / "Envir" / "MonGen.txt"
    if sha256_file(server_db) != server_db_hash or sha256_file(mon_gen) != mon_gen_hash:
        raise RuntimeError("本次客户端补丁修复意外修改了服务端数据库或MonGen")
    connection = sqlite3.connect(f"file:{server_db.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT Name,Appr FROM Monster WHERE Name GLOB '星辰怪*'").fetchall()
        db_integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if len(rows) != 19 or db_integrity != "ok":
        raise RuntimeError(f"目标Monster只读回读异常：rows={len(rows)}, integrity={db_integrity}")
    return {
        "client_wzl_pairs": 2,
        "pak_rules_removed_from": [str(item) for item in rule_paths],
        "platform_ready_models": 17,
        "platform_invalid_slots": 3,
        "server_monster_rows_unchanged": 19,
        "server_database_integrity": db_integrity,
        "server_database_hash_unchanged": True,
        "mon_gen_hash_unchanged": True,
    }


def main() -> int:
    args = parse_args()
    if args.apply and not args.yes:
        raise RuntimeError("正式部署必须同时提供--apply --yes")
    artifacts = candidate_artifacts()
    assert_clients_stopped_and_files_exclusive()
    rule_paths = (SERVER_ROOT / "登录器" / "pak.txt", GENERATOR_RULES)
    rule_candidates: dict[Path, bytes] = {}
    removed_rules: dict[str, list[str]] = {}
    for path in rule_paths:
        if not path.is_file():
            raise RuntimeError(f"PAK规则文件不存在：{path}")
        candidate, removed = remove_library_rules(path)
        rule_candidates[path] = candidate
        removed_rules[str(path)] = removed
    for number in LIBRARIES:
        for kind in ("wzl", "wzx"):
            target = CLIENT_DATA / f"Mon{number}.{kind}"
            if target.exists():
                raise RuntimeError(f"目标已存在同名资源，禁止覆盖：{target}")

    preview_sources: dict[tuple[int, int], Path] = {}
    for number, slots in ((113, range(10)), (116, range(9))):
        for slot in slots:
            source = AUDIT_ROOT / "previews" / f"Mon{number}-slot-{slot:02d}.png"
            if source.is_file():
                preview_sources[(number, slot)] = source
    missing_previews = [(number, slot) for number, slots in ((113, range(10)), (116, range(7))) for slot in slots if (number, slot) not in preview_sources]
    if missing_previews:
        raise RuntimeError(f"有效怪物槽缺少预览：{missing_previews}")

    durable_assets: dict[int, dict[str, object]] = {}
    for number, item in artifacts.items():
        folder = PLATFORM_ROOT / "怪物库" / "assets" / "wzl" / str(item["wzl_hash"])[:16]
        durable_assets[number] = {
            **item,
            "wzl_target": folder / f"Mon{number}.wzl",
            "wzx_target": folder / f"Mon{number}.wzx",
            "size": item["wzl"].stat().st_size + item["wzx"].stat().st_size,
        }
    preview_root = PLATFORM_ROOT / "怪物库" / "assets" / "previews" / "star-mon113-116-v1"
    durable_previews = {key: preview_root / value.name for key, value in preview_sources.items()}
    catalog = PLATFORM_ROOT / "怪物库" / "catalog.sqlite"
    if not catalog.is_file():
        raise RuntimeError(f"平台怪物库不存在：{catalog}")

    server_db = SERVER_ROOT / "Mud2" / "DB" / "ApexM2.DB"
    mon_gen = SERVER_ROOT / "Mir200" / "Envir" / "MonGen.txt"
    server_db_hash = sha256_file(server_db)
    mon_gen_hash = sha256_file(mon_gen)
    preflight = {
        "status": "ready-to-apply" if not args.apply else "applying",
        "client_data": str(CLIENT_DATA),
        "deploy": [
            {"target": str(CLIENT_DATA / f"Mon{number}.{kind}"), "sha256": item[f"{kind}_hash"]}
            for number, item in artifacts.items() for kind in ("wzl", "wzx")
        ],
        "quarantine_paks": [str(CLIENT_DATA / f"Mon{number}.pak") for number in LIBRARIES],
        "remove_rules": removed_rules,
        "platform_valid_slots": {"113": list(range(10)), "116": list(range(7))},
        "platform_invalid_slots": {"116": [7, 8, 9]},
        "server_database_change": False,
        "mon_gen_change": False,
    }
    if not args.apply:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    transaction_id = f"{stamp}_{uuid.uuid4().hex[:8]}"
    backup_root = PLATFORM_ROOT / "怪物库" / "backups" / "star-mon113-116-wzl-fix" / transaction_id
    backup_root.mkdir(parents=True, exist_ok=False)
    snapshots = backup_root / "snapshots"
    removed_root = backup_root / "removed-client-paks"
    created_targets: list[Path] = []
    created_assets: list[Path] = []
    moved_paks: list[tuple[Path, Path]] = []
    try:
        backup_map = {
            CLIENT_DATA / "Mon113.pak": snapshots / "client-data" / "Mon113.pak",
            CLIENT_DATA / "Mon116.pak": snapshots / "client-data" / "Mon116.pak",
            rule_paths[0]: snapshots / "server-login" / "pak.txt",
            rule_paths[1]: snapshots / "generator-login" / "pak.txt",
            catalog: snapshots / "platform" / "catalog.sqlite",
        }
        for source, target in backup_map.items():
            copy_verified(source, target)
            if sha256_file(source) != sha256_file(target):
                raise RuntimeError(f"备份哈希不一致：{source}")

        for number, resource in durable_assets.items():
            for kind in ("wzl", "wzx"):
                source = resource[kind]
                target = resource[f"{kind}_target"]
                expected = resource[f"{kind}_hash"]
                if target.exists():
                    if sha256_file(target) != expected:
                        raise RuntimeError(f"平台素材同名异内容：{target}")
                else:
                    copy_verified(source, target, expected)
                    created_assets.append(target)
        for key, source in preview_sources.items():
            target = durable_previews[key]
            expected = sha256_file(source)
            if target.exists():
                if sha256_file(target) != expected:
                    raise RuntimeError(f"平台预览同名异内容：{target}")
            else:
                copy_verified(source, target, expected)
                created_assets.append(target)

        catalog_candidate = catalog.with_name(f".{catalog.name}.staging-{uuid.uuid4().hex}")
        make_catalog_candidate(catalog, catalog_candidate, durable_assets, durable_previews)

        for number, resource in artifacts.items():
            for kind in ("wzl", "wzx"):
                target = CLIENT_DATA / f"Mon{number}.{kind}"
                copy_verified(resource[kind], target, resource[f"{kind}_hash"])
                created_targets.append(target)

        for number in LIBRARIES:
            source = CLIENT_DATA / f"Mon{number}.pak"
            target = removed_root / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            moved_paks.append((source, target))

        for path, data in rule_candidates.items():
            temporary = path.with_name(f".{path.name}.staging-{uuid.uuid4().hex}")
            temporary.write_bytes(data)
            os.replace(temporary, path)
        os.replace(catalog_candidate, catalog)

        verification = verify_production(artifacts, rule_paths, server_db_hash, mon_gen_hash)
        receipt = {
            **preflight,
            "status": "deployed-awaiting-login-regeneration-and-game-validation",
            "transaction_id": transaction_id,
            "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "backup_root": str(backup_root),
            "artifacts": [
                {"path": str(CLIENT_DATA / f"Mon{number}.{kind}"), "sha256": item[f"{kind}_hash"]}
                for number, item in artifacts.items() for kind in ("wzl", "wzx")
            ],
            "verification": verification,
        }
        receipt_path = backup_root / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path = BUILD_ROOT / f"{transaction_id}_deployment.json"
        report_path.write_text(json.dumps({"receipt": str(receipt_path), **receipt}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(report_path), "receipt": str(receipt_path), **receipt}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        for path, backup in (
            (rule_paths[0], snapshots / "server-login" / "pak.txt"),
            (rule_paths[1], snapshots / "generator-login" / "pak.txt"),
            (catalog, snapshots / "platform" / "catalog.sqlite"),
        ):
            if backup.is_file():
                copy_verified(backup, path)
        for path in reversed(created_targets):
            path.unlink(missing_ok=True)
        for source, moved in reversed(moved_paks):
            if moved.is_file() and not source.exists():
                os.replace(moved, source)
        for path in reversed(created_assets):
            path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
