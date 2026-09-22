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
SERVER_ROOT = Path(r"D:\MirServer")
CLIENT_ROOT = Path(r"D:\11周年")
CLIENT_DATA = CLIENT_ROOT / "data"
GENERATOR_RULES = Path(r"D:\素材文件夹\LFM2[20260707]\登录器\pak.txt")
SERVER_RULES = SERVER_ROOT / "登录器" / "pak.txt"
ACTIVE_LIMIT = 60
PROMOTE = (113, 116)
DEMOTE = (105, 111)
EXPECTED_HASHES = {
    113: "97FAA547FE847B608AB43438AC9FABF97D4077BC83B4904F92E393C06D971606",
    116: "B44EFF30C87BA9B4E20E81B459F78A2E4315B5090FD3FD97C01B9D63BB3ADE81",
}
DEPRECATED_REASON = (
    "已证伪：2026-08-13 09:10 使用调整后新登录器实测，"
    "Mon113/116提升到第14/15条后仍无外观；禁止再次执行前60条假设。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把星辰怪PAK规则提升到登录器前60条有效区")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


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


def basename(line: str) -> str:
    token = line.split("|", 1)[0].strip().replace("/", "\\")
    return token.rsplit("\\", 1)[-1].casefold()


def active_ranks(lines: list[str]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    active = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        active += 1
        result.setdefault(basename(line), []).append(active)
    return result


def build_reordered(path: Path) -> tuple[bytes, dict[str, object]]:
    before = path.read_bytes()
    text, encoding, bom, newline = decode_document(before)
    had_final_newline = text.endswith(("\r\n", "\n", "\r"))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    indexes: dict[int, int] = {}
    for number in (*PROMOTE, *DEMOTE):
        matches = [index for index, line in enumerate(lines) if basename(line) == f"mon{number}.pak"]
        if len(matches) != 1:
            raise RuntimeError(f"{path}的Mon{number}规则不唯一：{matches}")
        indexes[number] = matches[0]

    before_ranks = active_ranks(lines)
    next_lines = list(lines)
    for promote, demote in zip(PROMOTE, DEMOTE, strict=True):
        promote_index = indexes[promote]
        demote_index = indexes[demote]
        next_lines[promote_index], next_lines[demote_index] = (
            next_lines[demote_index],
            next_lines[promote_index],
        )
    after_ranks = active_ranks(next_lines)

    for number in PROMOTE:
        ranks = after_ranks.get(f"mon{number}.pak", [])
        if len(ranks) != 1 or ranks[0] > ACTIVE_LIMIT:
            raise RuntimeError(f"Mon{number}未进入前{ACTIVE_LIMIT}条：{ranks}")
    for number in DEMOTE:
        ranks = after_ranks.get(f"mon{number}.pak", [])
        if len(ranks) != 1 or ranks[0] <= ACTIVE_LIMIT:
            raise RuntimeError(f"Mon{number}未移出前{ACTIVE_LIMIT}条：{ranks}")

    merged = newline.join(next_lines) + (newline if had_final_newline else "")
    encoded = bom + merged.encode(encoding)
    return encoded, {
        "path": str(path),
        "encoding": encoding,
        "active_lines": sum(len(value) for value in before_ranks.values()),
        "before": {str(number): before_ranks[f"mon{number}.pak"] for number in (*PROMOTE, *DEMOTE)},
        "after": {str(number): after_ranks[f"mon{number}.pak"] for number in (*PROMOTE, *DEMOTE)},
    }


def copy_verified(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if sha256_file(source) != sha256_file(target):
        raise RuntimeError(f"备份哈希不一致：{source}")


def write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.staging-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def running_client_processes() -> list[dict[str, object]]:
    command = (
        "$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like 'D:\\11周年\\*' };"
        "if($p){$p|Select-Object ProcessId,Name,ExecutablePath|ConvertTo-Json -Compress}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"客户端进程检查失败：{result.stderr.strip()}")
    output = result.stdout.strip()
    if not output:
        return []
    parsed = json.loads(output)
    return parsed if isinstance(parsed, list) else [parsed]


def library_reference_counts() -> dict[int, int]:
    database = SERVER_ROOT / "Mud2" / "DB" / "ApexM2.DB"
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        counts: dict[int, int] = {}
        for (appearance,) in connection.execute("SELECT Appr FROM Monster"):
            library = int(appearance) // 10 + 1
            counts[library] = counts.get(library, 0) + 1
        return counts
    finally:
        connection.close()


def verify_rule_order(path: Path) -> dict[str, int]:
    text = decode_document(path.read_bytes())[0]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ranks = active_ranks(lines)
    result: dict[str, int] = {}
    for number in (*PROMOTE, *DEMOTE):
        values = ranks.get(f"mon{number}.pak", [])
        if len(values) != 1:
            raise RuntimeError(f"{path}的Mon{number}写后规则不唯一：{values}")
        result[str(number)] = values[0]
    if any(result[str(number)] > ACTIVE_LIMIT for number in PROMOTE):
        raise RuntimeError(f"{path}的星辰规则仍在有效区外：{result}")
    if any(result[str(number)] <= ACTIVE_LIMIT for number in DEMOTE):
        raise RuntimeError(f"{path}的未使用规则仍占有效区：{result}")
    return result


def main() -> int:
    raise RuntimeError(DEPRECATED_REASON)
    args = parse_args()
    if args.apply and not args.yes:
        raise RuntimeError("正式调整必须同时提供--apply --yes")

    counts = library_reference_counts()
    referenced = {number: counts.get(number, 0) for number in DEMOTE}
    if any(referenced.values()):
        raise RuntimeError(f"候选移出规则已被Monster引用，停止：{referenced}")

    for number, expected in EXPECTED_HASHES.items():
        pak = CLIENT_DATA / f"Mon{number}.pak"
        if not pak.is_file() or sha256_file(pak) != expected:
            raise RuntimeError(f"目标Mon{number}.pak缺失或哈希变化")

    processes = running_client_processes()
    candidates: dict[Path, bytes] = {}
    plans: list[dict[str, object]] = []
    for path in (SERVER_RULES, GENERATOR_RULES):
        data, plan = build_reordered(path)
        candidates[path] = data
        plans.append(plan)

    preflight = {
        "status": "blocked-client-running" if processes else "ready-to-apply",
        "hypothesis": "当前MakeGameLogin生成链只加载pak.txt前60条有效规则；Mon113/116位于61/62，客户端未尝试加载",
        "active_limit": ACTIVE_LIMIT,
        "promote": list(PROMOTE),
        "demote": list(DEMOTE),
        "demote_database_references": referenced,
        "rule_plans": plans,
        "running_client_processes": processes,
        "database_change": False,
        "mongen_change": False,
        "pak_file_change": False,
    }
    if not args.apply:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 2 if processes else 0
    if processes:
        raise RuntimeError(f"目标客户端仍在运行，已阻止调整：{processes}")

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    transaction_id = f"{stamp}_{uuid.uuid4().hex[:8]}"
    backup_root = PLATFORM_ROOT / "怪物库" / "backups" / "star-pak-priority" / transaction_id
    snapshots = backup_root / "snapshots"
    backup_root.mkdir(parents=True, exist_ok=False)
    backups = {
        SERVER_RULES: snapshots / "server-login" / "pak.txt",
        GENERATOR_RULES: snapshots / "generator-login" / "pak.txt",
    }
    database = SERVER_ROOT / "Mud2" / "DB" / "ApexM2.DB"
    mongen = SERVER_ROOT / "Mir200" / "Envir" / "MonGen.txt"
    protected_hashes = {database: sha256_file(database), mongen: sha256_file(mongen)}

    try:
        for source, target in backups.items():
            copy_verified(source, target)
        for path, data in candidates.items():
            write_atomic(path, data)
        verification = {
            "rule_ranks": {str(path): verify_rule_order(path) for path in candidates},
            "database_hash_unchanged": sha256_file(database) == protected_hashes[database],
            "mongen_hash_unchanged": sha256_file(mongen) == protected_hashes[mongen],
            "pak_hashes": {
                str(number): sha256_file(CLIENT_DATA / f"Mon{number}.pak")
                for number in PROMOTE
            },
        }
        if not verification["database_hash_unchanged"] or not verification["mongen_hash_unchanged"]:
            raise RuntimeError("数据库或MonGen发生意外变化")
        receipt = {
            **preflight,
            "status": "deployed-awaiting-login-regeneration-and-game-validation",
            "transaction_id": transaction_id,
            "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "backup_root": str(backup_root),
            "verification": verification,
        }
        receipt_path = backup_root / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path = PLATFORM_ROOT / "怪物库" / "build" / f"{transaction_id}_星辰怪PAK前60条优先级修复.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"receipt": str(receipt_path), **receipt}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(report_path), "receipt": str(receipt_path), **receipt}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        for target, backup in backups.items():
            if backup.is_file():
                shutil.copy2(backup, target)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
