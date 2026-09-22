from __future__ import annotations

import argparse
import configparser
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path


PLATFORM_ROOT = Path(r"D:\XuanYuanDevPlatform")
DEFAULT_DONOR_SERVER = Path(r"D:\MirServer10")
DEFAULT_DONOR_CLIENT = Path(r"D:\星辰剑歌")
DEFAULT_SERVER_ROOT = Path(r"D:\MirServer")
DEFAULT_TARGET_DATA = Path(r"D:\11周年\data")
DEFAULT_CANDIDATE_ROOT = (
    PLATFORM_ROOT / "怪物库" / "simulation" / "20260813_star10_smartmonster" / "candidate"
)
DEFAULT_BACKUP_ROOT = PLATFORM_ROOT / "怪物库" / "backups" / "star10-smartmonster"
DEFAULT_REPORT_ROOT = PLATFORM_ROOT / "怪物库" / "build" / "star10-smartmonster"

SOURCE_MONSTER = "祖玛雕像"
TARGET_MONSTER = "星辰怪10"
SOURCE_EFFECT_INDEX = 78
SOURCE_RESOURCE_ENTRY = "Mon7.wzl"
TARGET_RESOURCE_STEM = "XY_StarMon10"
TARGET_RESOURCE_ENTRY = f"{TARGET_RESOURCE_STEM}.wzl"
EXPECTED_SOURCE_HASHES = {
    "ini": "EADB5192B9114805694192B61641AA41B29C259B4FC30BE9D687ED8EA29B595A",
    "wzl": "16B52DDBD6F206DCA6D9F2503C8936D7E9936342CE7A76BEE539847CE4491ED0",
    "wzx": "FD7D786DF5A38AD59A8320D175549FD79B445CC4D8F282C98499FA0B6D408365",
}
EXPECTED_TARGET_MODEL = {"Race": 156, "RaceImg": 156, "Appr": 1120}
RESOURCE_KEYS = {
    "HPFile",
    "ActionFile",
    "EffectFile",
    "EffectFile2",
    "Fly_File",
    "FlyEff_File",
    "Self_File",
    "SelfKeep_File",
    "Explosion_File",
    "Target_File",
}
ALLOWED_MONSTER_FRAME_TYPES = {259, 261}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="星辰怪10 SmartMonster完整动作链：默认构建隔离候选并只读预检"
    )
    parser.add_argument("--apply", action="store_true", help="事务部署单怪候选")
    parser.add_argument("--rollback", metavar="TRANSACTION_ID", help="逐字节回滚指定事务")
    parser.add_argument("--yes", action="store_true", help="确认写操作")
    parser.add_argument("--donor-server", type=Path, default=DEFAULT_DONOR_SERVER)
    parser.add_argument("--donor-client", type=Path, default=DEFAULT_DONOR_CLIENT)
    parser.add_argument("--server-root", type=Path, default=DEFAULT_SERVER_ROOT)
    parser.add_argument("--target-data", type=Path, default=DEFAULT_TARGET_DATA)
    parser.add_argument("--candidate-root", type=Path, default=DEFAULT_CANDIDATE_ROOT)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--skip-process-check", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def file_evidence(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.staging-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_copy(source: Path, target: Path, expected_hash: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.staging-{uuid.uuid4().hex}")
    shutil.copy2(source, temporary)
    if sha256_file(temporary) != expected_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"暂存复制哈希不一致：{source}")
    os.replace(temporary, target)
    if sha256_file(target) != expected_hash:
        raise RuntimeError(f"提交后哈希不一致：{target}")


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.staging-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    if sha256_file(temporary) != sha256_bytes(data):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"暂存文本哈希不一致：{target}")
    os.replace(temporary, target)
    if sha256_file(target) != sha256_bytes(data):
        raise RuntimeError(f"文本提交后哈希不一致：{target}")


def source_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "ini": args.donor_server / "Mir200" / "Envir" / "SmartMonster" / f"{SOURCE_MONSTER}.ini",
        "effect_list": args.donor_server / "Mir200" / "Envir" / "EffectImageList.txt",
        "wzl": args.donor_client / "Data" / f"{SOURCE_RESOURCE_ENTRY}",
        "wzx": args.donor_client / "Data" / f"{Path(SOURCE_RESOURCE_ENTRY).stem}.wzx",
    }


def target_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "database": args.server_root / "Mud2" / "DB" / "ApexM2.DB",
        "mon_gen": args.server_root / "Mir200" / "Envir" / "MonGen.txt",
        "effect_list": args.server_root / "Mir200" / "Envir" / "EffectImageList.txt",
        "smart_dir": args.server_root / "Mir200" / "Envir" / "SmartMonster",
        "ini": args.server_root / "Mir200" / "Envir" / "SmartMonster" / f"{TARGET_MONSTER}.ini",
        "wzl": args.target_data / f"{TARGET_RESOURCE_STEM}.wzl",
        "wzx": args.target_data / f"{TARGET_RESOURCE_STEM}.wzx",
        "m2": args.server_root / "Mir200" / "M2Server.exe",
    }


def detect_text(data: bytes, path: Path) -> tuple[str, str, bytes, str]:
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom):]
    for encoding in ("utf-8", "gb18030"):
        try:
            text = body.decode(encoding)
            newline = "\r\n" if body.count(b"\r\n") >= body.count(b"\n") / 2 else "\n"
            return text, encoding, bom, newline
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"文本编码无法识别：{path}")


def effect_list_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"EffectImageList不存在：{path}")
    raw = path.read_bytes()
    text, encoding, bom, newline = detect_text(raw, path)
    lines = text.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise RuntimeError("EffectImageList包含空行；当前迁移器要求连续物理行以保证零基编号稳定")
    folded = [line.strip().casefold() for line in lines]
    matches = [index for index, value in enumerate(folded) if value == TARGET_RESOURCE_ENTRY.casefold()]
    if len(matches) > 1:
        raise RuntimeError(f"EffectImageList重复登记{TARGET_RESOURCE_ENTRY}：{matches}")
    target_index = matches[0] if matches else len(lines)
    if matches:
        after_raw = raw
    else:
        normalized = newline.join(lines) + newline + TARGET_RESOURCE_ENTRY + newline
        after_raw = bom + normalized.encode(encoding)
    return {
        "path": str(path),
        "raw": raw,
        "sha256": sha256_bytes(raw),
        "encoding": encoding,
        "bom": bom,
        "newline": newline,
        "lines": lines,
        "entry_matches": matches,
        "target_index": target_index,
        "after_raw": after_raw,
        "after_sha256": sha256_bytes(after_raw),
    }


def validate_source_identity(args: argparse.Namespace) -> dict[str, object]:
    paths = source_paths(args)
    for key in ("ini", "effect_list", "wzl", "wzx"):
        if not paths[key].is_file():
            raise RuntimeError(f"供体文件不存在：{paths[key]}")
    evidence = {key: file_evidence(paths[key]) for key in ("ini", "wzl", "wzx")}
    for key, expected in EXPECTED_SOURCE_HASHES.items():
        if evidence[key]["sha256"] != expected:
            raise RuntimeError(f"供体{key}哈希漂移：{evidence[key]}")
    effect_raw = paths["effect_list"].read_bytes()
    effect_text, _, _, _ = detect_text(effect_raw, paths["effect_list"])
    effect_lines = effect_text.splitlines()
    if SOURCE_EFFECT_INDEX >= len(effect_lines):
        raise RuntimeError(f"供体EffectImageList没有零基索引{SOURCE_EFFECT_INDEX}")
    resolved = effect_lines[SOURCE_EFFECT_INDEX].strip()
    if resolved.casefold() != SOURCE_RESOURCE_ENTRY.casefold():
        raise RuntimeError(
            f"供体ActionFile={SOURCE_EFFECT_INDEX}当前解析为{resolved}，预期{SOURCE_RESOURCE_ENTRY}"
        )
    return {
        "files": evidence,
        "effect_list": file_evidence(paths["effect_list"]),
        "zero_based_action_file": SOURCE_EFFECT_INDEX,
        "resolved_resource": resolved,
    }


def parse_ini(text: str) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    parser.read_file(io.StringIO(text))
    return parser


def validate_basic_melee_policy(parser: configparser.RawConfigParser) -> dict[str, object]:
    if parser.get("ServerAttack0", "AttackEnabled", fallback="") != "1":
        raise RuntimeError("供体ServerAttack0不是唯一基础攻击入口")
    if parser.get("ServerAttack0", "AttackMode", fallback="") != "0":
        raise RuntimeError("供体ServerAttack0不是普通近战模式")
    for index in range(1, 6):
        if parser.get(f"ServerAttack{index}", "AttackEnabled", fallback="") != "0":
            raise RuntimeError(f"供体ServerAttack{index}启用了额外攻击，停止只迁外观")
    enabled_additionals = []
    call_rates = []
    protect_flags = []
    for section in parser.sections():
        for key, value in parser.items(section):
            if section.startswith("Additionals") and key.startswith("Checked") and value != "0":
                enabled_additionals.append(f"{section}.{key}={value}")
            if section.startswith("CallMonster") and key == "CallMonstersRate" and value != "0":
                call_rates.append(f"{section}.{key}={value}")
            if section.startswith("Protect") and key in {
                "ProtectAddHP", "ProtectAddDefence", "ProtectAddMagDefence",
                "ProtectAddDC", "ProtectAddMC", "ProtectAddSC",
            } and value != "0":
                protect_flags.append(f"{section}.{key}={value}")
    if enabled_additionals or call_rates or protect_flags:
        raise RuntimeError(
            f"供体INI含特殊服务端能力：{enabled_additionals + call_rates + protect_flags}"
        )
    return {
        "server_attack_policy": "仅ServerAttack0基础近战启用",
        "additional_statuses": 0,
        "summon_attacks": 0,
        "protect_buffs": 0,
    }


def build_candidate_ini(source: Path, target_index: int) -> tuple[bytes, dict[str, object]]:
    raw = source.read_bytes()
    text, encoding, bom, newline = detect_text(raw, source)
    parser = parse_ini(text)
    policy = validate_basic_melee_policy(parser)
    action_values: list[int] = []
    unexpected_refs: list[str] = []
    for section in parser.sections():
        for key, value in parser.items(section):
            if key not in RESOURCE_KEYS:
                continue
            try:
                number = int(value)
            except ValueError as exc:
                raise RuntimeError(f"{section}.{key}不是整数：{value}") from exc
            if key == "ActionFile":
                action_values.append(number)
                if number != SOURCE_EFFECT_INDEX:
                    unexpected_refs.append(f"{section}.{key}={number}")
            elif number >= 0:
                unexpected_refs.append(f"{section}.{key}={number}")
    if not action_values or unexpected_refs:
        raise RuntimeError(f"供体INI存在未纳入的资源依赖：{unexpected_refs}")
    output_lines: list[str] = []
    replaced = 0
    for line in text.splitlines():
        if line.strip() == f"ActionFile={SOURCE_EFFECT_INDEX}":
            output_lines.append(f"ActionFile={target_index}")
            replaced += 1
        else:
            output_lines.append(line)
    if replaced != len(action_values):
        raise RuntimeError(f"ActionFile重写数量异常：{replaced}/{len(action_values)}")
    candidate_text = newline.join(output_lines) + newline
    candidate = bom + candidate_text.encode(encoding)
    candidate_parser = parse_ini(candidate_text)
    rewritten = sorted(
        {
            int(candidate_parser.get(section, "ActionFile"))
            for section in candidate_parser.sections()
            if candidate_parser.has_option(section, "ActionFile")
        }
    )
    if rewritten != [target_index]:
        raise RuntimeError(f"候选INI仍有错误ActionFile：{rewritten}")
    return candidate, {
        "source_action_file": SOURCE_EFFECT_INDEX,
        "target_action_file": target_index,
        "rewritten_occurrences": replaced,
        "encoding": encoding,
        "newline": "CRLF" if newline == "\r\n" else "LF",
        **policy,
    }


def validate_action_frames(ini_bytes: bytes, wzl_path: Path, wzx_path: Path) -> dict[str, object]:
    text, _, _, _ = detect_text(ini_bytes, Path("candidate.ini"))
    parser = parse_ini(text)
    wzl = wzl_path.read_bytes()
    wzx = wzx_path.read_bytes()
    if len(wzx) < 48 or (len(wzx) - 48) % 4:
        raise RuntimeError("供体WZX索引表结构异常")
    declared = int.from_bytes(wzx[44:48], "little")
    table_count = (len(wzx) - 48) // 4
    count = min(declared, table_count) if declared else table_count
    offsets = [int.from_bytes(wzx[48 + i * 4:52 + i * 4], "little") for i in range(count)]
    actions: list[dict[str, object]] = []
    for section in parser.sections():
        if not section.startswith("Act"):
            continue
        start = parser.getint(section, "StartIndex", fallback=-1)
        play = parser.getint(section, "PlayCount", fallback=0)
        empty = parser.getint(section, "EmptyCount", fallback=0)
        calc_dir = parser.getint(section, "CalcDir", fallback=0)
        if start < 0 or play <= 0:
            continue
        directions = 8 if calc_dir == 1 else 1
        stride = play + empty
        indices = [start + direction * stride + frame for direction in range(directions) for frame in range(play)]
        if max(indices) >= count:
            raise RuntimeError(f"{section}动作帧越界：max={max(indices)}, count={count}")
        frame_types: set[int] = set()
        for index in indices:
            offset = offsets[index]
            if offset <= 0 or offset + 2 > len(wzl):
                raise RuntimeError(f"{section}动作帧为空或偏移越界：index={index}, offset={offset}")
            frame_types.add(int.from_bytes(wzl[offset:offset + 2], "little"))
        if not frame_types.issubset(ALLOWED_MONSTER_FRAME_TYPES):
            raise RuntimeError(f"{section}包含非怪物帧类型：{sorted(frame_types)}")
        actions.append(
            {
                "section": section,
                "start": start,
                "play_count": play,
                "empty_count": empty,
                "directions": directions,
                "min_frame": min(indices),
                "max_frame": max(indices),
                "verified_play_frames": len(indices),
                "frame_types": sorted(frame_types),
            }
        )
    required = {"ActStand", "ActWalk", "ActStruck", "ActDie", "ActAttack1"}
    actual = {item["section"] for item in actions}
    if not required.issubset(actual):
        raise RuntimeError(f"候选缺少基础动作：{sorted(required - actual)}")
    return {
        "wzx_declared_count": declared,
        "wzx_table_count": table_count,
        "wzl_size": len(wzl),
        "actions": actions,
        "total_verified_play_frames": sum(int(item["verified_play_frames"]) for item in actions),
    }


def database_evidence(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"目标数据库不存在：{path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(
            'SELECT rowid AS "_rowid", * FROM Monster WHERE Name=?', (TARGET_MONSTER,)
        )]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if len(rows) != 1:
        raise RuntimeError(f"Monster表中{TARGET_MONSTER}不是唯一行：{len(rows)}")
    actual = {key: int(rows[0][key]) for key in EXPECTED_TARGET_MODEL}
    if actual != EXPECTED_TARGET_MODEL:
        raise RuntimeError(f"{TARGET_MONSTER}模型字段漂移：{actual}")
    if integrity != "ok":
        raise RuntimeError(f"目标数据库完整性失败：{integrity}")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "integrity": integrity,
        "row": rows[0],
    }


def mon_gen_evidence(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    text, encoding, _, _ = detect_text(raw, path)
    matches = []
    for number, line in enumerate(text.splitlines(), 1):
        fields = line.split()
        if len(fields) >= 4 and fields[3] == TARGET_MONSTER:
            matches.append({"line_number": number, "line": line})
    if len(matches) != 1:
        raise RuntimeError(f"MonGen中{TARGET_MONSTER}不是唯一刷新行：{len(matches)}")
    return {
        "path": str(path),
        "sha256": sha256_bytes(raw),
        "encoding": encoding,
        "matches": matches,
    }


def build_candidate(args: argparse.Namespace, effect: dict[str, object]) -> dict[str, object]:
    sources = source_paths(args)
    candidate_ini, rewrite = build_candidate_ini(sources["ini"], int(effect["target_index"]))
    resource_dir = args.candidate_root / "data"
    smart_dir = args.candidate_root / "SmartMonster"
    resource_dir.mkdir(parents=True, exist_ok=True)
    smart_dir.mkdir(parents=True, exist_ok=True)
    candidate_wzl = resource_dir / f"{TARGET_RESOURCE_STEM}.wzl"
    candidate_wzx = resource_dir / f"{TARGET_RESOURCE_STEM}.wzx"
    candidate_ini_path = smart_dir / f"{TARGET_MONSTER}.ini"
    atomic_copy(sources["wzl"], candidate_wzl, EXPECTED_SOURCE_HASHES["wzl"])
    atomic_copy(sources["wzx"], candidate_wzx, EXPECTED_SOURCE_HASHES["wzx"])
    atomic_write_bytes(candidate_ini_path, candidate_ini)
    action_frames = validate_action_frames(candidate_ini, candidate_wzl, candidate_wzx)
    manifest = {
        "schema": "xydp.star10-smartmonster-candidate.v1",
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_monster": SOURCE_MONSTER,
        "target_monster": TARGET_MONSTER,
        "target_effect_index_zero_based": effect["target_index"],
        "effect_entry": TARGET_RESOURCE_ENTRY,
        "rewrite": rewrite,
        "candidate_files": {
            "ini": file_evidence(candidate_ini_path),
            "wzl": file_evidence(candidate_wzl),
            "wzx": file_evidence(candidate_wzx),
        },
        "action_frames": action_frames,
    }
    write_json(args.candidate_root / "manifest.json", manifest)
    return manifest


def process_blockers(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.skip_process_check:
        return []
    m2 = str(target_paths(args)["m2"]).replace("'", "''")
    client_root = str(args.target_data.parent).replace("'", "''")
    command = (
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "$p=Get-CimInstance Win32_Process | Where-Object {"
        f" ($_.ExecutablePath -eq '{m2}') -or"
        f" ($_.ExecutablePath -like '{client_root}\\*') -or"
        " ($_.Name -match '^(Wzl编辑器|MakeGameLogin)\\.exe$') };"
        "if($p){$p|Select-Object ProcessId,Name,ExecutablePath|ConvertTo-Json -Compress}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"进程检查失败：{result.stderr.strip()}")
    output = result.stdout.strip()
    if not output:
        return []
    value = json.loads(output)
    return value if isinstance(value, list) else [value]


def target_state(args: argparse.Namespace, effect: dict[str, object], candidate: dict[str, object]) -> dict[str, object]:
    paths = target_paths(args)
    expected = {
        "ini": candidate["candidate_files"]["ini"]["sha256"],
        "wzl": candidate["candidate_files"]["wzl"]["sha256"],
        "wzx": candidate["candidate_files"]["wzx"]["sha256"],
    }
    files: dict[str, dict[str, object]] = {}
    for key in ("ini", "wzl", "wzx"):
        path = paths[key]
        files[key] = {
            "path": str(path),
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
            "expected_sha256": expected[key],
        }
    entry_count = len(effect["entry_matches"])
    exists_count = sum(1 for value in files.values() if value["exists"])
    if entry_count == 0 and exists_count == 0:
        state = "absent"
    elif entry_count == 1 and exists_count == 3 and all(
        value["sha256"] == value["expected_sha256"] for value in files.values()
    ):
        state = "deployed"
    else:
        state = "partial-or-conflicting"
    return {
        "state": state,
        "effect_entry_count": entry_count,
        "effect_index_zero_based": effect["target_index"],
        "files": files,
        "smart_dir_exists": paths["smart_dir"].is_dir(),
    }


def preflight(args: argparse.Namespace) -> dict[str, object]:
    sources = validate_source_identity(args)
    paths = target_paths(args)
    database = database_evidence(paths["database"])
    mon_gen = mon_gen_evidence(paths["mon_gen"])
    effect = effect_list_state(paths["effect_list"])
    candidate = build_candidate(args, effect)
    state = target_state(args, effect, candidate)
    blockers = process_blockers(args)
    if state["state"] == "deployed":
        status = "already-deployed"
    elif state["state"] != "absent":
        status = "blocked-partial-or-conflicting-target"
    elif blockers:
        status = "blocked-process-running"
    else:
        status = "ready-to-apply"
    result = {
        "schema": "xydp.star10-smartmonster-preflight.v1",
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "source": sources,
        "candidate": candidate,
        "database": database,
        "mon_gen": mon_gen,
        "effect_list": {
            key: value for key, value in effect.items()
            if key not in {"raw", "after_raw", "bom", "lines"}
        },
        "target": state,
        "process_blockers": blockers,
        "production_changes": {
            "database": False,
            "mon_gen": False,
            "pak_rules": False,
            "new_effect_entry": TARGET_RESOURCE_ENTRY,
            "new_smart_ini": f"{TARGET_MONSTER}.ini",
            "new_client_pair": [f"{TARGET_RESOURCE_STEM}.wzl", f"{TARGET_RESOURCE_STEM}.wzx"],
        },
    }
    write_json(args.report_root / "latest-preflight.json", result)
    return result


def backup_before_apply(
    args: argparse.Namespace, transaction_root: Path, plan: dict[str, object]
) -> dict[str, object]:
    snapshots = transaction_root / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=False)
    effect_source = target_paths(args)["effect_list"]
    effect_backup = snapshots / "EffectImageList.txt"
    atomic_copy(effect_source, effect_backup, sha256_file(effect_source))
    absence = {
        "ini_existed": target_paths(args)["ini"].exists(),
        "wzl_existed": target_paths(args)["wzl"].exists(),
        "wzx_existed": target_paths(args)["wzx"].exists(),
        "smart_dir_existed": target_paths(args)["smart_dir"].is_dir(),
    }
    if any(absence[key] for key in ("ini_existed", "wzl_existed", "wzx_existed")):
        raise RuntimeError(f"备份阶段发现候选目标已存在：{absence}")
    write_json(transaction_root / "preflight.json", plan)
    write_json(transaction_root / "absence.json", absence)
    return {
        "effect_list": file_evidence(effect_backup),
        "absence": absence,
    }


def restore_failed_apply(args: argparse.Namespace, transaction_root: Path, backups: dict[str, object]) -> None:
    paths = target_paths(args)
    effect_backup = transaction_root / "snapshots" / "EffectImageList.txt"
    if effect_backup.is_file():
        atomic_copy(effect_backup, paths["effect_list"], sha256_file(effect_backup))
    for key in ("ini", "wzl", "wzx"):
        paths[key].unlink(missing_ok=True)
    if not backups["absence"]["smart_dir_existed"] and paths["smart_dir"].is_dir():
        try:
            paths["smart_dir"].rmdir()
        except OSError:
            pass


def verify_deployed(args: argparse.Namespace, plan: dict[str, object]) -> dict[str, object]:
    paths = target_paths(args)
    effect = effect_list_state(paths["effect_list"])
    state = target_state(args, effect, plan["candidate"])
    if state["state"] != "deployed":
        raise RuntimeError(f"部署回读不是完整状态：{state}")
    if effect["sha256"] != plan["effect_list"]["after_sha256"]:
        raise RuntimeError("EffectImageList提交后哈希不等于预期")
    database = database_evidence(paths["database"])
    mon_gen = mon_gen_evidence(paths["mon_gen"])
    if database["sha256"] != plan["database"]["sha256"]:
        raise RuntimeError("部署期间目标数据库发生变化")
    if mon_gen["sha256"] != plan["mon_gen"]["sha256"]:
        raise RuntimeError("部署期间MonGen发生变化")
    candidate_ini = Path(plan["candidate"]["candidate_files"]["ini"]["path"]).read_bytes()
    frame_check = validate_action_frames(candidate_ini, paths["wzl"], paths["wzx"])
    return {
        "target": state,
        "effect_list": {
            "sha256": effect["sha256"],
            "entry_matches": effect["entry_matches"],
            "target_index_zero_based": effect["target_index"],
        },
        "database_unchanged": True,
        "mon_gen_unchanged": True,
        "action_frames": frame_check,
    }


def apply(args: argparse.Namespace, plan: dict[str, object]) -> dict[str, object]:
    if plan["status"] != "ready-to-apply":
        raise RuntimeError(f"预检状态不允许部署：{plan['status']}")
    if process_blockers(args):
        raise RuntimeError("提交前重新发现M2、客户端或编辑器进程，停止部署")
    transaction_id = f"{dt.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    transaction_root = args.backup_root / transaction_id
    transaction_root.mkdir(parents=True, exist_ok=False)
    backups = backup_before_apply(args, transaction_root, plan)
    paths = target_paths(args)
    candidate_files = plan["candidate"]["candidate_files"]
    try:
        atomic_copy(Path(candidate_files["wzl"]["path"]), paths["wzl"], candidate_files["wzl"]["sha256"])
        atomic_copy(Path(candidate_files["wzx"]["path"]), paths["wzx"], candidate_files["wzx"]["sha256"])
        atomic_copy(Path(candidate_files["ini"]["path"]), paths["ini"], candidate_files["ini"]["sha256"])
        effect = effect_list_state(paths["effect_list"])
        if effect["entry_matches"]:
            raise RuntimeError("提交阶段EffectImageList目标行已被其他任务写入")
        if int(effect["target_index"]) != int(plan["effect_list"]["target_index"]):
            raise RuntimeError("提交阶段EffectImageList序号发生变化")
        atomic_write_bytes(paths["effect_list"], effect["after_raw"])
        verification = verify_deployed(args, plan)
        receipt = {
            **plan,
            "schema": "xydp.star10-smartmonster-deploy.v1",
            "status": "deployed-awaiting-game-validation",
            "transaction_id": transaction_id,
            "completed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "backup_root": str(transaction_root),
            "backups": backups,
            "verification": verification,
            "rollback_command": (
                f'python "{Path(__file__).resolve()}" --rollback {transaction_id} --yes'
            ),
        }
        write_json(transaction_root / "receipt.json", receipt)
        write_json(args.report_root / f"{transaction_id}_deploy.json", receipt)
        return receipt
    except Exception:
        restore_failed_apply(args, transaction_root, backups)
        raise


def rollback(args: argparse.Namespace, transaction_id: str) -> dict[str, object]:
    if process_blockers(args):
        raise RuntimeError("存在M2、客户端或编辑器进程，阻止回滚")
    transaction_root = args.backup_root / transaction_id
    receipt_path = transaction_root / "receipt.json"
    if not receipt_path.is_file():
        raise RuntimeError(f"事务回执不存在：{receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    paths = target_paths(args)
    current_effect_hash = sha256_file(paths["effect_list"])
    deployed_effect_hash = receipt["verification"]["effect_list"]["sha256"]
    if current_effect_hash != deployed_effect_hash:
        raise RuntimeError("EffectImageList在部署后已变化，禁止整文件回滚")
    for key in ("ini", "wzl", "wzx"):
        expected = receipt["candidate"]["candidate_files"][key]["sha256"]
        if not paths[key].is_file() or sha256_file(paths[key]) != expected:
            raise RuntimeError(f"{key}已在部署后变化，禁止删除")
    if sha256_file(paths["database"]) != receipt["database"]["sha256"]:
        raise RuntimeError("目标数据库已变化，禁止回滚当前模型链")
    if sha256_file(paths["mon_gen"]) != receipt["mon_gen"]["sha256"]:
        raise RuntimeError("MonGen已变化，禁止回滚当前模型链")
    rollback_snapshot = transaction_root / "rollback-current"
    rollback_snapshot.mkdir(exist_ok=False)
    atomic_copy(paths["effect_list"], rollback_snapshot / "EffectImageList.txt", current_effect_hash)
    for key in ("ini", "wzl", "wzx"):
        atomic_copy(paths[key], rollback_snapshot / paths[key].name, sha256_file(paths[key]))
    effect_backup = transaction_root / "snapshots" / "EffectImageList.txt"
    atomic_copy(effect_backup, paths["effect_list"], receipt["backups"]["effect_list"]["sha256"])
    for key in ("ini", "wzl", "wzx"):
        paths[key].unlink()
    if not receipt["backups"]["absence"]["smart_dir_existed"]:
        try:
            paths["smart_dir"].rmdir()
        except OSError:
            pass
    result = {
        "schema": "xydp.star10-smartmonster-rollback.v1",
        "status": "rolled-back",
        "transaction_id": transaction_id,
        "completed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "restored_effect_list": file_evidence(paths["effect_list"]),
        "removed": [str(paths[key]) for key in ("ini", "wzl", "wzx")],
        "rollback_snapshot": str(rollback_snapshot),
    }
    write_json(transaction_root / "rollback-receipt.json", result)
    return result


def main() -> int:
    args = parse_args()
    if args.apply and args.rollback:
        raise RuntimeError("--apply和--rollback不能同时使用")
    if (args.apply or args.rollback) and not args.yes:
        raise RuntimeError("写操作必须同时提供--yes")
    if args.rollback:
        print(json.dumps(rollback(args, args.rollback), ensure_ascii=False, indent=2))
        return 0
    plan = preflight(args)
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan["status"] in {"ready-to-apply", "already-deployed"} else 2
    result = apply(args, plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
