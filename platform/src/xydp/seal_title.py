from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .encoding import TextDocument, encode_text_document, read_text_document
from .initial_camp import (
    InitialCampError,
    NATIVE_CURRENCY_HELP,
    NATIVE_CURRENCY_SPECS,
    _consistent_first,
    _decode_document,
    _enable_setup_flags,
    _integer,
    _merge_named_description_lines,
    _npc_name,
    _script_token,
    _text,
    read_workbook,
)
from .installer import InstallError, InstallPlan, Installer, PlannedChange
from .repository import PackageRepository
from .sqlitepatch import SqlitePatchError, apply_sqlite_upsert
from .target import TargetInspector
from .textpatch import (
    TextPatchError,
    ensure_event_label,
    install_event_hook,
    install_managed_anchor_hook,
    scan_labels,
    set_exclusive_unique_line,
)


SEAL_WORKBOOK = "21_神印基础属性.xlsx"
TITLE_WORKBOOK = "22_称号晋升.xlsx"
EXPECTED_FILES = (SEAL_WORKBOOK, TITLE_WORKBOOK)
PACKAGE_ID = "xy.lab.seal-title-v2"
PACKAGE_VERSION = "2.1.0-candidate.2"
OPERATION = "seal-title-two-npc"
DEFAULT_MAP = "XY_NMGF_MAIN"
DEFAULT_CENTER = (100, 75)
SEAL_VARIABLE = "XY_SEAL_BASE_LEVEL"
SEAL_STATE_RELATIVE = "Mir200/Envir/QuestDiary/XY_System/XuanYuanHumanVar.txt"
SEAL_LEGACY_STATE_RELATIVE = "Mir200/Envir/Market_Def/XY_Seal_Base_Level.txt"
SEAL_STATE_SCRIPT_PATH = r"..\QuestDiary\XY_System\XuanYuanHumanVar.txt"
SEAL_SCRIPT_PATH = "玄渊成长/神印修行"
TITLE_SCRIPT_PATH = "玄渊成长/称号晋升"
SEAL_CORE_RELATIVE = "Mir200/Envir/QuestDiary/玄渊成长/神印与称号/神印基础核心.txt"
TITLE_CORE_RELATIVE = "Mir200/Envir/QuestDiary/玄渊成长/神印与称号/称号晋升核心.txt"
QFUNCTION_RELATIVE = "Mir200/Envir/Market_Def/QFunction-0.txt"
QMANAGE_RELATIVE = "Mir200/Envir/MapQuest_Def/QManage.txt"
MERCHANT_RELATIVE = "Mir200/Envir/MerChant.txt"
DB_RELATIVE = "Mud2/DB/ApexM2.DB"
ITEMDESC_RELATIVE = "Mir200/Envir/ItemDescList.txt"
SETUP_RELATIVE = "Mir200/!setup.txt"
SEAL_COLUMNS = ("攻击", "魔法", "道术", "HP")
TITLE_COLUMNS = ("攻击", "魔法", "道术", "HP", "MP", "基础爆率")
SEAL_LEVEL_COUNT = 200
TITLE_LEVEL_COUNT = 10
ABILITY_IDS = {"攻击": (5, 6), "魔法": (7, 8), "道术": (9, 10), "HP": (11,)}
NATIVE_LINGFU = {"灵符", "账户灵符", "原生灵符"}
TITLE_PAYMENT_MODES = {"同时支付", "二选一", "二选一B免材料"}


class SealTitleError(ValueError):
    pass


def _material_cost_lines(row: dict[str, object]) -> tuple[list[str], list[str]]:
    checks: list[str] = []
    actions: list[str] = []
    for name_key, count_key in (("材料A", "材料A数量"), ("材料B", "材料B数量")):
        name = _text(row.get(name_key))
        count = _integer(row.get(count_key), 0) or 0
        if count < 0 or bool(name) != (count > 0):
            raise SealTitleError(f"{name_key}与{count_key}必须同时填写正数")
        if not name:
            continue
        token = _script_token(name, name_key)
        native = NATIVE_CURRENCY_SPECS.get(token)
        if native is not None:
            _cost_type, _display, check, action = native
            checks.append(check.format(amount=count, threshold=count - 1))
            actions.append(action.format(amount=count, threshold=count - 1))
        else:
            checks.append(f"CHECKITEM {token} {count}")
            actions.append(f"TAKE {token} {count}")
    return checks, actions


def _currency_cost_line(
    row: dict[str, object],
    suffix: str,
) -> tuple[str, str, str] | None:
    name_key = f"货币{suffix}"
    count_key = f"货币{suffix}数量"
    name = _text(row.get(name_key))
    count = _integer(row.get(count_key), 0) or 0
    if count < 0 or bool(name) != (count > 0):
        raise SealTitleError(f"{name_key}与{count_key}必须同时填写正数")
    if not name:
        return None
    token = _script_token(name, name_key)
    native = NATIVE_CURRENCY_SPECS.get(token)
    if native is None:
        raise SealTitleError(
            f"{name_key}只允许填写原生货币：{NATIVE_CURRENCY_HELP}；"
            f"普通背包物品请填写到材料A/材料B，当前值：{token}"
        )
    _cost_type, display, check, action = native
    return (
        display,
        check.format(amount=count, threshold=count - 1),
        action.format(amount=count, threshold=count - 1),
    )


def _payment_mode(row: dict[str, object]) -> str:
    mode = _text(row.get("支付方式")) or "同时支付"
    if mode not in TITLE_PAYMENT_MODES:
        raise SealTitleError("支付方式只允许填写：同时支付、二选一、二选一B免材料")
    if mode in {"二选一", "二选一B免材料"}:
        route_a = _currency_cost_line(row, "A")
        route_b = _currency_cost_line(row, "B")
        if route_a is None or route_b is None:
            raise SealTitleError("支付方式为二选一时，货币A和货币B必须都填写名称与正数数量")
        if route_a[0] == route_b[0]:
            raise SealTitleError("支付方式为二选一时，货币A和货币B必须是两种不同的原生货币")
    return mode


def _cost_lines(row: dict[str, object]) -> tuple[list[str], list[str]]:
    checks, actions = _material_cost_lines(row)
    for suffix in ("A", "B"):
        route = _currency_cost_line(row, suffix)
        if route is None:
            continue
        _display, check, action = route
        checks.append(check)
        actions.append(action)
    return checks, actions


def _title_payment_routes(
    row: dict[str, object],
) -> tuple[tuple[str, str, list[str], list[str]], ...]:
    mode = _payment_mode(row)
    if mode == "同时支付":
        checks, actions = _cost_lines(row)
        return (("", "确认晋升", checks, actions),)

    material_checks, material_actions = _material_cost_lines(row)
    routes: list[tuple[str, str, list[str], list[str]]] = []
    for suffix in ("A", "B"):
        route = _currency_cost_line(row, suffix)
        assert route is not None
        display, check, action = route
        include_materials = mode == "二选一" or suffix == "A"
        routes.append(
            (
                suffix,
                f"使用{display}晋升",
                [*material_checks, check] if include_materials else [check],
                [*material_actions, action] if include_materials else [action],
            )
        )
    return tuple(routes)


def _cost_summary(row: dict[str, object]) -> str:
    _cost_lines(row)
    parts: list[str] = []
    for name_key, count_key in (
        ("材料A", "材料A数量"), ("材料B", "材料B数量"),
        ("货币A", "货币A数量"), ("货币B", "货币B数量"),
    ):
        name = _text(row.get(name_key))
        count = _integer(row.get(count_key), 0) or 0
        if name and count:
            native = NATIVE_CURRENCY_SPECS.get(name)
            parts.append(f"{native[1] if native is not None else name}×{count}")
    if not parts:
        raise SealTitleError("可安装档位必须至少填写一组材料或货币")
    return "、".join(parts)


def _cost_group_summary(
    row: dict[str, object],
    pairs: tuple[tuple[str, str], ...],
) -> str:
    _cost_lines(row)
    parts: list[str] = []
    for name_key, count_key in pairs:
        name = _text(row.get(name_key))
        count = _integer(row.get(count_key), 0) or 0
        if name and count:
            native = NATIVE_CURRENCY_SPECS.get(name)
            parts.append(f"{native[1] if native is not None else name}×{count}")
    return "、".join(parts) or "无"


@dataclass(frozen=True)
class SealTitleNpc:
    feature_id: str
    name: str
    script_path: str
    map_code: str
    x: int
    y: int
    appearance: int
    state: str
    reuse_existing: bool = False


@dataclass
class SealTitlePlan:
    server: str
    materials: str
    materials_hash: str = ""
    client: str | None = None
    npcs: list[SealTitleNpc] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    install_plan: InstallPlan | None = None
    operation: str = OPERATION


def _expected_count(filename: str) -> int:
    return SEAL_LEVEL_COUNT if filename == SEAL_WORKBOOK else TITLE_LEVEL_COUNT


def _sheet_state(filename: str, rows: tuple[dict[str, object], ...]) -> str:
    expected = _expected_count(filename)
    if len(rows) != expected:
        raise SealTitleError(f"{filename}：必须保留完整{expected}档，当前为{len(rows)}档")
    states = [_text(row.get("状态")) for row in rows]
    unknown = sorted(set(states) - {"待配置", "可安装"})
    if unknown:
        raise SealTitleError(f"{filename}：状态只允许待配置或可安装，发现：{'、'.join(unknown)}")
    if set(states) == {"待配置"}:
        return "待配置"
    if set(states) == {"可安装"}:
        return "可安装"
    raise SealTitleError(f"{filename}：{expected}档状态必须全部待配置或全部可安装，禁止半套启用")


def _levels(filename: str, rows: tuple[dict[str, object], ...]) -> list[int]:
    expected = _expected_count(filename)
    levels: list[int] = []
    for row_number, row in enumerate(rows, 2):
        value = _integer(row.get("档位/等级"))
        if value is None:
            raise SealTitleError(f"{filename}：第{row_number}行档位/等级不能为空")
        levels.append(value)
    if levels != list(range(1, expected + 1)):
        raise SealTitleError(f"{filename}：档位/等级必须严格为1到{expected}且不可断层")
    return levels


def _nonnegative_values(
    filename: str,
    rows: tuple[dict[str, object], ...],
    columns: tuple[str, ...],
) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    previous = {column: 0 for column in columns}
    for index, row in enumerate(rows, 1):
        values: dict[str, int] = {}
        for column in columns:
            value = _integer(row.get(column))
            if value is None or value < 0:
                raise SealTitleError(f"{filename}：第{index}档{column}必须填写非负整数")
            if value < previous[column]:
                raise SealTitleError(
                    f"{filename}：第{index}档{column}总值{value}低于上一档{previous[column]}"
                )
            values[column] = value
        checks, _actions = _cost_lines(row)
        if not checks:
            raise SealTitleError(f"{filename}：第{index}档标为可安装，但没有填写材料或货币")
        _cost_summary(row)
        result.append(values)
        previous = values
    return result


def _summary(values: dict[str, int], *, include_mp: bool = False, include_drop: bool = False) -> str:
    parts = [
        f"攻击+{values['攻击']}-{values['攻击']}",
        f"魔法+{values['魔法']}-{values['魔法']}",
        f"道术+{values['道术']}-{values['道术']}",
        f"HP+{values['HP']}",
    ]
    if include_mp:
        parts.append(f"MP+{values['MP']}")
    if include_drop:
        parts.append(f"基础爆率+{values['基础爆率']}%")
    return "；".join(parts)


def _pending_core(label: str, npc_name: str) -> str:
    return (
        f"[@{label}]\n{{\n#IF\n#SAY\n【{npc_name}】材料表尚未配置完整，当前功能暂不开放。\\\n"
        "<关闭/@exit>\n}\n"
    )


def _validate_self_contained_npc(body: str, source_label: str) -> None:
    """Validate the exact script contract accepted by the current LFM2 server."""
    normalized = body.replace("\r\n", "\n")
    if re.search(r"(?im)^\s*[{}]\s*$", normalized):
        raise SealTitleError("自包含NPC脚本仍含独立花括号行，拒绝生成")
    executable_calls = [
        line for line in normalized.splitlines()
        if line.strip() and not line.lstrip().startswith(";") and line.lstrip().upper().startswith("#CALL")
    ]
    if executable_calls:
        raise SealTitleError("自包含NPC脚本仍含可执行#CALL，拒绝生成")
    labels = re.findall(r"(?im)^\s*\[@([^\]]+)\]\s*$", normalized)
    if labels.count("Main") != 1 or source_label in labels:
        raise SealTitleError("自包含NPC脚本必须且只能保留一个[@Main]")
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise SealTitleError("自包含NPC脚本存在重复标签：" + "、".join(duplicates))
    label_set = set(labels)
    goto_targets = re.findall(r"(?im)\bGOTO\s+@([A-Za-z0-9_]+)", normalized)
    button_targets = [
        target for target in re.findall(r"/@([A-Za-z0-9_]+)", normalized)
        if target.casefold() != "exit"
    ]
    missing = sorted({target for target in (*goto_targets, *button_targets) if target not in label_set})
    if missing:
        raise SealTitleError("自包含NPC脚本存在缺失目标：" + "、".join(missing))


def _self_contained_npc(core_body: str, source_label: str, npc_name: str) -> str:
    """Expand the canonical core into the Market_Def NPC accepted in candidate.7."""
    normalized = core_body.replace("\r\n", "\n")
    if len(re.findall(r"(?im)^\s*\{\s*$", normalized)) != 1 or len(
        re.findall(r"(?im)^\s*\}\s*$", normalized)
    ) != 1:
        raise SealTitleError(f"{npc_name}核心脚本外层花括号数量异常，拒绝展开")
    normalized = re.sub(r"(?im)^\s*[{}]\s*\n?", "", normalized)
    normalized = re.sub(
        rf"(?im)^\s*\[@{re.escape(source_label)}\]\s*$",
        "[@Main]",
        normalized,
    )
    normalized = re.sub(
        rf"(?i)(\bGOTO\s+)@{re.escape(source_label)}\b",
        r"\1@Main",
        normalized,
    )
    body = (
        f"; {npc_name}正式自包含NPC；由平台核心母版生成，不依赖跨目录#CALL。\n"
        + normalized.rstrip("\n")
        + "\n"
    )
    _validate_self_contained_npc(body, source_label)
    return body


def _replace_existing_npc_block(text: str, kind: str, desired: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"^; XYDP-NPC-BEGIN {re.escape(PACKAGE_ID)} {re.escape(kind)} SHA256=([0-9a-f]{{64}})\r?\n"
        rf"(.*?)^; XYDP-NPC-END {re.escape(PACKAGE_ID)} {re.escape(kind)}(?=[ \t]*\r?$)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    begin_token = f"XYDP-NPC-BEGIN {PACKAGE_ID} {kind}"
    end_token = f"XYDP-NPC-END {PACKAGE_ID} {kind}"
    if match is None:
        if begin_token in text or end_token in text:
            raise SealTitleError(f"现有NPC的{kind}受管块标记不完整，拒绝覆盖")
        return text, False
    body = match.group(2).replace("\r\n", "\n").rstrip("\n") + "\n"
    if hashlib.sha256(body.encode("gb18030")).hexdigest() != match.group(1):
        raise SealTitleError(f"现有NPC的{kind}受管块已被手工修改，拒绝覆盖")
    return text[:match.start()] + desired + text[match.end():], True


def _is_candidate7_self_contained(text: str, kind: str, source_label: str) -> bool:
    begin = f"; XYDP-CANDIDATE7-BEGIN {PACKAGE_ID} {kind}"
    end = f"; XYDP-CANDIDATE7-END {PACKAGE_ID} {kind}"
    if begin not in text and end not in text:
        return False
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) >= text.index(end):
        raise SealTitleError(f"candidate.7的{kind}标记不完整，拒绝升级")
    body = text[text.index(begin) + len(begin):text.index(end)].lstrip("\r\n")
    _validate_self_contained_npc(body, source_label)
    return True


def _bind_title_to_existing_npc(text: str, desired: bytes) -> bytes:
    if f"XYDP-FILE-BEGIN {PACKAGE_ID} title-self-contained" in text:
        _validate_existing_managed_file(text.encode("gb18030"), "title-self-contained", desired)
        return desired
    if _is_candidate7_self_contained(text, "title-self-contained", "XY_TITLE_ADVANCE_MAIN"):
        return desired

    result, had_direct = _replace_existing_npc_block(text, "title-direct-main", "")
    if had_direct:
        if result.strip().casefold() != "[@main]":
            raise SealTitleError("神树赐福旧直接入口之外仍有未知内容，拒绝整体升级")
        return desired

    result, had_menu = _replace_existing_npc_block(result, "title-menu", "")
    result, had_entry = _replace_existing_npc_block(result, "title-entry", "")
    if had_menu != had_entry:
        raise SealTitleError("神树赐福旧称号菜单与入口不成对，拒绝自动迁移")

    main_matches = list(re.finditer(r"(?im)^\s*\[@Main\]\s*$", result))
    if len(main_matches) != 1:
        raise SealTitleError(f"神树赐福脚本必须且只能包含一个[@Main]，当前为{len(main_matches)}个")
    start = main_matches[0].end()
    next_label = re.search(r"(?im)^\s*\[@[^\]]+\]\s*$", result[start:])
    end = start + next_label.start() if next_label else len(result)
    section_lines = [line.strip() for line in result[start:end].splitlines() if line.strip()]
    greeting_ok = (
        len(section_lines) == 3
        and section_lines[0].casefold() == "#say"
        and re.fullmatch(r"愿神树的赐福与你同在。[\\ ]*", section_lines[1]) is not None
        and section_lines[2].casefold() == "<关闭/@exit>"
    )
    if not greeting_ok:
        raise SealTitleError("神树赐福原[@Main]不是已确认的欢迎语结构，拒绝替换为直接称号界面")
    if result[:start].strip().casefold() != "[@main]" or result[end:].strip():
        raise SealTitleError("神树赐福欢迎语之外仍有未知内容，拒绝整体升级")
    return desired


def _seal_core(rows: tuple[dict[str, object], ...], npc_name: str) -> str:
    if _sheet_state(SEAL_WORKBOOK, rows) == "待配置":
        return _pending_core("XY_SEAL_BASE_MAIN", npc_name)
    _levels(SEAL_WORKBOOK, rows)
    values = _nonnegative_values(SEAL_WORKBOOK, rows, SEAL_COLUMNS)
    lines = [
        "[@XY_SEAL_BASE_MAIN]", "{",
        "#IF", f"CHECKVAR HUMAN {SEAL_VARIABLE} < 0", "#ACT", "GOTO @XY_SEAL_BASE_INVALID", "BREAK", "",
        "#IF", f"CHECKVAR HUMAN {SEAL_VARIABLE} = {SEAL_LEVEL_COUNT}", "#ACT", "GOTO @XY_SEAL_BASE_FULL", "BREAK", "",
    ]
    for threshold in range(20, SEAL_LEVEL_COUNT + 1, 20):
        lines += [
            "#IF", f"CHECKVAR HUMAN {SEAL_VARIABLE} < {threshold}", "#ACT",
            f"GOTO @XY_SEAL_BASE_ROUTE_{threshold - 20}_{threshold - 1}", "BREAK", "",
        ]
    lines += ["#IF", "#ACT", "GOTO @XY_SEAL_BASE_INVALID", "BREAK", "}", ""]

    for start in range(0, SEAL_LEVEL_COUNT, 20):
        end = start + 19
        lines.append(f"[@XY_SEAL_BASE_ROUTE_{start}_{end}]")
        for current in range(start, end + 1):
            lines += [
                "#IF", f"CHECKVAR HUMAN {SEAL_VARIABLE} = {current}", "#ACT",
                f"GOTO @XY_SEAL_BASE_VIEW_{current + 1}", "BREAK", "",
            ]
        lines += ["#IF", "#ACT", "GOTO @XY_SEAL_BASE_INVALID", "BREAK", ""]

    previous = {column: 0 for column in SEAL_COLUMNS}
    for index, (row, total) in enumerate(zip(rows, values), 1):
        checks, actions = _cost_lines(row)
        deltas = {column: total[column] - previous[column] for column in SEAL_COLUMNS}
        current_summary = "未修行" if index == 1 else _summary(previous)
        lines += [
            f"[@XY_SEAL_BASE_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            "<> <神印修行：/FCOLOR=158> <只显示当前可进行的下一档/FCOLOR=218>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> <当前阶段:/FCOLOR=161>{{{index - 1}档/SCOLOR=249}}\\",
            f"<> <当前总值:/FCOLOR=161>{{{current_summary}/SCOLOR=249}}\\",
            f"<> <下一阶段:/FCOLOR=161>{{{index}档/SCOLOR=253}}\\",
            f"<> <下一总值:/FCOLOR=161>{{{_summary(total)}/SCOLOR=147}}\\",
            f"<> <所需资源:/FCOLOR=161>{{{_cost_summary(row)}/SCOLOR=251}}\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> 【<确认修行/@XY_SEAL_BASE_APPLY_{index}>】　<关闭/@exit>\\", "",
            f"[@XY_SEAL_BASE_APPLY_{index}]", "#IF", f"CHECKVAR HUMAN {SEAL_VARIABLE} = {index - 1}", *checks,
            "#ACT", f"CALCVAR HUMAN {SEAL_VARIABLE} = {index}",
            f"SAVEVAR HUMAN {SEAL_VARIABLE} {SEAL_STATE_SCRIPT_PATH}",
        ]
        for column in SEAL_COLUMNS:
            for ability_id in ABILITY_IDS[column]:
                if deltas[column]:
                    lines.append(f"ChangeHumAbilityEX {ability_id} + {deltas[column]}")
        lines += [
            *actions,
            f"SENDMSG 6 [神印修行] 已提升至{index}档。",
            "GOTO @XY_SEAL_BASE_MAIN",
            "BREAK",
            "#ELSEACT",
            "MESSAGEBOX 锻体所需的物品或货币不足，请备齐后再来。",
            "BREAK",
            "",
        ]
        previous = total

    lines += [
        "[@XY_SEAL_BASE_FULL]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        "<> <神印修行：/FCOLOR=158> <当前已经达到最高档/FCOLOR=218>\\",
        f"<> <最终总值:/FCOLOR=161>{{{_summary(values[-1])}/SCOLOR=253}}\\",
        "<> <关闭/@exit>\\", "",
        "[@XY_SEAL_BASE_INVALID]", "#IF", "#SAY",
        "修行记录异常，请联系游戏管理员。\\", "<关闭/@exit>",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _title_configured(
    rows: tuple[dict[str, object], ...],
) -> tuple[list[dict[str, int]], list[str], list[int]]:
    _levels(TITLE_WORKBOOK, rows)
    values = _nonnegative_values(TITLE_WORKBOOK, rows, TITLE_COLUMNS)
    titles: list[str] = []
    shapes: list[int] = []
    for index, row in enumerate(rows, 1):
        title = _script_token(row.get("称号名称"), f"称号晋升第{index}档称号名称")
        shape = _integer(row.get("称号编号"))
        if shape is None or not 0 <= shape <= 255:
            raise SealTitleError(f"称号晋升第{index}档称号编号必须是0到255")
        titles.append(title)
        shapes.append(shape)
    if len(set(titles)) != TITLE_LEVEL_COUNT:
        raise SealTitleError("22_称号晋升.xlsx：10档称号名称必须唯一")
    if len(set(shapes)) != TITLE_LEVEL_COUNT:
        raise SealTitleError("22_称号晋升.xlsx：10档称号编号必须唯一")
    return values, titles, shapes


def _title_core(rows: tuple[dict[str, object], ...], npc_name: str) -> str:
    if _sheet_state(TITLE_WORKBOOK, rows) == "待配置":
        return _pending_core("XY_TITLE_ADVANCE_MAIN", npc_name)
    values, titles, _shapes = _title_configured(rows)
    lines = ["[@XY_TITLE_ADVANCE_MAIN]", "{"]
    for index in range(TITLE_LEVEL_COUNT - 1, -1, -1):
        target = (
            "@XY_TITLE_ADVANCE_FULL"
            if index == TITLE_LEVEL_COUNT - 1
            else f"@XY_TITLE_ADVANCE_VIEW_{index + 2}"
        )
        lines += ["#IF", f"CHECKFENGHAO {titles[index]}", "#ACT", f"GOTO {target}", "BREAK", ""]
    lines += ["#IF", "#ACT", "GOTO @XY_TITLE_ADVANCE_VIEW_1", "BREAK", "}", ""]

    for index, (row, total, title) in enumerate(zip(rows, values, titles), 1):
        previous = titles[index - 2] if index > 1 else ""
        current_display = previous or "无"
        payment_mode = _payment_mode(row)
        payment_routes = _title_payment_routes(row)
        material_summary = _cost_group_summary(
            row, (("材料A", "材料A数量"), ("材料B", "材料B数量"))
        )
        currency_all_summary = _cost_group_summary(
            row, (("货币A", "货币A数量"), ("货币B", "货币B数量"))
        )
        currency_a_summary = _cost_group_summary(row, (("货币A", "货币A数量"),))
        currency_b_summary = _cost_group_summary(row, (("货币B", "货币B数量"),))
        material_label = "货币A路线材料" if payment_mode == "二选一B免材料" else "需要材料"
        lines += [
            f"[@XY_TITLE_ADVANCE_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            "<> <称号晋升：/FCOLOR=158> <当前只显示下一档/FCOLOR=218>\\",
            f"<> <当前称号:/FCOLOR=161>{{{current_display}/SCOLOR=249}}\\",
            f"<> <下一级称号:/FCOLOR=161>{{{index}档（{title}）/SCOLOR=253}}\\",
            f"<> <{material_label}:/FCOLOR=161>{{{material_summary}/SCOLOR=251}}\\",
        ]
        if payment_mode in {"二选一", "二选一B免材料"}:
            payment_description = (
                "货币A需材料；货币B免材料"
                if payment_mode == "二选一B免材料"
                else "二选一，任选一种"
            )
            lines += [
                f"<> <支付方式:/FCOLOR=161>{{{payment_description}/SCOLOR=253}}\\",
                f"<> <货币A:/FCOLOR=161>{{{currency_a_summary}/SCOLOR=251}}　<货币B:/FCOLOR=161>{{{currency_b_summary}/SCOLOR=251}}\\",
            ]
        else:
            lines.append(f"<> <需要货币:/FCOLOR=161>{{{currency_all_summary}/SCOLOR=251}}\\")
        lines += [
            f"<> <攻魔道:/FCOLOR=161>{{攻击+{total['攻击']}-{total['攻击']}；魔法+{total['魔法']}-{total['魔法']}；道术+{total['道术']}-{total['道术']}/SCOLOR=147}}\\",
            f"<> <生命爆率:/FCOLOR=161>{{HP+{total['HP']}；MP+{total['MP']}；基础爆率+{total['基础爆率']}%/SCOLOR=147}}\\",
        ]
        buttons = "　".join(
            f"【<{label}/@XY_TITLE_ADVANCE_APPLY_{index}{'_' + code if code else ''}>】"
            for code, label, _checks, _actions in payment_routes
        )
        lines += [f"<> {buttons}　<关闭/@exit>\\", ""]

        for route_code, _label, checks, actions in payment_routes:
            suffix = f"_{route_code}" if route_code else ""
            lines += [f"[@XY_TITLE_ADVANCE_APPLY_{index}{suffix}]", "#IF"]
            if previous:
                lines.append(f"CHECKFENGHAO {previous}")
            for current_or_higher in titles[index - 1:]:
                lines.append(f"NOT CHECKFENGHAO {current_or_higher}")
            lines += [
                *checks,
                "#ACT",
                f"GIVEFENGHAO {title} 1",
                f"GOTO @XY_TITLE_ADVANCE_CONFIRM_{index}{suffix}",
                "BREAK",
                "#ELSEACT",
                "MESSAGEBOX 晋升所需的物品或货币不足，请备齐后再来。",
                "BREAK",
                "",
                f"[@XY_TITLE_ADVANCE_CONFIRM_{index}{suffix}]",
                "#IF",
                f"CHECKFENGHAO {title}",
            ]
            if previous:
                lines.append(f"CHECKFENGHAO {previous}")
            lines += [*checks, "#ACT", *actions]
            if previous:
                lines.append(f"RECYCFENGHAO {previous}")
            lines += [
                f"SENDMSG 6 [称号晋升] 已晋升为{title}。",
                "GOTO @XY_TITLE_ADVANCE_MAIN",
                "BREAK",
                "#ELSEACT",
                f"RECYCFENGHAO {title}",
                "MESSAGEBOX 称号晋升未能完成，请稍后再试；本次未消耗物品和货币。",
                "BREAK",
                "",
            ]

    lines += [
        "[@XY_TITLE_ADVANCE_FULL]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        "<> <称号晋升：/FCOLOR=158> <当前已经达到最高档/FCOLOR=218>\\",
        f"<> <最高称号:/FCOLOR=161>{{{titles[-1]}/SCOLOR=253}}\\",
        f"<> <完整属性:/FCOLOR=161>{{{_summary(values[-1], include_mp=True, include_drop=True)}/SCOLOR=147}}\\",
        "<> <关闭/@exit>\\",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _managed_file(kind: str, body: str) -> bytes:
    body = body.replace("\r\n", "\n").rstrip("\n") + "\n"
    digest = hashlib.sha256(body.encode("gb18030")).hexdigest()
    text = (
        f"; XYDP-FILE-BEGIN {PACKAGE_ID} {kind} SHA256={digest}\n"
        f"{body}"
        f"; XYDP-FILE-END {PACKAGE_ID} {kind}\n"
    )
    return text.replace("\n", "\r\n").encode("gb18030")


def _validate_existing_managed_file(data: bytes | None, kind: str, desired: bytes) -> None:
    if data is None or data == desired:
        return
    document = _decode_document(data)
    legacy_kinds = {
        "seal-self-contained": ("seal-wrapper",),
        "title-self-contained": ("title-wrapper",),
    }.get(kind, ())
    match = None
    matched_kind = kind
    for accepted_kind in (kind, *legacy_kinds):
        pattern = re.compile(
            rf"^; XYDP-FILE-BEGIN {re.escape(PACKAGE_ID)} {re.escape(accepted_kind)} SHA256=([0-9a-f]{{64}})\r?\n"
            rf"(.*?)^; XYDP-FILE-END {re.escape(PACKAGE_ID)} {re.escape(accepted_kind)}\s*$",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(document.text)
        if match:
            matched_kind = accepted_kind
            break
    if not match and kind == "seal-self-contained" and _is_candidate7_self_contained(
        document.text, "seal-self-contained", "XY_SEAL_BASE_MAIN"
    ):
        return
    if not match and kind == "title-self-contained" and _is_candidate7_self_contained(
        document.text, "title-self-contained", "XY_TITLE_ADVANCE_MAIN"
    ):
        return
    if not match:
        raise SealTitleError(f"目标已有非平台受管的{kind}文件，拒绝覆盖")
    body = match.group(2).replace("\r\n", "\n").rstrip("\n") + "\n"
    if hashlib.sha256(body.encode("gb18030")).hexdigest() != match.group(1):
        desired_document = _decode_document(desired)
        desired_pattern = re.compile(
            rf"^; XYDP-FILE-BEGIN {re.escape(PACKAGE_ID)} {re.escape(kind)} SHA256=([0-9a-f]{{64}})\r?\n"
            rf"(.*?)^; XYDP-FILE-END {re.escape(PACKAGE_ID)} {re.escape(kind)}\s*$",
            re.MULTILINE | re.DOTALL,
        )
        desired_match = desired_pattern.search(desired_document.text)
        desired_body = (
            desired_match.group(2).replace("\r\n", "\n").rstrip("\n") + "\n"
            if desired_match else None
        )
        if body != desired_body:
            raise SealTitleError(f"目标{matched_kind}受管文件已被手工修改，拒绝升级或覆盖")


def _map_file_from_info(text: str, map_code: str) -> str:
    matches: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*\[\s*([^|\s\]]+)(?:\|([^\s\]]+))?\s+", line, re.IGNORECASE)
        if match and match.group(1).casefold() == map_code.casefold():
            matches.append((match.group(2) or map_code) + ".map")
    if len(matches) != 1:
        raise SealTitleError(f"MapInfo中地图代码{map_code}匹配到{len(matches)}行")
    return matches[0]


def _geometry(data: bytes, map_code: str) -> tuple[int, int, int]:
    if len(data) < 52:
        raise SealTitleError(f"地图{map_code}文件小于52字节")
    width, height = struct.unpack_from("<HH", data, 0)
    for cell_size in (12, 14, 36):
        if len(data) == 52 + width * height * cell_size:
            return width, height, cell_size
    raise SealTitleError(f"地图{map_code}格式不是支持的type0/type2/type3")


def _walkable(data: bytes, width: int, height: int, cell_size: int, x: int, y: int) -> bool:
    if not (1 <= x < width - 1 and 1 <= y < height - 1):
        return False
    offset = 52 + (x * height + y) * cell_size
    front = struct.unpack_from("<H", data, offset + 4)[0]
    door = data[offset + 6] & 0x7F
    return not (front & 0x8000) and door == 0


def _occupied(merchant: str, map_code: str, own_paths: set[str]) -> tuple[set[tuple[int, int]], list[list[str]]]:
    points: set[tuple[int, int]] = set()
    other_rows: list[list[str]] = []
    for line in merchant.splitlines():
        fields = line.split("\t")
        if len(fields) < 5 or fields[0].casefold() in own_paths:
            continue
        other_rows.append(fields)
        if fields[1].casefold() == map_code.casefold():
            try:
                points.add((int(fields[2]), int(fields[3])))
            except ValueError:
                pass
    return points, other_rows


def _auto_point(
    data: bytes,
    width: int,
    height: int,
    cell_size: int,
    occupied: set[tuple[int, int]],
    map_code: str,
) -> tuple[int, int]:
    center = DEFAULT_CENTER if map_code.casefold() == DEFAULT_MAP.casefold() else (width // 2, height // 2)
    candidates: list[tuple[int, int]] = []
    for radius in range(2, max(width, height)):
        for dx in range(-radius, radius + 1):
            candidates.extend(((center[0] + dx, center[1] - radius), (center[0] + dx, center[1] + radius)))
        for dy in range(-radius + 1, radius):
            candidates.extend(((center[0] - radius, center[1] + dy), (center[0] + radius, center[1] + dy)))
        for point in candidates:
            if point not in occupied and _walkable(data, width, height, cell_size, *point):
                return point
        candidates.clear()
    raise SealTitleError(f"地图{map_code}找不到可走且未占用的NPC坐标")


def _title_item_values(title: str, shape: int, values: dict[str, int]) -> dict[str, object]:
    return {
        "Name": title, "StdMode": 70, "Shape": shape, "Weight": 0, "Anicount": 1,
        "Source": 0, "Reserved": 0, "Looks": shape * 5, "DuraMax": 0,
        "Ac": 0, "Ac2": 0, "Mac": 0, "Mac2": 0,
        "Dc": values["攻击"], "Dc2": values["攻击"],
        "Mc": values["魔法"], "Mc2": values["魔法"],
        "Sc": values["道术"], "Sc2": values["道术"],
        "Need": 0, "NeedLevel": 0, "Price": 0, "Stock": 0, "Color": 247,
        "OverLap": 0, "HP": values["HP"], "MP": values["MP"], "Light": 0, "Horse": 0,
    }


def _upsert_titles(database: bytes, rows: tuple[dict[str, object], ...]) -> bytes:
    values, titles, shapes = _title_configured(rows)
    for title, shape, totals in zip(titles, shapes, values):
        database = apply_sqlite_upsert(database, {
            "type": "sqlite_upsert", "table": "StdItems", "unique_key": ["Name"],
            "conflict_keys": [["StdMode", "Shape"]], "allocate": {"Idx": "max_plus_one"},
            "on_conflict": "error", "values": _title_item_values(title, shape, totals),
        })
    return database


def _title_description_lines(rows: tuple[dict[str, object], ...]) -> tuple[list[str], list[str]]:
    values, titles, _shapes = _title_configured(rows)
    itemdesc: list[str] = []
    fenghao: list[str] = []
    for total, title in zip(values, titles):
        summary = _summary(total, include_mp=True, include_drop=True)
        fenghao.append(f"{title}={summary}")
        itemdesc.append(
            f"{title}=\\242/　玄渊晋升称号\\-\\146/　[称号属性]："
            f"\\251/　攻击+{total['攻击']}-{total['攻击']}"
            f"\\251/　魔法+{total['魔法']}-{total['魔法']}"
            f"\\251/　道术+{total['道术']}-{total['道术']}"
            f"\\251/　HP+{total['HP']}\\251/　MP+{total['MP']}"
            f"\\251/　基础爆率+{total['基础爆率']}%"
        )
    return itemdesc, fenghao


def _drop_hooks(rows: tuple[dict[str, object], ...]) -> dict[str, str]:
    values, titles, _shapes = _title_configured(rows)

    def build(variable: str) -> str:
        lines: list[str] = []
        for total, title in zip(values, titles):
            if total["基础爆率"]:
                lines += ["#IF", f"CHECKFENGHAO {title}", "#ACT", f"INC {variable} {total['基础爆率']}"]
        return "\n".join(lines)

    return {
        "XY_EQUIP_MAKER_DROP_ANCHOR": build("N$XY_最终爆率"),
        "XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR": build("N$XY_RT_Drop"),
    }


class SealTitleService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        self.repository = PackageRepository(self.root / "packages")
        self.repository.refresh()
        self.installer = Installer(self.repository, self.root / "backups")

    @property
    def materials_root(self) -> Path:
        return self.root / "所需材料表格汇总"

    def load(self, materials: Path) -> dict[str, object]:
        root = Path(materials)
        missing = [name for name in EXPECTED_FILES if not (root / name).is_file()]
        if missing:
            raise SealTitleError("材料表缺失：" + "、".join(missing))
        return {name: read_workbook(root / name) for name in EXPECTED_FILES}

    @staticmethod
    def _add_change(
        changes: dict[str, PlannedChange],
        root: Path,
        relative: str,
        after: bytes,
        operation: str,
        *,
        scope: str = "server",
        managed_kind: str | None = None,
    ) -> None:
        key = relative if scope == "server" else f"client:{relative}"
        path = root / Path(relative.replace("/", "\\"))
        if key in changes:
            before = changes[key].before
        else:
            before = path.read_bytes() if path.exists() else None
        if managed_kind:
            _validate_existing_managed_file(before, managed_kind, after)
        changes[key] = PlannedChange(relative, before, after, operation, PACKAGE_ID, scope)

    def preflight(
        self,
        server: Path,
        materials: Path | None = None,
        client: Path | None = None,
    ) -> SealTitlePlan:
        materials = Path(materials or self.materials_root)
        plan = SealTitlePlan(str(Path(server).absolute()), str(materials.absolute()))
        try:
            books = self.load(materials)
            seal = books[SEAL_WORKBOOK]
            title = books[TITLE_WORKBOOK]
            seal_state = _sheet_state(SEAL_WORKBOOK, seal.rows)
            title_state = _sheet_state(TITLE_WORKBOOK, title.rows)
            _levels(SEAL_WORKBOOK, seal.rows)
            _levels(TITLE_WORKBOOK, title.rows)
            if seal_state == "可安装":
                _nonnegative_values(SEAL_WORKBOOK, seal.rows, SEAL_COLUMNS)
            if title_state == "可安装":
                _title_configured(title.rows)
            plan.materials_hash = hashlib.sha256((seal.sha256 + title.sha256).encode()).hexdigest()

            target = TargetInspector.inspect(Path(server))
            client_root: Path | None = None
            if title_state == "可安装":
                if client is None:
                    raise SealTitleError("称号晋升已配置，必须选择客户端以同步fenghao.dat")
                client_root = Path(client).resolve()
                if not client_root.is_dir():
                    raise SealTitleError(f"客户端目录不存在：{client_root}")
                plan.client = str(client_root)
            elif client is not None:
                candidate = Path(client).resolve()
                if candidate.is_dir():
                    client_root = candidate
                    plan.client = str(candidate)

            merchant_path = target.root / Path(MERCHANT_RELATIVE.replace("/", "\\"))
            merchant_doc = read_text_document(merchant_path) if merchant_path.exists() else TextDocument("", "gb18030", "\r\n")
            own_paths = {SEAL_SCRIPT_PATH.casefold(), TITLE_SCRIPT_PATH.casefold()}
            specs = (
                ("seal", SEAL_WORKBOOK, SEAL_SCRIPT_PATH, "神印修行", 222, seal.rows, seal_state),
                ("title", TITLE_WORKBOOK, TITLE_SCRIPT_PATH, "称号晋升", 226, title.rows, title_state),
            )
            map_cache: dict[str, tuple[bytes, int, int, int, set[tuple[int, int]], list[list[str]]]] = {}
            mapinfo = read_text_document(target.envir / "MapInfo.txt").text
            for feature_id, filename, script_path, default_name, default_appearance, rows, state in specs:
                name = _npc_name(_consistent_first(rows, "NPC名称", filename, default_name), filename)
                map_code = _text(_consistent_first(rows, "地图", filename, DEFAULT_MAP)) or DEFAULT_MAP
                appearance = _integer(_consistent_first(rows, "外观", filename, default_appearance))
                if appearance is None or appearance < 0:
                    raise SealTitleError(f"{filename}：外观必须是非负整数")
                if map_code.casefold() not in map_cache:
                    map_file = target.root / "Mir200" / "Map" / _map_file_from_info(mapinfo, map_code)
                    if not map_file.is_file():
                        raise SealTitleError(f"地图文件不存在：{map_file}")
                    data = map_file.read_bytes()
                    width, height, cell_size = _geometry(data, map_code)
                    occupied, other_rows = _occupied(merchant_doc.text, map_code, own_paths)
                    map_cache[map_code.casefold()] = (data, width, height, cell_size, occupied, other_rows)
                data, width, height, cell_size, occupied, other_rows = map_cache[map_code.casefold()]
                x = _integer(_consistent_first(rows, "X坐标", filename, "自动"))
                y = _integer(_consistent_first(rows, "Y坐标", filename, "自动"))
                if (x is None) != (y is None):
                    raise SealTitleError(f"{filename}：X/Y坐标必须同时填写或同时留空")
                own_rows = []
                for line in merchant_doc.text.splitlines():
                    fields = line.split("\t")
                    if len(fields) >= 7 and fields[0].casefold() == script_path.casefold():
                        own_rows.append(fields)
                if len(own_rows) > 1:
                    raise SealTitleError(f"{filename}：平台脚本路径存在重复NPC注册：{script_path}")
                if own_rows:
                    fields = own_rows[0]
                    if fields[1].casefold() != map_code.casefold() or fields[4] != name:
                        raise SealTitleError(f"{filename}：已安装平台NPC的地图或名称与表格不一致")
                    try:
                        actual_point = (int(fields[2]), int(fields[3]))
                        actual_appearance = int(fields[6])
                    except ValueError as exc:
                        raise SealTitleError(f"{filename}：已安装平台NPC的坐标或外观不是整数") from exc
                    if x is not None and y is not None and actual_point != (x, y):
                        raise SealTitleError(
                            f"{filename}：已安装平台NPC坐标{actual_point[0]},{actual_point[1]}"
                            f"与表格{x},{y}不一致"
                        )
                    if not _walkable(data, width, height, cell_size, *actual_point):
                        raise SealTitleError(
                            f"{filename}：已安装平台NPC坐标不可走 {actual_point[0]},{actual_point[1]}"
                        )
                    existing_script = target.envir / "Market_Def" / f"{fields[0]}-{map_code}.txt"
                    if not existing_script.is_file():
                        raise SealTitleError(f"{filename}：已安装平台NPC脚本不存在：{existing_script}")
                    existing_text = read_text_document(existing_script).text
                    managed_marker = f"XYDP-FILE-BEGIN {PACKAGE_ID} " in existing_text
                    candidate7_marker = (
                        feature_id == "seal"
                        and f"XYDP-CANDIDATE7-BEGIN {PACKAGE_ID} seal-self-contained" in existing_text
                    ) or (
                        feature_id == "title"
                        and f"XYDP-CANDIDATE7-BEGIN {PACKAGE_ID} title-self-contained" in existing_text
                    )
                    if not managed_marker and not candidate7_marker:
                        raise SealTitleError(
                            f"{filename}：脚本路径已注册但不是平台受管文件，拒绝接管：{existing_script}"
                        )
                    plan.npcs.append(
                        SealTitleNpc(
                            feature_id, name, fields[0], map_code, *actual_point,
                            actual_appearance, state, True,
                        )
                    )
                    if actual_appearance != int(appearance):
                        plan.warnings.append(
                            f"保留已安装NPC“{name}”当前外观{actual_appearance}；"
                            f"本轮入口修复不按表格外观{appearance}覆盖。"
                        )
                    continue
                same_name = [fields for fields in other_rows if len(fields) >= 7 and fields[4] == name]
                if same_name:
                    if feature_id != "title" or len(same_name) != 1:
                        raise SealTitleError(f"NPC名称已被其他注册占用：{name}")
                    fields = same_name[0]
                    if fields[1].casefold() != map_code.casefold():
                        raise SealTitleError(f"{filename}：现有{name}不在配置地图{map_code}")
                    if x is None or y is None:
                        raise SealTitleError(f"{filename}：复用现有{name}时必须明确填写X/Y坐标")
                    try:
                        actual_point = (int(fields[2]), int(fields[3]))
                        actual_appearance = int(fields[6])
                    except ValueError as exc:
                        raise SealTitleError(f"{filename}：现有{name}注册的坐标或外观不是整数") from exc
                    if actual_point != (x, y) or actual_appearance != int(appearance):
                        raise SealTitleError(
                            f"{filename}：现有{name}注册与表格不一致，实际"
                            f"{actual_point[0]},{actual_point[1]}/外观{actual_appearance}，"
                            f"表格{x},{y}/外观{appearance}"
                        )
                    if not _walkable(data, width, height, cell_size, *actual_point):
                        raise SealTitleError(f"{filename}：现有{name}坐标不可走 {actual_point[0]},{actual_point[1]}")
                    existing_script = target.envir / "Market_Def" / f"{fields[0]}-{map_code}.txt"
                    if not existing_script.is_file():
                        raise SealTitleError(f"{filename}：现有{name}脚本不存在：{existing_script}")
                    plan.npcs.append(
                        SealTitleNpc(
                            feature_id, name, fields[0], map_code, *actual_point,
                            actual_appearance, state, True,
                        )
                    )
                    continue
                point = _auto_point(data, width, height, cell_size, occupied, map_code) if x is None else (x, y)
                assert point[0] is not None and point[1] is not None
                point = (int(point[0]), int(point[1]))
                if point in occupied:
                    raise SealTitleError(f"{filename}：NPC坐标已占用 {point[0]},{point[1]}")
                if not _walkable(data, width, height, cell_size, *point):
                    raise SealTitleError(f"{filename}：NPC坐标不可走 {point[0]},{point[1]}")
                occupied.add(point)
                plan.npcs.append(SealTitleNpc(feature_id, name, script_path, map_code, *point, int(appearance), state))

            npc_by_id = {item.feature_id: item for item in plan.npcs}
            changes: dict[str, PlannedChange] = {}
            seal_core_body = _seal_core(seal.rows, npc_by_id["seal"].name)
            title_core_body = _title_core(title.rows, npc_by_id["title"].name)
            seal_core = _managed_file("seal-core", seal_core_body)
            title_core = _managed_file("title-core", title_core_body)
            seal_npc = _managed_file(
                "seal-self-contained",
                _self_contained_npc(seal_core_body, "XY_SEAL_BASE_MAIN", npc_by_id["seal"].name),
            )
            title_npc = _managed_file(
                "title-self-contained",
                _self_contained_npc(title_core_body, "XY_TITLE_ADVANCE_MAIN", npc_by_id["title"].name),
            )
            seal_wrapper_relative = f"Mir200/Envir/Market_Def/{SEAL_SCRIPT_PATH}-{npc_by_id['seal'].map_code}.txt"
            self._add_change(changes, target.root, SEAL_CORE_RELATIVE, seal_core, "generate-seal-core", managed_kind="seal-core")
            self._add_change(changes, target.root, TITLE_CORE_RELATIVE, title_core, "generate-title-core", managed_kind="title-core")
            self._add_change(
                changes, target.root, seal_wrapper_relative,
                seal_npc,
                "generate-seal-self-contained", managed_kind="seal-self-contained",
            )
            if npc_by_id["title"].reuse_existing:
                title_npc_relative = (
                    f"Mir200/Envir/Market_Def/{npc_by_id['title'].script_path}-"
                    f"{npc_by_id['title'].map_code}.txt"
                )
                title_npc_path = target.root / Path(title_npc_relative.replace("/", "\\"))
                title_npc_doc = read_text_document(title_npc_path)
                title_npc_bytes = _bind_title_to_existing_npc(title_npc_doc.text, title_npc)
                self._add_change(
                    changes, target.root, title_npc_relative,
                    title_npc_bytes,
                    "attach-title-to-existing-npc",
                )
                plan.warnings.append(
                    f"复用现有NPC“{npc_by_id['title'].name}”，点击NPC直接进入称号晋升界面。"
                )
            else:
                title_wrapper_relative = f"Mir200/Envir/Market_Def/{TITLE_SCRIPT_PATH}-{npc_by_id['title'].map_code}.txt"
                self._add_change(
                    changes, target.root, title_wrapper_relative,
                    title_npc,
                    "generate-title-self-contained", managed_kind="title-self-contained",
                )

            merchant_text = merchant_doc.text
            for npc in plan.npcs:
                if npc.reuse_existing:
                    continue
                line = f"{npc.script_path}\t{npc.map_code}\t{npc.x}\t{npc.y}\t{npc.name}\t0\t{npc.appearance}\t0"
                merchant_text = set_exclusive_unique_line(merchant_text, line, [0], merchant_doc.newline).text
            self._add_change(
                changes, target.root, MERCHANT_RELATIVE,
                encode_text_document(merchant_doc, merchant_text), "register-seal-title-npcs",
            )

            if seal_state == "可安装":
                seal_state_path = target.root / Path(SEAL_STATE_RELATIVE.replace("/", "\\"))
                if not seal_state_path.exists():
                    legacy_state_path = target.root / Path(
                        SEAL_LEGACY_STATE_RELATIVE.replace("/", "\\")
                    )
                    if legacy_state_path.is_file():
                        state_bytes = legacy_state_path.read_bytes()
                        plan.warnings.append(
                            "检测到旧神印状态文件：本次只复制到人物HUMAN统一状态文件，"
                            "不删除旧文件；以后不会覆盖新状态。"
                        )
                    else:
                        state_bytes = b"\xef\xbb\xbf"
                    self._add_change(
                        changes,
                        target.root,
                        SEAL_STATE_RELATIVE,
                        state_bytes,
                        "initialize-seal-human-state",
                    )

                qmanage_path = target.root / Path(QMANAGE_RELATIVE.replace("/", "\\"))
                qmanage_doc = read_text_document(qmanage_path)
                variable_lines = re.findall(rf"(?im)^\s*VAR\s+Integer\s+HUMAN\s+{re.escape(SEAL_VARIABLE)}\s*$", qmanage_doc.text)
                own_marker = f"XYDP-HOOK-BEGIN {PACKAGE_ID} Login" in qmanage_doc.text
                if variable_lines and not own_marker:
                    raise SealTitleError(f"人物变量{SEAL_VARIABLE}已被目标脚本占用")
                qmanage_text = ensure_event_label(qmanage_doc.text, PACKAGE_ID, "Login", qmanage_doc.newline).text
                login_body = (
                    "#IF\n"
                    "#ACT\n"
                    f"VAR Integer HUMAN {SEAL_VARIABLE}\n"
                    f"LOADVAR HUMAN {SEAL_VARIABLE} {SEAL_STATE_SCRIPT_PATH}"
                )
                qmanage_text = install_event_hook(
                    qmanage_text, PACKAGE_ID, "Login", login_body, qmanage_doc.newline
                ).text
                self._add_change(
                    changes, target.root, QMANAGE_RELATIVE,
                    encode_text_document(qmanage_doc, qmanage_text), "install-seal-login-state",
                )

            if title_state == "可安装":
                db_path = target.root / Path(DB_RELATIVE.replace("/", "\\"))
                if not db_path.is_file():
                    raise SealTitleError(f"目标缺少{DB_RELATIVE}")
                database = _upsert_titles(db_path.read_bytes(), title.rows)
                self._add_change(changes, target.root, DB_RELATIVE, database, "upsert-title-definitions")

                qfunction_path = target.root / Path(QFUNCTION_RELATIVE.replace("/", "\\"))
                qfunction_doc = read_text_document(qfunction_path)
                duplicates = scan_labels(qfunction_doc.text).duplicates
                if duplicates:
                    detail = "、".join(f"{name}:{lines}" for name, lines in duplicates.items())
                    raise SealTitleError(f"QFunction存在重复标签：{detail}")
                qfunction_text = qfunction_doc.text
                for anchor, content in _drop_hooks(title.rows).items():
                    qfunction_text = install_managed_anchor_hook(
                        qfunction_text, PACKAGE_ID, anchor, content, qfunction_doc.newline,
                        canonical_before_existing_hooks=True,
                    ).text
                self._add_change(
                    changes, target.root, QFUNCTION_RELATIVE,
                    encode_text_document(qfunction_doc, qfunction_text), "install-title-drop-hooks",
                )

                itemdesc, fenghao = _title_description_lines(title.rows)
                itemdesc_path = target.root / Path(ITEMDESC_RELATIVE.replace("/", "\\"))
                itemdesc_doc = read_text_document(itemdesc_path) if itemdesc_path.exists() else TextDocument("", "gb18030", "\r\n")
                self._add_change(
                    changes, target.root, ITEMDESC_RELATIVE,
                    _merge_named_description_lines(itemdesc_doc, itemdesc), "merge-title-itemdesc",
                )
                setup_path = target.root / Path(SETUP_RELATIVE.replace("/", "\\"))
                setup_doc = read_text_document(setup_path)
                self._add_change(
                    changes, target.root, SETUP_RELATIVE,
                    _enable_setup_flags(setup_doc, ("SendItemDescList", "SendTzItemDescList")),
                    "enable-title-descriptions",
                )
                assert client_root is not None
                candidate_paths = ("data/fenghao.dat", "Resources/fenghao.dat")
                existing = [relative for relative in candidate_paths if (client_root / Path(relative.replace("/", "\\"))).is_file()]
                for relative in existing or [candidate_paths[0]]:
                    path = client_root / Path(relative.replace("/", "\\"))
                    document = read_text_document(path) if path.exists() else TextDocument("", "gb18030", "\r\n")
                    self._add_change(
                        changes, client_root, relative,
                        _merge_named_description_lines(document, fenghao), "merge-title-fenghao", scope="client",
                    )

            real_changes = [item for item in changes.values() if item.before != item.after]
            plan.warnings.append(
                "神印与称号原有单档晋升链已通过当前服游戏验收；"
                "2.1.0新增货币二选一与货币B免材料路线仍为candidate，实际NPC继续采用自包含脚本，不依赖跨目录#CALL。"
            )
            if seal_state == "待配置":
                plan.warnings.append("21_神印基础属性.xlsx仍为待配置：NPC只显示待配置，不声明等级变量、不扣费、不加属性。")
            if title_state == "待配置":
                plan.warnings.append("22_称号晋升.xlsx仍为待配置：NPC只显示待配置，不修改数据库、爆率锚点或客户端称号说明。")
            plan.warnings.append("预检只生成内存计划；确认安装前会再次核对目标文件哈希，失败自动回滚。")
            plan.changes = real_changes
            plan.install_plan = InstallPlan(
                target_root=str(target.root), client_root=str(client_root) if client_root else None,
                package_ids=[PACKAGE_ID], package_versions={PACKAGE_ID: PACKAGE_VERSION},
                parameters={
                    "materials": str(materials.absolute()), "materials_hash": plan.materials_hash,
                    "seal_state": seal_state, "title_state": title_state,
                    "npcs": [asdict(item) for item in plan.npcs],
                    "skipped_formal_package": "xy.ops.title",
                    "verification_status": "candidate",
                },
                changes=real_changes, warnings=plan.warnings, operation_type=OPERATION,
                candidate_packages=[PACKAGE_ID],
            )
        except (OSError, ValueError, InstallError, InitialCampError, TextPatchError, SqlitePatchError, sqlite3.Error) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: SealTitlePlan):
        if plan.blockers or plan.install_plan is None:
            raise SealTitleError("神印与称号双NPC安装被阻止：\n" + "\n".join(plan.blockers))
        return self.installer.install(plan.install_plan)

    def rollback_latest(self, server: Path) -> str:
        state = Path(server) / ".xydp" / "installed.json"
        if not state.is_file():
            raise SealTitleError("目标服没有平台安装状态")
        data = json.loads(state.read_text(encoding="utf-8"))
        for transaction in reversed(data.get("transactions", [])):
            receipt = self.root / "backups" / transaction / "receipt.json"
            if not receipt.is_file():
                continue
            record = json.loads(receipt.read_text(encoding="utf-8"))
            if record.get("operation_type") == OPERATION:
                self.installer.rollback(Path(server), transaction)
                return transaction
        raise SealTitleError("目标服没有可回滚的神印与称号双NPC事务")
