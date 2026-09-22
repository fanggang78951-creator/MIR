"""命格八槽候选池的四文件受管事务。

原NPC仍负责槽位、支付、概率和保底。本模块只在原核心的洗练完成出口
注入同文件候选池与八槽重建块，并生成一个不依赖槽位临时变量的运行时重算后台。
NPC包装、MerChant、数据库和客户端保持不变。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import replace
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .mingge_native import NativeCandidate, compile_native_candidate, read_native_candidate_workbook
from .mingge_native_p2_install import (
    NativeP2TestInstallError,
    _assert_no_reparse_path,
    _is_reparse_point,
    _transaction_lock as _p2_transaction_lock,
)


TEST_SCRIPT_RELATIVE = "Mir200/Envir/QuestDiary/玄渊命格/命格P3实例快速版.txt"
USERCMD_RELATIVE = "Mir200/Envir/UserCmd.txt"
QFUNCTION_RELATIVE = "Mir200/Envir/Market_Def/QFunction-0.txt"
TEXTVAR_RELATIVE = "Mir200/Envir/CustomItemPropertyTextVarList.txt"
NPC_WRAPPER_RELATIVE = "Mir200/Envir/Market_Def/玄渊命格/龙魂觉醒-3.txt"
CORE_RELATIVE = "Mir200/Envir/QuestDiary/玄渊命格/命格核心.txt"
ATTACK_SPEED_CORE_RELATIVE = "Mir200/Envir/QuestDiary/玄渊攻速突破/全身攻速阈值核心.txt"
MERCHANT_RELATIVE = "Mir200/Envir/MerChant.txt"
BASELINE_RELATIVES = (
    MERCHANT_RELATIVE,
    NPC_WRAPPER_RELATIVE,
    CORE_RELATIVE,
    TEXTVAR_RELATIVE,
    QFUNCTION_RELATIVE,
)
EXPECTED_P2_HASHES = {
    MERCHANT_RELATIVE: "EFD62AD12FD0B90E25DE794B78CF4BE786484DD7CE5C1E5AAE217F1935FF4E97".lower(),
    NPC_WRAPPER_RELATIVE: "EF2A5A673C93EDC1652ABE01AEDE2D97D5A8EFCFE3EB5C03AA1F434FD1CBA57B".lower(),
}
EXPECTED_P2_ROWS = {
    17: (250, 1, 17, 0, 0, 5, 0, 0),
    18: (250, 6, 18, 0, 0, 100, 0, 0),
    19: (250, 7, 19, 0, 0, 100, 0, 0),
}
EXPECTED_PROPERTIES = (
    (1, "防御", 5, 17, 1),
    (2, "生命值", 100, 18, 6),
    (3, "魔法值", 100, 19, 7),
)
TEXT_VAR_START = 33
POOL_ORDER = ("GREEN", "BLUE", "RED", "RAINBOW")
RAINBOW_NAME_COLORS = (249, 69, 250, 251)
RAINBOW_PROPERTY_COLORS = (31, 147, 239)
RAINBOW_PANEL_AUTOCOLOR = "254,251,168,191,250,70,245,249,253"
PANEL_RESULT_VARIABLE = "S$XY_MG_P4_PANEL_RESULT"
PANEL_PLACEHOLDER = "<&Text:点击中间已开放槽位进行选择:420:126{FCOLOR=161}>"
PANEL_DEFAULT = "<&Text:点击洗练后在这里显示本次命格:420:126{FCOLOR=161}>"
PROGRESS_SCHEMA_FLAG = "U499"
PROGRESS_SCHEMA_VERSION = 82802
OWNED_PROGRESS_COUNTERS = (
    *(f"U{value}" for value in range(201, 209)),
    *(f"U{value}" for value in range(471, 479)),
    *(f"U{value}" for value in range(491, 499)),
)
RUNTIME_VARIABLES = {
    33: "N$XY_MG_P3_MONSTER_ABSORB",
    34: "N$XY_MG_P3_TAO_PERCENT",
    35: "N$XY_MG_P3_FATAL",
    36: "N$XY_MG_P3_EXECUTION_BP",
    37: "N$XY_MG_P3_CORPSE",
    38: "N$XY_MG_P3_BLAST",
    39: "N$XY_MG_P3_TAIL",
}
ATTACK_SPEED_TEXT_LINE = 40
ATTACK_SPEED_TEXT = "{攻速突破∶|251}+$$2"
ATTACK_SPEED_CALL = "#CALL [\\玄渊攻速突破\\全身攻速阈值核心.txt] @XY_AS_CAP_RECALC"
SCRIPT_BIND_RUNTIME_VARIABLES = {
    50: "N$XY_MG_P3_TOUGHNESS",
    51: "N$XY_MG_P3_EXECUTION_BONUS",
    53: "N$XY_MG_P3_DAMAGE_COEFF",
}
QFUNCTION_ANCHOR_PLAN = (
    (33, "@XYDP_RecalcMonsterAbsorb", "汇总后接现有对怪吸收重算"),
    (34, "@XY_MG_P3_RECALC_TAO", "道术下限/上限临时归零后CalcPercent重算"),
    (35, "@XY_MG_P3_RECALC_FATAL", "独立命格原生重算后AddHumNewValue 22"),
    (36, "XY_EXECUTION_LAB_CHANCE_ANCHOR", "接现有处决概率运行时"),
    (37, "XY_EQUIP_MAKER_CORPSE_ANCHOR", "接KillMon鞭尸运行时"),
    (38, "@XYDP_RecalcBlast", "接现有暴击伤害重算"),
    (39, "XY_EQUIP_MAKER_KILL_RESET", "接AttackDamage尾刀运行时"),
    (50, "XY_EXECUTION_LAB_TOUGHNESS_ANCHOR", "韧性实例显示镜像后接玩家实效缓存"),
    (51, "XY_EXECUTION_LAB_PVE_BONUS_ANCHOR", "处决倍率实例显示镜像后接玩家实效缓存"),
    (53, "XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR", "伤害系数实例显示镜像后接玩家实效缓存"),
)
NPC_ENTRY_PLAN = (
    "Mir200/Envir/MerChant.txt:复用地图3(320,339)龙魂觉醒，不新增注册",
    "Mir200/Envir/Market_Def/玄渊命格/龙魂觉醒-3.txt:只读确认继续调用原命格核心，不纳入写入事务",
    "Mir200/Envir/QuestDiary/玄渊命格/命格核心.txt:在@XY_MG_DRAW_TAIL追加同文件八槽候选池与重建块，不改变界面布局",
)
TRANSACTION_ID = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")


class NativeP3ColorTestInstallError(ValueError):
    """P3实例快速版的只读预检或多文件事务不满足安全契约。"""


@dataclass(frozen=True)
class NativeP3ColorPlannedFile:
    relative_path: str
    path: Path
    before_sha256: str
    after_sha256: str
    after: bytes


@dataclass(frozen=True)
class NativeP3ColorInstallPlan:
    plan_id: str
    workbook: Path
    workbook_sha256: str
    candidate_spec_sha256: str
    candidate_ids: tuple[str, ...]
    candidate_literals: tuple[str, ...]
    server_root: Path
    files: tuple[NativeP3ColorPlannedFile, ...]
    text_var_entries: tuple[tuple[int, str], ...]
    qfunction_anchor_plan: tuple[tuple[int, str, str], ...]
    npc_entry_plan: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class NativeP3ColorInstallReceipt:
    transaction_id: str
    status: str
    receipt_path: Path
    files: tuple[str, ...]


@dataclass(frozen=True)
class NativeP3ColorRollbackReceipt:
    transaction_id: str
    status: str
    receipt_path: Path


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _server_key(server_root: Path) -> str:
    return _sha256_bytes(str(Path(server_root).resolve()).casefold().encode("utf-8"))[:24]


def _transaction_base(platform_root: Path, *, create: bool = False) -> Path:
    raw_root = Path(platform_root).absolute()
    if _is_reparse_point(raw_root):
        raise NativeP3ColorTestInstallError("平台根目录不能是符号链接、联接或重解析点")
    root = raw_root.resolve(strict=False)
    base = root / "backups" / "mingge-native-p3-color-test"
    if not base.resolve(strict=False).is_relative_to(root):
        raise NativeP3ColorTestInstallError("命格P3颜色事务目录越界")
    if create:
        base.mkdir(parents=True, exist_ok=True)
    if base.exists():
        try:
            _assert_no_reparse_path(base, root)
        except NativeP2TestInstallError as exc:
            raise NativeP3ColorTestInstallError(str(exc)) from exc
    return base


def _active_path(platform_root: Path, server_root: Path) -> Path:
    return _transaction_base(platform_root) / "active" / f"{_server_key(server_root)}.json"


def _coordination_path(platform_root: Path, server_root: Path) -> Path:
    return _transaction_base(platform_root) / "coordination" / f"{_server_key(server_root)}.json"


def _current_hash(path: Path) -> str | None:
    return _sha256_bytes(path.read_bytes()) if path.is_file() else None


def _baseline_blockers(server: Path) -> list[str]:
    blockers: list[str] = []
    for relative in BASELINE_RELATIVES:
        path = server / Path(relative)
        try:
            _assert_no_reparse_path(path, server)
        except NativeP2TestInstallError as exc:
            blockers.append(str(exc))
            continue
        current = _current_hash(path)
        expected = EXPECTED_P2_HASHES.get(relative)
        if current is None:
            blockers.append(f"命格P3运行时依赖文件缺失：{relative}")
        elif expected is not None and current != expected:
            blockers.append(f"当前P2基线哈希不匹配：{relative}；期望{expected}，实际{current or 'missing'}")
    return blockers


def _candidate_fingerprint(candidates: tuple[NativeCandidate, ...]) -> str:
    payload = []
    for candidate in candidates:
        compiled = compile_native_candidate(candidate)
        payload.append({
            "candidate_id": candidate.candidate_id,
            "target_item_name": candidate.target_item_name,
            "equip_slot": candidate.equip_slot,
            "mingge_name": candidate.mingge_name,
            "color_scheme": asdict(candidate.color_scheme) if candidate.color_scheme else None,
            "properties": [
                {
                    "order": item.order,
                    "display_name": item.display_name,
                    "value": item.value,
                    "row": item.property_row,
                    "position": item.position,
                    "binding": item.binding,
                    "value2": item.value2,
                    "value3": item.value3,
                    "dependency": item.dependency,
                    "route": item.route,
                    "text_line": item.text_line,
                }
                for item in candidate.properties
            ],
            "segments": [asdict(item) for item in candidate.segments],
            "segment_literal": compiled.segment_literal,
        })
    return _sha256_bytes(_canonical_json(payload))


def _candidate_blockers(candidates: tuple[NativeCandidate, ...]) -> list[str]:
    blockers: list[str] = []
    if len(candidates) < 4:
        blockers.append("八槽候选池至少需要4个启用候选以覆盖绿/蓝/红/彩四类")
    for candidate in candidates:
        if candidate.target_item_name != "鞭尸灵玉" or candidate.equip_slot != 17:
            blockers.append(f"候选{candidate.candidate_id}只允许目标装备鞭尸灵玉、中文部位灵玉/位置17")
        if not 1 <= len(candidate.properties) <= 3:
            blockers.append(f"候选{candidate.candidate_id}必须包含1至3条属性")
        if any(item.property_row not in range(0, 20) for item in candidate.properties):
            blockers.append(f"候选{candidate.candidate_id}属性row超出引擎明确支持的0至19")
        for item in candidate.properties:
            if item.route == "static_only":
                blockers.append(f"候选{candidate.candidate_id}属性{item.display_name}只有static_only路由，快速版禁止伪造实效")
            elif item.route == "textline_runtime" and item.text_line not in {*RUNTIME_VARIABLES, ATTACK_SPEED_TEXT_LINE}:
                blockers.append(f"候选{candidate.candidate_id}属性{item.display_name}的Text行没有已接入的实例接口")
            elif item.route == "script_bind" and item.binding not in SCRIPT_BIND_RUNTIME_VARIABLES:
                blockers.append(
                    f"候选{candidate.candidate_id}属性{item.display_name}使用未接入人物实效缓存的"
                    f"script_bind binding{item.binding}，禁止只生成显示镜像"
                )
            elif item.route not in {"direct", "script_bind", "textline_runtime"}:
                blockers.append(f"候选{candidate.candidate_id}属性{item.display_name}路由非法")
        scheme = candidate.color_scheme
        if scheme is None:
            blockers.append(f"候选{candidate.candidate_id}不是V3颜色方案候选")
        elif scheme.kind not in {"uniform", "native-rainbow"}:
            blockers.append(f"候选{candidate.candidate_id}颜色方案类型非法")
        if sum(item.role == "命格名称" for item in candidate.segments) != 1:
            blockers.append(f"候选{candidate.candidate_id}必须恰好显示一次命格名称")
        for property_name in (item.display_name for item in candidate.properties):
            roles = tuple(
                item.role for item in candidate.segments
                if item.source_property == property_name
            )
            expected_roles = ("属性名称", "正负号", "属性值", "单位") if next(
                prop.unit for prop in candidate.properties if prop.display_name == property_name
            ) else ("属性名称", "正负号", "属性值")
            if roles != expected_roles:
                blockers.append(f"候选{candidate.candidate_id}必须恰好显示{property_name}的名称、正负号和值")
    branch_owners: dict[str, str] = {}
    for candidate in candidates:
        key = _branch_key(candidate)
        previous = branch_owners.get(key)
        if previous is not None:
            blockers.append(
                f"候选ID转换后脚本标签{key}冲突：{previous}与{candidate.candidate_id}"
            )
        else:
            branch_owners[key] = candidate.candidate_id
    try:
        _classify_candidates(candidates)
    except NativeP3ColorTestInstallError as exc:
        blockers.append(str(exc))
    aggregate_keys = {
        (item.binding, item.type3, item.type4, item.value_command)
        for candidate in candidates
        for item in candidate.properties
        if item.route in {"direct", "script_bind"} or item.text_line == ATTACK_SPEED_TEXT_LINE
    }
    if len(aggregate_keys) > 8:
        blockers.append("当前候选集合的唯一direct/script_bind绑定超过row1至8的汇总上限")
    for _, value in _candidate_text_var_entries(candidates):
        if len(value) > 128:
            blockers.append("命格名称与属性组合文本超过引擎128字符上限")
    return list(dict.fromkeys(blockers))


def _candidate_pool_name(candidate: NativeCandidate) -> str | None:
    scheme = candidate.color_scheme
    if scheme is None:
        return None
    if scheme.kind == "native-rainbow":
        return "RAINBOW"
    if scheme.kind != "uniform":
        return None
    return {249: "RED", 250: "GREEN", 252: "BLUE"}.get(int(scheme.uniform_color))


def _classify_candidates(candidates: tuple[NativeCandidate, ...]) -> dict[str, tuple[NativeCandidate, ...]]:
    grouped: dict[str, list[NativeCandidate]] = {name: [] for name in POOL_ORDER}
    for candidate in candidates:
        name = _candidate_pool_name(candidate)
        if name is not None:
            grouped[name].append(candidate)
    missing = tuple(name for name in POOL_ORDER if not grouped[name])
    if missing:
        raise NativeP3ColorTestInstallError("命格候选池缺少颜色类别：" + "、".join(missing))
    return {name: tuple(grouped[name]) for name in POOL_ORDER}


def _encode_script(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("gb18030")


def _decode_script(payload: bytes, label: str) -> str:
    try:
        return payload.decode("gb18030")
    except UnicodeError as exc:
        raise NativeP3ColorTestInstallError(f"{label}不是GB18030可解码文本") from exc


def _candidate_display_literal(candidate: NativeCandidate) -> str:
    scheme = candidate.color_scheme
    if scheme is not None and scheme.kind == "native-rainbow":
        name = "".join(
            f"{{{character}|{RAINBOW_NAME_COLORS[index % len(RAINBOW_NAME_COLORS)]}}}"
            for index, character in enumerate(candidate.mingge_name)
        )
        properties = []
        for index, item in enumerate(candidate.properties):
            sign = "+" if item.value >= 0 else "-"
            text = f"{item.display_name}{sign}{abs(item.value)}{item.unit}"
            properties.append(
                f"{{{text}|{RAINBOW_PROPERTY_COLORS[index % len(RAINBOW_PROPERTY_COLORS)]}}}"
            )
        if not name or not properties:
            raise NativeP3ColorTestInstallError(f"候选{candidate.candidate_id}没有可用的彩色名称或属性")
        return name + "\\" + "{·|255}".join(properties)
    color = int(scheme.uniform_color) if scheme is not None and scheme.uniform_color is not None else candidate.segments[0].color
    name = "".join(
        f"{{{candidate.mingge_name[index:index + 2]}|{color}}}"
        for index in range(0, len(candidate.mingge_name), 2)
    )
    properties = []
    for item in candidate.properties:
        sign = "+" if item.value >= 0 else "-"
        properties.append(f"{{{item.display_name}{sign}{abs(item.value)}{item.unit}|{color}}}")
    if not name or not properties:
        raise NativeP3ColorTestInstallError(f"候选{candidate.candidate_id}没有可用的统一色名称或属性")
    return name + "\\" + f"{{·|{color}}}".join(properties)


def _candidate_panel_markup(candidate: NativeCandidate) -> str:
    text = f"本次洗出：{candidate.mingge_name}（槽位<$STR(N$XY_MG_SLOT)>）"
    scheme = candidate.color_scheme
    if scheme is not None and scheme.kind == "native-rainbow":
        style = f"AUTOCOLOR={RAINBOW_PANEL_AUTOCOLOR};FSIZE=9"
    else:
        color = int(scheme.uniform_color) if scheme is not None and scheme.uniform_color is not None else candidate.segments[0].color
        style = f"FCOLOR={color};FSIZE=9"
    return f"<&Text:{text}:405:126{{{style}}}>"


def _candidate_text_var_entries(candidates: tuple[NativeCandidate, ...]) -> tuple[tuple[int, str], ...]:
    return tuple(
        (TEXT_VAR_START + index, _candidate_display_literal(candidate))
        for index, candidate in enumerate(candidates)
    )


def _append_text_vars(before: bytes, entries: tuple[tuple[int, str], ...]) -> bytes:
    lines = _decode_script(before, "CustomItemPropertyTextVarList").splitlines()
    if len(lines) < 32:
        raise NativeP3ColorTestInstallError("CustomItemPropertyTextVarList现有1至32行不完整")
    last_line = entries[-1][0]
    while len(lines) < last_line:
        lines.append("")
    for line_no, value in entries:
        current = lines[line_no - 1].strip()
        if current and current != value:
            raise NativeP3ColorTestInstallError(f"CustomItemPropertyTextVarList第{line_no}行已被其他内容占用")
        lines[line_no - 1] = value
    return _encode_script(lines)


def _managed_insert(text: str, anchor: str, block_id: str, payload_lines: tuple[str, ...]) -> str:
    begin = f"; XY-MG-P3-BEGIN {block_id}"
    end = f"; XY-MG-P3-END {block_id}"
    block = "\r\n".join((begin, *payload_lines, end))
    if begin in text or end in text:
        if text.count(begin) == 1 and text.count(end) == 1 and block in text:
            return text
        raise NativeP3ColorTestInstallError(f"受管块{block_id}存在冲突或残缺")
    if text.count(anchor) != 1:
        raise NativeP3ColorTestInstallError(f"锚点{anchor}必须恰好出现一次")
    return text.replace(anchor, anchor + "\r\n" + block, 1)


def _repair_legacy_batch_apply_control(text: str) -> str:
    """把旧版平铺批量写入改成槽位标签内的无条件写入与收尾。"""
    start = "[@XY_MG_BATCH_APPLY]"
    end = "[@XY_MG_DRAW_TAIL]"
    if start not in text:
        return text
    if "[@XY_MG_BATCH_APPLY_SLOT_1]" in text:
        return text
    if text.count(start) != 1 or text.count(end) != 1:
        raise NativeP3ColorTestInstallError("原命格批量写入标签数量与当前版本基线不匹配")
    before, remainder = text.split(start, 1)
    legacy, after = remainder.split(end, 1)
    header = re.compile(
        r"(?:^|\r\n)#IF\r\nEQUAL N\$XY_MG_SLOT (\d+)\r\n#ACT\r\n"
    )
    matches = tuple(header.finditer(legacy))
    if not matches:
        raise NativeP3ColorTestInstallError("原命格批量写入缺少槽位分支")
    slots = tuple(int(match.group(1)) for match in matches)
    if slots != tuple(range(1, len(slots) + 1)):
        raise NativeP3ColorTestInstallError("原命格批量写入槽位顺序不连续")
    dispatcher: list[str] = [start]
    for slot in slots:
        dispatcher.extend((
            "#IF", f"EQUAL N$XY_MG_SLOT {slot}", "#ACT",
            f"GOTO @XY_MG_BATCH_APPLY_SLOT_{slot}", "BREAK",
        ))
    dispatcher.extend(("#IF", "#ACT", "MESSAGEBOX 当前命格槽位无效，未改变装备。", "BREAK"))
    slot_blocks: list[str] = []
    for index, (slot, match) in enumerate(zip(slots, matches)):
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(legacy)
        chunk = legacy[match.end():chunk_end].strip("\r\n")
        if len(re.findall(r"(?m)^LockUpdateItem \d+\r?$", chunk)) != 1:
            raise NativeP3ColorTestInstallError(f"原命格槽位{slot}写入锁数量异常")
        if len(re.findall(r"(?m)^UpdateItem \d+\r?$", chunk)) != 1:
            raise NativeP3ColorTestInstallError(f"原命格槽位{slot}刷新数量异常")
        if chunk.count("DELAYGOTO 50 @XY_MG_DRAW_TAIL") != 1:
            raise NativeP3ColorTestInstallError(f"原命格槽位{slot}收尾跳转数量异常")
        chunk = re.sub(
            r"(?m)^(LockUpdateItem \d+)(?=\r?$)", r"#IF\r\n#ACT\r\n\1", chunk, count=1
        )
        chunk = re.sub(
            r"(?m)^(UpdateItem \d+)(?=\r?$)", r"#IF\r\n#ACT\r\n\1", chunk, count=1
        )
        slot_blocks.append(
            "\r\n".join((f"[@XY_MG_BATCH_APPLY_SLOT_{slot}]", "#IF", "#ACT", chunk))
        )
    repaired = "\r\n".join((*dispatcher, *slot_blocks))
    return before + repaired + "\r\n" + end + after


def _patch_qfunction(before: bytes) -> bytes:
    text = _decode_script(before, "QFunction-0.txt").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    recalc_call = ("#IF", "#ACT", "#CALL [\\玄渊命格\\命格P3实例快速版.txt] @XY_MG_P3_RECALC_ALL")
    for event in ("PlayLogin", "TakeOnEx", "TakeOffEx"):
        text = _managed_insert(text, f"[@{event}]", f"RECALC_{event}", recalc_call)
    runtime_blocks = (
        ("; XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR", "TEXT33_MONSTER_ABSORB", ("#IF", "#ACT", "INC N$XY_MDA_Raw <$STR(N$XY_MG_P3_MONSTER_ABSORB)>")),
        ("; XY_EXECUTION_LAB_CHANCE_ANCHOR", "TEXT36_EXECUTION", ("#IF", "#ACT", "MOV N$XY_MG_P3_EVT <$STR(N$XY_MG_P3_EXECUTION_BP)>", "MUL N$XY_MG_P3_EVT 100", "INC N$XY_EXEC_ChanceBP <$STR(N$XY_MG_P3_EVT)>")),
        ("; XY_EQUIP_MAKER_CORPSE_ANCHOR", "TEXT37_CORPSE", ("#IF", "#ACT", "INC N$XY_CorpseRate <$STR(N$XY_MG_P3_CORPSE)>")),
        ("; XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR", "TEXT38_BLAST", ("#IF", "#ACT", "INC N$XY_RT_Blast <$STR(N$XY_MG_P3_BLAST)>")),
        ("; XY_EQUIP_MAKER_KILL_RESET", "TEXT39_TAIL", ("#IF", "#ACT", "INC N$XY_TailKillRate <$STR(N$XY_MG_P3_TAIL)>")),
        ("; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR", "BIND50_TOUGHNESS", ("#IF", "#ACT", "INC N$XY_EXEC_Toughness <$STR(N$XY_MG_P3_TOUGHNESS)>")),
        ("; XY_EXECUTION_LAB_PVE_BONUS_ANCHOR", "BIND51_EXECUTION_BONUS", ("#IF", "#ACT", "INC N$XY_EXEC_PVEEquipBonusPercent <$STR(N$XY_MG_P3_EXECUTION_BONUS)>")),
        ("; XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR", "BIND53_DAMAGE_COEFFICIENT", ("#IF", "#ACT", "INC N$XY_RT_DamageCoeff <$STR(N$XY_MG_P3_DAMAGE_COEFF)>")),
    )
    for anchor, block_id, lines in runtime_blocks:
        text = _managed_insert(text, anchor, block_id, lines)
    return text.encode("gb18030")


def _branch_key(candidate: NativeCandidate) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", candidate.candidate_id).upper()


def _aggregate_properties(candidates: tuple[NativeCandidate, ...]):
    result: list[object] = []
    seen: set[tuple[int, int, int | None, str]] = set()
    for candidate in candidates:
        for item in candidate.properties:
            if item.route not in {"direct", "script_bind"} and item.text_line != ATTACK_SPEED_TEXT_LINE:
                continue
            key = (item.binding, item.type3, item.type4, item.value_command)
            if key not in seen:
                seen.add(key)
                result.append(item)
    return tuple(result)


def _clear_item_row(row: int) -> tuple[str, ...]:
    return (
        f"SetCustomItemAbil 17 {row} 0 0", f"SetCustomItemAbil 17 {row} 1 0",
        f"SetCustomItemAbil 17 {row} 2 0", f"SetCustomItemAbil 17 {row} 3 0",
        f"SetCustomItemAbil 17 {row} 4 0", f"SetCustomItemValueEx 17 {row} = 0 0 0",
    )


def _candidate_increment_lines(candidate: NativeCandidate, candidate_index: int, aggregates: tuple[object, ...]) -> tuple[str, ...]:
    lines: list[str] = []
    aggregate_keys = {
        (item.binding, item.type3, item.type4, item.value_command): index + 1
        for index, item in enumerate(aggregates)
    }
    for item in candidate.properties:
        if item.route in {"direct", "script_bind"} or item.text_line == ATTACK_SPEED_TEXT_LINE:
            number = aggregate_keys[(item.binding, item.type3, item.type4, item.value_command)]
            lines.append(f"INC N$XY_MG_P4_SUM{number}A {item.value}")
            if item.value_command == "value_ex":
                lines.append(f"INC N$XY_MG_P4_SUM{number}B {item.value2}")
                lines.append(f"INC N$XY_MG_P4_SUM{number}C {item.value3}")
    return tuple(lines)


def _pool_lines(pool_name: str, candidates: tuple[NativeCandidate, ...]) -> tuple[str, ...]:
    lines: list[str] = [f"[@XY_MG_P4_POOL_{pool_name}]", "#IF", "#ACT"]
    if len(candidates) == 1:
        lines.extend((f"GOTO @XY_MG_P4_CHOOSE_{_branch_key(candidates[0])}", "BREAK", ""))
        return tuple(lines)
    lines.extend((f"GOTO @XY_MG_P4_POOL_{pool_name}_ROLL_1", "BREAK", ""))
    for index, candidate in enumerate(candidates[:-1], start=1):
        remaining = len(candidates) - index + 1
        lines.extend((
            f"[@XY_MG_P4_POOL_{pool_name}_ROLL_{index}]", "#IF", f"RANDOMEX 1 {remaining}", "#ACT",
            f"GOTO @XY_MG_P4_CHOOSE_{_branch_key(candidate)}", "BREAK", "#IF", "#ACT",
            f"GOTO @XY_MG_P4_POOL_{pool_name}_ROLL_{index + 1}", "BREAK", "",
        ))
    lines.extend((
        f"[@XY_MG_P4_POOL_{pool_name}_ROLL_{len(candidates)}]", "#IF", "#ACT",
        f"GOTO @XY_MG_P4_CHOOSE_{_branch_key(candidates[-1])}", "BREAK", "",
    ))
    return tuple(lines)


def _render_core_block(candidates: tuple[NativeCandidate, ...]) -> tuple[str, ...]:
    pools = _classify_candidates(candidates)
    entries = _candidate_text_var_entries(candidates)
    line_by_id = {candidate.candidate_id: line for candidate, (line, _) in zip(candidates, entries)}
    aggregates = _aggregate_properties(candidates)
    lines: list[str] = ["#IF", "#ACT", "GOTO @XY_MG_P4_SELECT_POOL", "BREAK", ""]
    lines.extend(("[@XY_MG_P4_SELECT_POOL]",))
    for quality, pool_name in enumerate(POOL_ORDER, start=1):
        lines.extend(("#IF", f"EQUAL N$XY_MG_QUALITY {quality}", "#ACT", f"GOTO @XY_MG_P4_POOL_{pool_name}", "BREAK"))
    lines.extend(("#IF", "#ACT", "MESSAGEBOX 本次洗练品质无法映射候选池，未改变装备。", "BREAK", ""))
    for pool_name in POOL_ORDER:
        lines.extend(_pool_lines(pool_name, pools[pool_name]))
    for candidate in candidates:
        line = line_by_id[candidate.candidate_id]
        color = candidate.segments[0].color
        lines.extend((
            f"[@XY_MG_P4_CHOOSE_{_branch_key(candidate)}]", "#IF", "#ACT",
            f"MOV N$XY_MG_P4_TEXT_LINE {line}", f"MOV N$XY_MG_P4_TEXT_COLOR {color}",
            f"MOV {PANEL_RESULT_VARIABLE} {_candidate_panel_markup(candidate)}",
            "GOTO @XY_MG_P4_DISPATCH_SLOT", "BREAK", "",
        ))
    lines.append("[@XY_MG_P4_DISPATCH_SLOT]")
    for slot in range(1, 9):
        lines.extend(("#IF", f"EQUAL N$XY_MG_SLOT {slot}", "#ACT", f"GOTO @XY_MG_P4_WRITE_SLOT_{slot}", "BREAK"))
    lines.extend(("#IF", "#ACT", "MESSAGEBOX 当前命格槽位无效，未改变装备。", "BREAK", ""))
    for slot in range(1, 9):
        row = slot + 8
        lines.extend((
            f"[@XY_MG_P4_WRITE_SLOT_{slot}]", "#IF", "CHECKUSEITEM 17", "EQUAL <$JADE> 鞭尸灵玉", "#ACT",
            "LockUpdateItem 17",
            f"SetCustomItemAbil 17 {row} 0 <$STR(N$XY_MG_P4_TEXT_COLOR)>",
            f"SetCustomItemAbil 17 {row} 1 60", f"SetCustomItemAbil 17 {row} 2 {slot}",
            f"SetCustomItemAbil 17 {row} 3 0", f"SetCustomItemAbil 17 {row} 4 9",
            f"SetCustomItemValueEx 17 {row} = <$STR(N$XY_MG_P4_TEXT_LINE)> 0 0",
            "GOTO @XY_MG_P4_REBUILD", "BREAK", "#ELSEACT",
            "MESSAGEBOX 点击后灵玉位置或名称已变化，未写入。", "BREAK", "",
        ))
    lines.extend(("[@XY_MG_P4_REBUILD]", "#IF", "#ACT"))
    for index in range(1, len(aggregates) + 1):
        lines.extend((f"MOV N$XY_MG_P4_SUM{index}A 0", f"MOV N$XY_MG_P4_SUM{index}B 0", f"MOV N$XY_MG_P4_SUM{index}C 0"))
    for slot in range(1, 9):
        lines.append(f"MOV N$XY_MG_P4_VALID{slot} 0")
    for slot in range(1, 9):
        row = slot + 8
        lines.append(f"GetCustomItemValueEx 17 {row} N$XY_MG_P4_TMPP N$XY_MG_P4_SLOT{slot} N$XY_MG_P4_TMPB N$XY_MG_P4_TMPC")
    for slot in range(1, 9):
        for candidate_index, candidate in enumerate(candidates, start=1):
            increments = _candidate_increment_lines(candidate, candidate_index, aggregates)
            lines.extend((
                "#IF", f"EQUAL N$XY_MG_P4_SLOT{slot} {line_by_id[candidate.candidate_id]}", "#ACT",
                f"MOV N$XY_MG_P4_VALID{slot} 1", *increments,
            ))
    for slot in range(1, 9):
        lines.extend(("#IF", f"EQUAL N$XY_MG_P4_VALID{slot} 0", "#ACT", *_clear_item_row(slot + 8)))
    for row in range(1, 9):
        lines.extend(_clear_item_row(row))
    for row in (17, 18, 19):
        lines.extend(_clear_item_row(row))
    for row, item in enumerate(aggregates, start=1):
        lines.extend((
            f"SetCustomItemAbil 17 {row} 0 250", f"SetCustomItemAbil 17 {row} 1 {item.binding}",
            f"SetCustomItemAbil 17 {row} 2 {item.position}", f"SetCustomItemAbil 17 {row} 3 {item.type3}",
        ))
        if item.type4 is not None:
            lines.append(f"SetCustomItemAbil 17 {row} 4 {item.type4}")
        if item.text_line == ATTACK_SPEED_TEXT_LINE:
            lines.append(f"SetCustomItemValueEx 17 {row} = {ATTACK_SPEED_TEXT_LINE} <$STR(N$XY_MG_P4_SUM{row}A)> 0")
        elif item.value_command == "value_ex":
            lines.append(f"SetCustomItemValueEx 17 {row} = <$STR(N$XY_MG_P4_SUM{row}A)> <$STR(N$XY_MG_P4_SUM{row}B)> <$STR(N$XY_MG_P4_SUM{row}C)>")
        else:
            lines.append(f"SetCustomItemValue 17 {row} = <$STR(N$XY_MG_P4_SUM{row}A)>")
    lines.extend((
        "MOV S$XY_MG_P4_EMPTY", "SetCustomItemText 17 <$STR(S$XY_MG_P4_EMPTY)>",
        "SetCustomItemTextColor 17 255", "UpdateItem 17",
        "#CALL [\\玄渊命格\\命格P3实例快速版.txt] @XY_MG_P3_RECALC_ALL",
    ))
    if any(item.text_line == ATTACK_SPEED_TEXT_LINE for candidate in candidates for item in candidate.properties):
        lines.append(ATTACK_SPEED_CALL)
    lines.extend(("DELAYGOTO 50 @XY_MG_PANEL_ROUTE", "BREAK"))
    return tuple(lines)


def _patch_original_core(before: bytes, candidates: tuple[NativeCandidate, ...]) -> bytes:
    text = _decode_script(before, "命格核心.txt").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    state_lines = (
        "#IF", f"NOT EQUAL {PROGRESS_SCHEMA_FLAG} {PROGRESS_SCHEMA_VERSION}", "#ACT",
        *(f"MOV {counter} 0" for counter in OWNED_PROGRESS_COUNTERS),
        f"MOV {PROGRESS_SCHEMA_FLAG} {PROGRESS_SCHEMA_VERSION}",
        "#IF", "#ACT", f"MOV {PANEL_RESULT_VARIABLE} {PANEL_DEFAULT}",
    )
    text = _managed_insert(
        text, "[@XY_MG_MAIN]\r\n{", "ORIGINAL_UI_STATE_INIT", state_lines
    )
    lines = text.split("\r\n")
    if lines.count("RANDOM 50") != 1 or lines.count("RANDOM 10") != 2:
        raise NativeP3ColorTestInstallError("原命格品质随机命令数量与当前版本基线不匹配")
    lines = [
        "RANDOMEX 1 50" if line == "RANDOM 50"
        else "RANDOMEX 1 10" if line == "RANDOM 10"
        else line
        for line in lines
    ]
    text = "\r\n".join(lines)
    text = _repair_legacy_batch_apply_control(text)
    if text.count(PANEL_PLACEHOLDER) != 9:
        raise NativeP3ColorTestInstallError("原命格右侧结果占位数量与当前版本基线不匹配")
    text = text.replace(PANEL_PLACEHOLDER, f"<$STR({PANEL_RESULT_VARIABLE})>")
    return _managed_insert(text, "[@XY_MG_DRAW_TAIL]", "ORIGINAL_UI_APPLY", _render_core_block(candidates)).encode("gb18030")


def _render_test_script(candidates: tuple[NativeCandidate, ...]) -> bytes:
    entries = _candidate_text_var_entries(candidates)
    line_by_id = {candidate.candidate_id: line for candidate, (line, _) in zip(candidates, entries)}
    body = [
        "[@XY_MG_P3_RECALC_ALL]", "{", "#IF", "#ACT",
        "MOV N$XY_MG_P3_MONSTER_ABSORB 0", "MOV N$XY_MG_P3_TAO_PERCENT 0",
        "MOV N$XY_MG_P3_FATAL 0", "MOV N$XY_MG_P3_EXECUTION_BP 0",
        "MOV N$XY_MG_P3_CORPSE 0", "MOV N$XY_MG_P3_BLAST 0", "MOV N$XY_MG_P3_TAIL 0",
        "MOV N$XY_MG_P3_TOUGHNESS 0", "MOV N$XY_MG_P3_EXECUTION_BONUS 0",
        "MOV N$XY_MG_P3_DAMAGE_COEFF 0",
        "#IF", "CHECKUSEITEM 17", "EQUAL <$JADE> 鞭尸灵玉", "#ACT", "GOTO @XY_MG_P3_READ_SLOTS", "BREAK",
        "#ELSEACT", "GOTO @XY_MG_P3_APPLY_HUMAN", "BREAK", "",
        "[@XY_MG_P3_READ_SLOTS]", "#IF", "#ACT",
    ]
    for slot in range(1, 9):
        body.append(f"GetCustomItemValueEx 17 {slot + 8} N$XY_MG_P3_TMPP N$XY_MG_P3_SLOT{slot} N$XY_MG_P3_TMPB N$XY_MG_P3_TMPC")
    for slot in range(1, 9):
        for candidate in candidates:
            runtime = [
                item for item in candidate.properties
                if item.route == "textline_runtime" and item.text_line != ATTACK_SPEED_TEXT_LINE
                or (item.route == "script_bind" and item.binding in SCRIPT_BIND_RUNTIME_VARIABLES)
            ]
            if not runtime:
                continue
            body.extend(("#IF", f"EQUAL N$XY_MG_P3_SLOT{slot} {line_by_id[candidate.candidate_id]}", "#ACT"))
            for item in runtime:
                variable = (
                    RUNTIME_VARIABLES[item.text_line]
                    if item.route == "textline_runtime"
                    else SCRIPT_BIND_RUNTIME_VARIABLES[item.binding]
                )
                body.append(f"INC {variable} {item.value}")
    body.extend((
        "[@XY_MG_P3_APPLY_HUMAN]", "#IF", "#ACT",
        "ChangeHumAbility 9 = 0", "ChangeHumAbility 10 = 0",
        "MOV N$XY_MG_P3_TAO_LOW 0", "MOV N$XY_MG_P3_TAO_HIGH 0",
        "CalcPercent <$SC> <$STR(N$XY_MG_P3_TAO_PERCENT)> N$XY_MG_P3_TAO_LOW",
        "CalcPercent <$MAXSC> <$STR(N$XY_MG_P3_TAO_PERCENT)> N$XY_MG_P3_TAO_HIGH",
        "ChangeHumAbility 9 + <$STR(N$XY_MG_P3_TAO_LOW)>",
        "ChangeHumAbility 10 + <$STR(N$XY_MG_P3_TAO_HIGH)>",
        "AddHumNewValue 22 = <$STR(N$XY_MG_P3_FATAL)>", "BREAK", "}",
    ))
    payload = _encode_script(body)
    text = payload.decode("gb18030")
    upper = text.upper()
    forbidden = (
        "GAMEGOLD", "GAMEPOINT", "RANDOM", "LINKGIVEITEM", "SQL ", "MIR.DB", "UPDATE STDITEMS",
    )
    if any(token in upper for token in forbidden):
        raise NativeP3ColorTestInstallError("P3运行时重算脚本包含数据库、付费、随机或发物品禁用命令")
    return payload


def _attack_speed_dependency_blockers(candidates: tuple[NativeCandidate, ...], server: Path) -> list[str]:
    if not any(
        item.text_line == ATTACK_SPEED_TEXT_LINE
        for candidate in candidates
        for item in candidate.properties
    ):
        return []
    blockers: list[str] = []
    core_path = server / Path(ATTACK_SPEED_CORE_RELATIVE)
    if not core_path.is_file():
        blockers.append("攻速突破依赖核心缺失")
    else:
        try:
            core = _decode_script(core_path.read_bytes(), "攻速突破核心")
        except (OSError, NativeP3ColorTestInstallError) as exc:
            blockers.append(f"攻速突破依赖核心不可读取：{exc}")
        else:
            if core.count("[@XY_AS_CAP_RECALC]") != 1 or "GetAllCustomItemValueByTextLine 60 -1 40 " not in core:
                blockers.append("攻速突破依赖核心缺少TextLine40统一重算接口")
    textvar_path = server / Path(TEXTVAR_RELATIVE)
    try:
        text_lines = _decode_script(textvar_path.read_bytes(), "CustomItemPropertyTextVarList").splitlines()
    except (OSError, NativeP3ColorTestInstallError) as exc:
        blockers.append(f"攻速突破依赖TextVar40不可读取：{exc}")
    else:
        if len(text_lines) < ATTACK_SPEED_TEXT_LINE or text_lines[ATTACK_SPEED_TEXT_LINE - 1].strip() != ATTACK_SPEED_TEXT:
            blockers.append("攻速突破依赖TextVar40合同缺失")
    qfunction_path = server / Path(QFUNCTION_RELATIVE)
    try:
        qfunction = _decode_script(qfunction_path.read_bytes(), "QFunction-0.txt")
    except (OSError, NativeP3ColorTestInstallError) as exc:
        blockers.append(f"攻速突破依赖QFunction不可读取：{exc}")
    else:
        if qfunction.count("; XY-AS-CAP-V1-BEGIN") != 1 or qfunction.count("; XY-AS-CAP-V1-END") != 1:
            blockers.append("攻速突破依赖QFunction受管接口缺失或重复")
    return blockers


def _control_blocker(platform_root: Path, server_root: Path) -> list[str]:
    blockers: list[str] = []
    for label, path in (
        ("active", _active_path(platform_root, server_root)),
        ("coordination", _coordination_path(platform_root, server_root)),
    ):
        if path.exists():
            blockers.append(f"当前服务端已有P3颜色活动{label}状态，必须先回滚P3，才可回滚P2或再次安装")
    return blockers


def plan_native_p3_color_test_install(
    workbook_path: Path,
    server_root: Path,
    platform_root: Path,
) -> NativeP3ColorInstallPlan:
    """只读预检V3四颜色候选及正式P2三文件哈希。"""
    book = read_native_candidate_workbook(Path(workbook_path), derive_v3_segments=True)
    server_entry = Path(server_root).absolute()
    server = server_entry.resolve()
    blockers = _candidate_blockers(book.candidates)
    if _is_reparse_point(server_entry):
        blockers.append("服务端根目录不能是符号链接、联接或重解析点")
    blockers.extend(_baseline_blockers(server))
    blockers.extend(_attack_speed_dependency_blockers(book.candidates, server))
    blockers.extend(_control_blocker(platform_root, server))
    planned_payloads: list[tuple[str, bytes, bytes]] = []
    targets = {
        TEST_SCRIPT_RELATIVE: server / Path(TEST_SCRIPT_RELATIVE),
        TEXTVAR_RELATIVE: server / Path(TEXTVAR_RELATIVE),
        QFUNCTION_RELATIVE: server / Path(QFUNCTION_RELATIVE),
        CORE_RELATIVE: server / Path(CORE_RELATIVE),
    }
    before_payloads = {relative: path.read_bytes() if path.is_file() else b"" for relative, path in targets.items()}
    text_var_entries = _candidate_text_var_entries(book.candidates)
    try:
        generated = {
            TEST_SCRIPT_RELATIVE: _render_test_script(book.candidates),
            TEXTVAR_RELATIVE: _append_text_vars(before_payloads[TEXTVAR_RELATIVE], text_var_entries),
            QFUNCTION_RELATIVE: _patch_qfunction(before_payloads[QFUNCTION_RELATIVE]),
            CORE_RELATIVE: _patch_original_core(before_payloads[CORE_RELATIVE], book.candidates),
        }
    except NativeP3ColorTestInstallError as exc:
        blockers.append(str(exc))
        generated = dict(before_payloads)
    for relative, target in targets.items():
        planned_payloads.append((relative, before_payloads[relative], generated[relative]))
    candidate_literals = tuple(compile_native_candidate(item).segment_literal for item in book.candidates)
    workbook_hash = _sha256_bytes(book.source.read_bytes())
    candidate_hash = _candidate_fingerprint(book.candidates)
    identity = "|".join((
        workbook_hash,
        candidate_hash,
        str(server).casefold(),
        *(_sha256_bytes(before) for _, before, _ in planned_payloads),
        *(_sha256_bytes(after) for _, _, after in planned_payloads),
    ))
    return NativeP3ColorInstallPlan(
        plan_id=_sha256_bytes(identity.encode("utf-8"))[:24],
        workbook=book.source,
        workbook_sha256=workbook_hash,
        candidate_spec_sha256=candidate_hash,
        candidate_ids=tuple(item.candidate_id for item in book.candidates),
        candidate_literals=candidate_literals,
        server_root=server,
        files=tuple(NativeP3ColorPlannedFile(
            relative_path=relative,
            path=targets[relative],
            before_sha256=_sha256_bytes(before) if before else "",
            after_sha256=_sha256_bytes(after),
            after=after,
        ) for relative, before, after in planned_payloads),
        text_var_entries=text_var_entries,
        qfunction_anchor_plan=QFUNCTION_ANCHOR_PLAN,
        npc_entry_plan=NPC_ENTRY_PLAN,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=(
            "服务端正式写入由总负责人执行；本计划不新增地图3龙魂觉醒NPC注册",
            "TextVar从33行起按候选生成完整名称与属性，QFunction按受管锚点接入，冲突时阻止",
            "事务文件为P3重算后台、TextVar、QFunction和原命格核心同文件八槽块；NPC包装与MerChant逐字节不改",
            "39号表候选按绿/蓝/红/彩分池，原界面八个槽位分别保存TextVar候选标识",
            "文件回滚不能恢复已经写入鞭尸灵玉实例的最后一次命格属性",
        ),
    )


def _assert_plan_current(plan: NativeP3ColorInstallPlan, platform_root: Path) -> None:
    if plan.blockers:
        raise NativeP3ColorTestInstallError("P3安装计划存在阻断：" + "；".join(plan.blockers))
    expected_relatives = (TEST_SCRIPT_RELATIVE, TEXTVAR_RELATIVE, QFUNCTION_RELATIVE, CORE_RELATIVE)
    if tuple(item.relative_path for item in plan.files) != expected_relatives:
        raise NativeP3ColorTestInstallError("P3计划必须包含后台脚本、TextVar、QFunction和原命格核心四文件")
    for planned in plan.files:
        expected_path = plan.server_root / Path(planned.relative_path)
        if planned.path.absolute() != expected_path.absolute():
            raise NativeP3ColorTestInstallError(f"P3计划目标路径不符合合同：{planned.relative_path}")
        current_hash = _current_hash(planned.path) or ""
        if current_hash != planned.before_sha256:
            raise NativeP3ColorTestInstallError(f"P3目标在预检后发生哈希漂移：{planned.relative_path}")
        if planned.after_sha256 != _sha256_bytes(planned.after):
            raise NativeP3ColorTestInstallError(f"P3计划内容与哈希不匹配：{planned.relative_path}")
    fresh = plan_native_p3_color_test_install(plan.workbook, plan.server_root, platform_root)
    if fresh.blockers or fresh.plan_id != plan.plan_id:
        raise NativeP3ColorTestInstallError("P3四文件计划在预检后发生变化：" + "；".join(fresh.blockers))


def _read_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise NativeP3ColorTestInstallError(f"P3{label}缺失：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeP3ColorTestInstallError(f"P3{label}无法解析：{path}") from exc
    if not isinstance(value, dict):
        raise NativeP3ColorTestInstallError(f"P3{label}不是对象")
    return value


def install_native_p3_color_test(
    plan: NativeP3ColorInstallPlan,
    platform_root: Path,
) -> NativeP3ColorInstallReceipt:
    """在P2全局互斥下事务安装P3后台和原界面受管接点。"""
    _assert_plan_current(plan, platform_root)
    try:
        lock = _p2_transaction_lock(platform_root, plan.server_root)
        with lock:
            _assert_plan_current(plan, platform_root)
            base = _transaction_base(platform_root, create=True)
            transaction_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
            transaction = base / transaction_id
            if transaction.exists():
                raise NativeP3ColorTestInstallError(f"P3事务目录已存在：{transaction}")
            files_dir = transaction / "files"
            files_dir.mkdir(parents=True)
            manifest_files: list[dict[str, object]] = []
            before_payloads: dict[str, bytes | None] = {}
            for index, planned in enumerate(plan.files):
                existed_before = planned.path.is_file()
                before = planned.path.read_bytes() if existed_before else None
                before_hash = _sha256_bytes(before) if before is not None else ""
                if before_hash != planned.before_sha256:
                    raise NativeP3ColorTestInstallError(
                        f"P3目标在预检后发生哈希漂移：{planned.relative_path}"
                    )
                before_payloads[planned.relative_path] = before
                backup_relative_path: str | None = None
                backup_sha256 = ""
                if before is not None:
                    backup_relative_path = f"files/{index:02d}.before.bin"
                    backup_sha256 = before_hash
                    _atomic_write(transaction / backup_relative_path, before)
                manifest_files.append({
                    "relative_path": planned.relative_path,
                    "existed_before": existed_before,
                    "before_sha256": before_hash,
                    "after_sha256": planned.after_sha256,
                    "backup_relative_path": backup_relative_path,
                    "backup_sha256": backup_sha256,
                })
            manifest = {
                "schema_version": 2,
                "operation": "mingge-native-p3-color-test-install",
                "transaction_id": transaction_id,
                "server_root": str(plan.server_root),
                "workbook": str(plan.workbook),
                "workbook_sha256": plan.workbook_sha256,
                "candidate_spec_sha256": plan.candidate_spec_sha256,
                "files": manifest_files,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            manifest_payload = _canonical_json(manifest)
            manifest_sha256 = _sha256_bytes(manifest_payload)
            _atomic_write(transaction / "manifest.json", manifest_payload)
            _atomic_write(transaction / "manifest.sha256", (manifest_sha256 + "\n").encode("ascii"))
            receipt_path = transaction / "receipt.json"
            _atomic_write(receipt_path, _canonical_json({
                "schema_version": 1,
                "operation": "mingge-native-p3-color-test-install",
                "status": "prepared",
                "transaction_id": transaction_id,
                "files": [item.relative_path for item in plan.files],
            }))
            active_path = _active_path(platform_root, plan.server_root)
            coordination_path = _coordination_path(platform_root, plan.server_root)
            try:
                for planned in plan.files:
                    _atomic_write(planned.path, planned.after)
                    if _current_hash(planned.path) != planned.after_sha256:
                        raise NativeP3ColorTestInstallError(
                            f"P3安装后文件哈希不匹配：{planned.relative_path}"
                        )
                control = {
                    "schema_version": 2,
                    "transaction_id": transaction_id,
                    "server_root": str(plan.server_root),
                    "manifest_sha256": manifest_sha256,
                    "files": [item.relative_path for item in plan.files],
                    "state": "active",
                }
                _atomic_write(active_path, _canonical_json(control))
                _atomic_write(coordination_path, _canonical_json(control))
                _atomic_write(receipt_path, _canonical_json({
                    "schema_version": 2,
                    "operation": "mingge-native-p3-color-test-install",
                    "status": "installed-test-candidate",
                    "transaction_id": transaction_id,
                    "files": [item.relative_path for item in plan.files],
                    "manifest_sha256": manifest_sha256,
                }))
            except Exception as exc:
                restore_errors: list[str] = []
                for planned in reversed(plan.files):
                    before = before_payloads[planned.relative_path]
                    try:
                        if before is None:
                            if planned.path.exists():
                                planned.path.unlink()
                        else:
                            _atomic_write(planned.path, before)
                        if (_current_hash(planned.path) or "") != planned.before_sha256:
                            restore_errors.append(planned.relative_path)
                    except Exception:
                        restore_errors.append(planned.relative_path)
                for control_path in (active_path, coordination_path):
                    try:
                        current = _read_json(control_path, "失败恢复控制状态") if control_path.exists() else {}
                        if current.get("transaction_id") == transaction_id:
                            control_path.unlink()
                    except Exception:
                        pass
                if restore_errors:
                    raise NativeP3ColorTestInstallError(
                        "P3安装失败且自动恢复不完整：" + "、".join(restore_errors)
                    ) from exc
                raise
            return NativeP3ColorInstallReceipt(
                transaction_id=transaction_id,
                status="installed-test-candidate",
                receipt_path=receipt_path,
                files=tuple(item.relative_path for item in plan.files),
            )
    except NativeP2TestInstallError as exc:
        raise NativeP3ColorTestInstallError(str(exc)) from exc


def rollback_native_p3_color_test(
    platform_root: Path,
    transaction_id: str,
    server_root: Path,
) -> NativeP3ColorRollbackReceipt:
    """哈希守卫恢复TextVar、QFunction和原命格核心，并删除新建后台。"""
    if not TRANSACTION_ID.fullmatch(transaction_id):
        raise NativeP3ColorTestInstallError("P3事务ID格式非法")
    server = Path(server_root).resolve()
    try:
        lock = _p2_transaction_lock(platform_root, server)
        with lock:
            base = _transaction_base(platform_root)
            transaction = base / transaction_id
            if transaction.parent.resolve(strict=False) != base.resolve(strict=False):
                raise NativeP3ColorTestInstallError("P3事务目录越界")
            manifest_path = transaction / "manifest.json"
            manifest_payload = manifest_path.read_bytes() if manifest_path.is_file() else b""
            recorded_manifest_hash = (
                (transaction / "manifest.sha256").read_text(encoding="ascii").strip()
                if (transaction / "manifest.sha256").is_file() else ""
            )
            manifest_hash = _sha256_bytes(manifest_payload)
            if not manifest_payload or recorded_manifest_hash != manifest_hash:
                raise NativeP3ColorTestInstallError("P3 manifest哈希守卫失败")
            manifest = _read_json(manifest_path, "manifest")
            if (
                manifest.get("schema_version") != 2
                or manifest.get("operation") != "mingge-native-p3-color-test-install"
                or manifest.get("transaction_id") != transaction_id
                or manifest.get("server_root") != str(server)
            ):
                raise NativeP3ColorTestInstallError("P3 manifest事务合同不匹配")
            entries = manifest.get("files")
            if not isinstance(entries, list) or len(entries) != 4:
                raise NativeP3ColorTestInstallError("P3 manifest必须包含四个文件条目")
            expected_relatives = (TEST_SCRIPT_RELATIVE, TEXTVAR_RELATIVE, QFUNCTION_RELATIVE, CORE_RELATIVE)
            if tuple(entry.get("relative_path") for entry in entries if isinstance(entry, dict)) != expected_relatives:
                raise NativeP3ColorTestInstallError("P3 manifest文件顺序或路径不匹配")
            active_path = _active_path(platform_root, server)
            coordination_path = _coordination_path(platform_root, server)
            active = _read_json(active_path, "active")
            coordination = _read_json(coordination_path, "coordination")
            for label, control in (("active", active), ("coordination", coordination)):
                if (
                    control.get("transaction_id") != transaction_id
                    or control.get("server_root") != str(server)
                    or control.get("manifest_sha256") != manifest_hash
                    or control.get("state") != "active"
                ):
                    raise NativeP3ColorTestInstallError(f"P3{label}活动归属或哈希守卫不匹配")
            merchant_hash = _current_hash(server / Path(MERCHANT_RELATIVE))
            expected_merchant = EXPECTED_P2_HASHES.get(MERCHANT_RELATIVE)
            if expected_merchant is not None and merchant_hash != expected_merchant.lower():
                raise NativeP3ColorTestInstallError("P3回滚前MerChant发生漂移，保持零覆盖")

            restore_payloads: dict[str, bytes | None] = {}
            installed_payloads: dict[str, bytes] = {}
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise NativeP3ColorTestInstallError("P3 manifest文件条目格式非法")
                relative = str(entry["relative_path"])
                target = server / Path(relative)
                try:
                    _assert_no_reparse_path(target, server)
                except NativeP2TestInstallError as exc:
                    raise NativeP3ColorTestInstallError(str(exc)) from exc
                after_hash = str(entry.get("after_sha256") or "")
                if _current_hash(target) != after_hash:
                    raise NativeP3ColorTestInstallError(f"P3文件在回滚前发生未知漂移：{relative}")
                installed_payloads[relative] = target.read_bytes()
                existed_before = entry.get("existed_before") is True
                before_hash = str(entry.get("before_sha256") or "")
                if existed_before:
                    expected_backup = transaction / "files" / f"{index:02d}.before.bin"
                    backup_value = entry.get("backup_relative_path")
                    backup = transaction / str(backup_value or "")
                    if backup.resolve(strict=False) != expected_backup.resolve(strict=False) or not backup.is_file():
                        raise NativeP3ColorTestInstallError(f"P3备份缺失或路径不匹配：{relative}")
                    before = backup.read_bytes()
                    if _sha256_bytes(before) != before_hash or _sha256_bytes(before) != entry.get("backup_sha256"):
                        raise NativeP3ColorTestInstallError(f"P3备份哈希不匹配：{relative}")
                    restore_payloads[relative] = before
                else:
                    if before_hash or entry.get("backup_relative_path") not in (None, ""):
                        raise NativeP3ColorTestInstallError(f"P3新建文件的manifest状态非法：{relative}")
                    restore_payloads[relative] = None

            restored: list[str] = []
            try:
                for entry in reversed(entries):
                    relative = str(entry["relative_path"])
                    target = server / Path(relative)
                    before = restore_payloads[relative]
                    if before is None:
                        target.unlink()
                    else:
                        _atomic_write(target, before)
                    restored.append(relative)
                for entry in entries:
                    relative = str(entry["relative_path"])
                    if (_current_hash(server / Path(relative)) or "") != str(entry.get("before_sha256") or ""):
                        raise NativeP3ColorTestInstallError(f"P3回滚后哈希不匹配：{relative}")
            except Exception as exc:
                recovery_errors: list[str] = []
                for relative in restored:
                    try:
                        _atomic_write(server / Path(relative), installed_payloads[relative])
                    except Exception:
                        recovery_errors.append(relative)
                if recovery_errors:
                    raise NativeP3ColorTestInstallError(
                        "P3回滚失败且恢复活动版本不完整：" + "、".join(recovery_errors)
                    ) from exc
                raise
            active_path.unlink()
            coordination_path.unlink()
            rollback_path = transaction / "rollback-receipt.json"
            _atomic_write(rollback_path, _canonical_json({
                "schema_version": 2,
                "operation": "mingge-native-p3-color-test-rollback",
                "status": "rolled-back",
                "transaction_id": transaction_id,
                "restored_files": [str(entry["relative_path"]) for entry in entries],
                "p2_stack_order": "P3 rolled back before P2 rollback",
            }))
            return NativeP3ColorRollbackReceipt(transaction_id, "rolled-back", rollback_path)
    except NativeP2TestInstallError as exc:
        raise NativeP3ColorTestInstallError(str(exc)) from exc
