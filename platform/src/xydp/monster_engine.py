from __future__ import annotations

import configparser
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


RESOURCE_KEYS = frozenset({
    "HPFile", "ActionFile", "EffectFile", "EffectFile2", "Fly_File",
    "FlyEff_File", "Self_File", "SelfKeep_File", "Explosion_File", "Target_File",
})
ALLOWED_MONSTER_FRAME_TYPES = frozenset({259, 261})
REQUIRED_ACTIONS = frozenset({"ActStand", "ActWalk", "ActStruck", "ActDie", "ActAttack1"})


@dataclass(frozen=True)
class EngineDependency:
    source_index: int
    entry: str
    kind: str
    source_path: str
    companion_path: str | None
    source_hash: str
    companion_hash: str | None
    pak_password: str | None
    ordinal: int | None = None
    monster_id: int | None = None


@dataclass(frozen=True)
class MonsterEngineClosure:
    engine_mode: str
    closure_status: str
    closure_hash: str
    smart_ini_path: str | None
    smart_ini_hash: str | None
    dependencies: tuple[EngineDependency, ...]
    resource_reference_counts: dict[str, int]
    total_verified_play_frames: int
    login_policy: str
    capability_policy: str
    reason: str | None


@dataclass(frozen=True)
class EffectImageListDocument:
    path: str
    raw: bytes
    encoding: str
    bom: bytes
    newline: str
    lines: tuple[str, ...]


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _detect_text(raw: bytes, path: Path) -> tuple[str, str, bytes, str]:
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):]
    for encoding in ("utf-8", "gb18030"):
        try:
            text = body.decode(encoding)
        except UnicodeDecodeError:
            continue
        newline = "\r\n" if b"\r\n" in body else "\n"
        return text, encoding, bom, newline
    raise RuntimeError(f"文本编码无法识别：{path}")


def _parse_ini(text: str) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    parser.read_file(io.StringIO(text))
    return parser


def _closure_hash(
    monster_values: Mapping[str, object],
    ini_hash: str | None,
    effect_list_hash: str | None,
    dependencies: tuple[EngineDependency, ...],
    engine_mode: str,
    status: str,
    resource_reference_counts: Mapping[str, int],
    total_verified_play_frames: int,
    login_policy: str,
    capability_policy: str,
    reason: str | None,
) -> str:
    payload = {
        "monster": {str(key): str(value) for key, value in sorted(monster_values.items())},
        "smart_ini_hash": ini_hash,
        "effect_image_list_hash": effect_list_hash,
        "dependencies": [
            {
                "source_index": item.source_index,
                "entry": item.entry,
                "kind": item.kind,
                "source_hash": item.source_hash,
                "companion_hash": item.companion_hash,
            }
            for item in dependencies
        ],
        "engine_mode": engine_mode,
        "status": status,
        "resource_reference_counts": dict(sorted(resource_reference_counts.items())),
        "total_verified_play_frames": total_verified_play_frames,
        "login_policy": login_policy,
        "capability_policy": capability_policy,
        "reason": reason,
    }
    return _sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _make_closure(
    monster_values: Mapping[str, object],
    *,
    engine_mode: str,
    closure_status: str,
    smart_ini: Path | None,
    smart_ini_hash: str | None,
    effect_list_hash: str | None = None,
    dependencies: tuple[EngineDependency, ...] = (),
    resource_reference_counts: dict[str, int] | None = None,
    total_verified_play_frames: int = 0,
    login_policy: str = "none",
    capability_policy: str = "not_applicable",
    reason: str | None = None,
) -> MonsterEngineClosure:
    counts = resource_reference_counts or {}
    return MonsterEngineClosure(
        engine_mode=engine_mode,
        closure_status=closure_status,
        closure_hash=_closure_hash(
            monster_values,
            smart_ini_hash,
            effect_list_hash,
            dependencies,
            engine_mode,
            closure_status,
            counts,
            total_verified_play_frames,
            login_policy,
            capability_policy,
            reason,
        ),
        smart_ini_path=str(smart_ini) if smart_ini and smart_ini.is_file() else None,
        smart_ini_hash=smart_ini_hash,
        dependencies=dependencies,
        resource_reference_counts=counts,
        total_verified_play_frames=total_verified_play_frames,
        login_policy=login_policy,
        capability_policy=capability_policy,
        reason=reason,
    )


def derive_donor_server_root(database: Path) -> Path:
    database = Path(database)
    if database.name.casefold() != "apexm2.db" or database.parent.name.casefold() != "db" or database.parent.parent.name.casefold() != "mud2":
        raise RuntimeError(f"数据库路径不符合Mud2/DB/ApexM2.DB：{database}")
    return database.parent.parent.parent


def classify_engine_mode(monster_values: Mapping[str, object], smart_ini: Path | None) -> str:
    if smart_ini is not None and Path(smart_ini).is_file():
        return "smartmonster"
    try:
        race_img = int(monster_values.get("RaceImg", -1))
    except (TypeError, ValueError):
        race_img = -1
    return "smartmonster" if race_img == 156 else "standard_appr"


def parse_effect_image_list(path: Path) -> EffectImageListDocument:
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"EffectImageList不存在：{path}")
    raw = path.read_bytes()
    text, encoding, bom, newline = _detect_text(raw, path)
    return EffectImageListDocument(
        path=str(path), raw=raw, encoding=encoding, bom=bom, newline=newline, lines=tuple(text.splitlines())
    )


def _capability_reason(parser: configparser.RawConfigParser) -> str | None:
    if parser.get("ServerAttack0", "AttackEnabled", fallback="") != "1":
        return "ServerAttack0不是基础攻击入口"
    if parser.get("ServerAttack0", "AttackMode", fallback="") != "0":
        return "ServerAttack0不是普通近战模式"
    for section in parser.sections():
        folded_section = section.casefold()
        server_attack = re.fullmatch(r"serverattack(\d+)", folded_section)
        if server_attack is not None and int(server_attack.group(1)) != 0:
            if parser.get(section, "AttackEnabled", fallback="0") != "0":
                return f"{section}启用了额外攻击"
        for key, value in parser.items(section):
            folded_key = key.casefold()
            if folded_section.startswith("additionals") and folded_key.startswith("checked") and value != "0":
                return f"{section}.{key}启用了附加状态"
            if folded_section.startswith("callmonster") and folded_key == "callmonstersrate" and value != "0":
                return f"{section}.{key}启用了召唤"
            if folded_section.startswith("protect") and folded_key in {
                "protectaddhp", "protectadddefence", "protectaddmagdefence", "protectadddc", "protectaddmc", "protectaddsc",
            } and value != "0":
                return f"{section}.{key}启用了保护增益"
    return None


def _collect_resource_references(parser: configparser.RawConfigParser) -> tuple[dict[str, int], dict[int, list[str]]]:
    counts: dict[str, int] = {}
    references: dict[int, list[str]] = {}
    for section in parser.sections():
        for key, value in parser.items(section):
            if key not in RESOURCE_KEYS:
                continue
            try:
                index = int(value.strip())
            except ValueError as exc:
                raise RuntimeError(f"{section}.{key}不是整数：{value}") from exc
            if index < 0:
                continue
            counts[key] = counts.get(key, 0) + 1
            references.setdefault(index, []).append(key)
    if not counts.get("ActionFile"):
        raise RuntimeError("INI缺少ActionFile资源引用")
    return counts, references


def _resolve_dependency(
    index: int,
    document: EffectImageListDocument,
    client_roots: Sequence[Path],
    pak_passwords: Mapping[str, set[str]],
) -> EngineDependency:
    if index >= len(document.lines):
        raise RuntimeError(f"EffectImageList没有零基索引{index}")
    entry = document.lines[index]
    if not entry.strip():
        raise RuntimeError(f"EffectImageList零基索引{index}引用空行")
    source: Path | None = None
    for root in client_roots:
        candidate = Path(root) / entry.strip()
        if candidate.is_file():
            source = candidate
            break
    if source is None:
        raise RuntimeError(f"客户端资源不存在：{entry}")
    suffix = source.suffix.casefold()
    if suffix == ".wzl":
        companion = source.with_suffix(".wzx")
        if not companion.is_file():
            raise RuntimeError(f"WZL缺少WZX伴随文件：{source.name}")
        return EngineDependency(index, entry, "wzl_wzx", str(source), str(companion), _sha256_file(source), _sha256_file(companion), None)
    if suffix == ".pak":
        passwords = pak_passwords.get(entry) or pak_passwords.get(source.name) or pak_passwords.get(str(source)) or set()
        if len(passwords) != 1:
            raise RuntimeError(f"PAK缺少唯一密码规则：{entry}")
        return EngineDependency(index, entry, "pak", str(source), None, _sha256_file(source), None, next(iter(passwords)))
    raise RuntimeError(f"不支持的SmartMonster资源类型：{entry}")


def _validate_action_frames(
    parser: configparser.RawConfigParser, dependencies: Mapping[int, EngineDependency]
) -> int:
    actual = {section for section in parser.sections() if section.startswith("Act")}
    missing = REQUIRED_ACTIONS - actual
    if missing:
        raise RuntimeError(f"候选缺少基础动作：{sorted(missing)}")
    for section in REQUIRED_ACTIONS:
        if not parser.has_option(section, "ActionFile"):
            raise RuntimeError(f"{section}缺少ActionFile")
        if parser.getint(section, "StartIndex", fallback=-1) < 0:
            raise RuntimeError(f"{section}起始索引无效")
        if parser.getint(section, "PlayCount", fallback=0) <= 0:
            raise RuntimeError(f"{section}播放帧数无效")
    total = 0
    for section in parser.sections():
        if not section.startswith("Act") or not parser.has_option(section, "ActionFile"):
            continue
        start = parser.getint(section, "StartIndex", fallback=-1)
        play_count = parser.getint(section, "PlayCount", fallback=0)
        empty_count = parser.getint(section, "EmptyCount", fallback=0)
        calc_dir = parser.getint(section, "CalcDir", fallback=0)
        if start < 0 or play_count <= 0:
            continue
        resource_index = parser.getint(section, "ActionFile")
        dependency = dependencies.get(resource_index)
        if dependency is None or dependency.kind != "wzl_wzx" or dependency.companion_path is None:
            raise RuntimeError(f"{section}动作资源不可读取")
        wzl = Path(dependency.source_path).read_bytes()
        wzx = Path(dependency.companion_path).read_bytes()
        if len(wzx) < 48 or (len(wzx) - 48) % 4:
            raise RuntimeError("WZX索引表结构异常")
        table_count = (len(wzx) - 48) // 4
        declared = int.from_bytes(wzx[44:48], "little")
        count = min(declared, table_count) if declared else table_count
        directions = 8 if calc_dir == 1 else 1
        stride = play_count + empty_count
        indices = [start + direction * stride + frame for direction in range(directions) for frame in range(play_count)]
        if not indices or max(indices) >= count:
            raise RuntimeError(f"{section}动作帧越界")
        for frame_index in indices:
            offset = int.from_bytes(wzx[48 + frame_index * 4:52 + frame_index * 4], "little")
            if offset <= 0 or offset + 2 > len(wzl):
                raise RuntimeError(f"{section}动作帧为空或偏移越界")
            frame_type = int.from_bytes(wzl[offset:offset + 2], "little")
            if frame_type not in ALLOWED_MONSTER_FRAME_TYPES:
                raise RuntimeError(f"{section}包含非怪物帧类型：{frame_type}")
        total += len(indices)
    return total


def build_smartmonster_closure(
    monster_values: Mapping[str, object],
    smart_ini: Path,
    effect_list: Path,
    client_roots: Sequence[Path],
    pak_passwords: Mapping[str, set[str]],
) -> MonsterEngineClosure:
    smart_ini = Path(smart_ini)
    engine_mode = classify_engine_mode(monster_values, smart_ini)
    if engine_mode != "smartmonster":
        return _make_closure(monster_values, engine_mode=engine_mode, closure_status="unsupported", smart_ini=None, smart_ini_hash=None, reason="不是SmartMonster引擎模式")
    if not smart_ini.is_file():
        return _make_closure(monster_values, engine_mode=engine_mode, closure_status="incomplete", smart_ini=smart_ini, smart_ini_hash=None, login_policy="custom_monster_dat_required", capability_policy="unknown", reason="缺少同名SmartMonster INI")
    raw_ini = smart_ini.read_bytes()
    ini_hash = _sha256_bytes(raw_ini)
    effect_list_hash: str | None = None
    try:
        text, _, _, _ = _detect_text(raw_ini, smart_ini)
        parser = _parse_ini(text)
        document = parse_effect_image_list(effect_list)
        effect_list_hash = _sha256_bytes(document.raw)
        complex_reason = _capability_reason(parser)
        if complex_reason:
            return _make_closure(monster_values, engine_mode=engine_mode, closure_status="complex_ability", smart_ini=smart_ini, smart_ini_hash=ini_hash, effect_list_hash=effect_list_hash, login_policy="custom_monster_dat_required", capability_policy="complex_ability", reason=complex_reason)
        counts, references = _collect_resource_references(parser)
        dependencies = tuple(_resolve_dependency(index, document, client_roots, pak_passwords) for index in sorted(references))
        dependency_map = {dependency.source_index: dependency for dependency in dependencies}
        if any(dependency.kind == "pak" for dependency in dependencies):
            return _make_closure(monster_values, engine_mode=engine_mode, closure_status="ready_opaque", smart_ini=smart_ini, smart_ini_hash=ini_hash, effect_list_hash=effect_list_hash, dependencies=dependencies, resource_reference_counts=counts, login_policy="custom_monster_dat_required", capability_policy="basic_melee", reason="资源容器不可读取，需单怪验收")
        frames = _validate_action_frames(parser, dependency_map)
        return _make_closure(monster_values, engine_mode=engine_mode, closure_status="ready_verified", smart_ini=smart_ini, smart_ini_hash=ini_hash, effect_list_hash=effect_list_hash, dependencies=dependencies, resource_reference_counts=counts, total_verified_play_frames=frames, login_policy="custom_monster_dat_required", capability_policy="basic_melee")
    except (OSError, RuntimeError, configparser.Error, ValueError) as exc:
        return _make_closure(monster_values, engine_mode=engine_mode, closure_status="incomplete", smart_ini=smart_ini, smart_ini_hash=ini_hash, effect_list_hash=effect_list_hash, login_policy="custom_monster_dat_required", capability_policy="basic_melee", reason=str(exc))


def rewrite_smartmonster_ini(ini_bytes: bytes, source_to_target: Mapping[int, int]) -> bytes:
    text, encoding, bom, _ = _detect_text(ini_bytes, Path("SmartMonster.ini"))
    pattern = re.compile(r"^(?P<prefix>\s*(?:" + "|".join(re.escape(key) for key in RESOURCE_KEYS) + r")\s*=\s*)(?P<value>-?\d+)(?P<suffix>\s*(?:[;#].*)?)$")
    rewritten: list[str] = []
    for line in text.splitlines(keepends=True):
        ending = ""
        body = line
        if body.endswith("\r\n"):
            body, ending = body[:-2], "\r\n"
        elif body.endswith("\n") or body.endswith("\r"):
            body, ending = body[:-1], body[-1]
        match = pattern.match(body)
        if match is None:
            rewritten.append(line)
            continue
        source_index = int(match.group("value"))
        if source_index < 0:
            rewritten.append(line)
            continue
        if source_index not in source_to_target:
            raise RuntimeError(f"资源引用缺少目标映射：{source_index}")
        target_index = source_to_target[source_index]
        if target_index < 0:
            raise RuntimeError(f"目标资源编号必须非负：{target_index}")
        rewritten.append(f"{match.group('prefix')}{target_index}{match.group('suffix')}{ending}")
    return bom + "".join(rewritten).encode(encoding)
