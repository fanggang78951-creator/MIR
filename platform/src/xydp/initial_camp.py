from __future__ import annotations

import hashlib
import json
import re
import copy
import sqlite3
import struct
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from .encoding import TextDocument, encode_text_document, read_text_document
from .installer import InstallError, InstallPlan, Installer, PlannedChange
from .repository import PackageRepository
from .sqlitepatch import SqlitePatchError, apply_sqlite_upsert
from .target import TargetInspector
from .textpatch import (
    TextPatchError,
    install_managed_anchor_hook,
    remove_managed_anchor_hook,
    scan_labels,
    set_exclusive_unique_line,
)


EXPECTED_FILES = (
    "01_狂暴.xlsx", "02_捐献.xlsx", "03_赞助称号.xlsx",
    "04_转生.xlsx", "05_圣律之剑.xlsx", "06_黄金圣物.xlsx",
    "07_新手礼包.xlsx",
)
FEATURE_SPECS = (
    ("01_狂暴.xlsx", "rage", "玄渊运营/狂暴之力"),
    ("02_捐献.xlsx", "donate", "玄渊运营/沙城捐献"),
    ("03_赞助称号.xlsx", "sponsor", "玄渊运营/赞助称号"),
    ("04_转生.xlsx", "rebirth", "玄渊成长/转生"),
    ("05_圣律之剑.xlsx", "horse", "玄渊成长/马牌升级"),
    ("06_黄金圣物.xlsx", "relic", "玄渊成长/军鼓升级"),
    ("07_新手礼包.xlsx", "gift", "玄渊新手/新手礼包"),
)
PACKAGE_ID = "xy.initial-camp.seven-npcs"
PACKAGE_VERSION = "1.8.0-candidate.1"
CONFIG_SYNC_PACKAGE_ID = "xy.platform.config-sync.initial-camp"
CONFIG_SYNC_PACKAGE_VERSION = "1.1.0"
LEGACY_PACKAGE_ID = "xy.initial-camp.six-npcs"
LEGACY_DONATE_TITLE_PACKAGE_ID = "xy.ops.donate-title"
MAP_CODE = "xycamp"
SPAWN = (25, 28)
NATIVE_LINGFU_NAMES = {"灵符", "账户灵符", "原生灵符"}
NATIVE_GOLD_NAMES = {"金币", "原生金币"}
NATIVE_YUANBAO_NAMES = {"元宝", "原生元宝"}
NATIVE_DIAMOND_NAMES = {"金刚石", "原生金刚石", "账户金刚石"}
NATIVE_CURRENCY_SPECS = {
    **{
        name: ("原生金币", "金币", "CHECKGOLD {amount}", "GOLDCOUNT - {amount}")
        for name in NATIVE_GOLD_NAMES
    },
    **{
        name: ("原生元宝", "元宝", "CHECKGAMEGOLD > {threshold}", "GAMEGOLD - {amount}")
        for name in NATIVE_YUANBAO_NAMES
    },
    **{
        name: ("原生灵符", "灵符", "CHECKGAMEGIRD > {threshold}", "GAMEGIRD - {amount}")
        for name in NATIVE_LINGFU_NAMES
    },
    **{
        name: ("原生金刚石", "金刚石", "CHECKGAMEDIAMOND {amount}", "GAMEDIAMOND - {amount}")
        for name in NATIVE_DIAMOND_NAMES
    },
}
NATIVE_CURRENCY_HELP = "金币、元宝、灵符、金刚石（可填写原生/账户别名）"
SINGLE_TIER_ITEMSHOW_X = 260
SINGLE_TIER_ITEMSHOW_Y = -90


class InitialCampError(ValueError):
    pass


@dataclass(frozen=True)
class SheetData:
    filename: str
    rows: tuple[dict[str, object], ...]
    sha256: str


@dataclass(frozen=True)
class CampNpc:
    feature_id: str
    name: str
    script_path: str
    map_code: str
    x: int
    y: int
    appearance: int
    state: str


@dataclass
class InitialCampPlan:
    server: str
    materials: str
    materials_hash: str
    client: str | None = None
    npcs: list[CampNpc] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    install_plan: InstallPlan | None = None
    operation: str = "initial-camp-seven-npc"


def _cell_text(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> object:
    value = cell.find("m:v", ns)
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(item.text or "" for item in cell.findall(".//m:t", ns))
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell_type == "s":
        return shared[int(raw)]
    if cell_type in {"str", "e"}:
        return raw
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return 0
    value = 0
    for letter in letters.group(0):
        value = value * 26 + ord(letter) - 64
    return value - 1


def read_workbook(path: Path) -> SheetData:
    path = Path(path)
    raw = path.read_bytes()
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.findall(".//m:t", ns)) for item in root.findall("m:si", ns)]
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", rel_ns)}
        sheet = book.find("m:sheets/m:sheet", ns)
        if sheet is None:
            raise InitialCampError(f"表格没有工作表：{path.name}")
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = targets[rid].lstrip("/")
        xml_name = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(archive.read(xml_name))
        matrix: list[list[object]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            values: list[object] = []
            for cell in row.findall("m:c", ns):
                index = _column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")
                values[index] = _cell_text(cell, shared, ns)
            matrix.append(values)
    if not matrix:
        raise InitialCampError(f"表格为空：{path.name}")
    headers = [str(value).strip() for value in matrix[0]]
    rows: list[dict[str, object]] = []
    for values in matrix[1:]:
        item = {header: (values[index] if index < len(values) else "") for index, header in enumerate(headers) if header}
        if any(str(value).strip() for value in item.values()):
            rows.append(item)
    return SheetData(path.name, tuple(rows), hashlib.sha256(raw).hexdigest())


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _integer(value: object, default: int | None = None) -> int | None:
    if value in (None, "", "自动"):
        return default
    try:
        return int(float(str(value)))
    except ValueError as exc:
        raise InitialCampError(f"应为整数的单元格填写了：{value}") from exc


def _status(rows: tuple[dict[str, object], ...]) -> str:
    states = {_text(row.get("状态")) for row in rows if _text(row.get("状态"))}
    return "可安装" if states == {"可安装"} else "待配置"


def _first(rows: tuple[dict[str, object], ...], key: str, default: object = "") -> object:
    for row in rows:
        if _text(row.get(key)):
            return row[key]
    return default


def _consistent_first(
    rows: tuple[dict[str, object], ...], key: str, filename: str, default: object = ""
) -> object:
    values = [_text(row.get(key)) for row in rows if _text(row.get(key))]
    if not values:
        return default
    if len(set(values)) != 1:
        raise InitialCampError(f"{filename}：{key} 在不同档位填写不一致")
    return next(row[key] for row in rows if _text(row.get(key)))


def _script_token(value: object, field_name: str) -> str:
    token = _text(value)
    if not token:
        raise InitialCampError(f"{field_name}不能为空")
    if re.search(r"[\s<>\\/\[\]{};]", token):
        raise InitialCampError(f"{field_name}含脚本不支持的字符：{token}")
    return token


def _npc_name(value: object, filename: str) -> str:
    name = _text(value)
    if not name:
        raise InitialCampError(f"{filename}：NPC名称不能为空")
    if any(char in name for char in "\t\r\n"):
        raise InitialCampError(f"{filename}：NPC名称不能包含制表符或换行")
    return name


def _decode_document(data: bytes | None) -> TextDocument:
    if data is None:
        return TextDocument("", "gb18030", "\r\n")
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom):]
    for encoding in ("utf-8", "gb18030"):
        try:
            text = body.decode(encoding)
            return TextDocument(text, encoding, "\r\n" if "\r\n" in text else "\n", bom)
        except UnicodeDecodeError:
            continue
    raise InitialCampError("目标文本编码无法识别")


def _map_file_from_mapinfo(text: str) -> str:
    match = re.search(r"(?im)^\s*\[\s*xycamp(?:\|([^\s\]]+))?\s+", text)
    if not match:
        raise InitialCampError("MapInfo.txt 中找不到 xycamp 初始营地")
    return (match.group(1) or MAP_CODE) + ".map"


def _map_geometry(data: bytes) -> tuple[int, int, int]:
    if len(data) < 52:
        raise InitialCampError("初始营地地图文件小于52字节")
    width, height = struct.unpack_from("<HH", data, 0)
    cell_count = width * height
    for cell_size in (12, 14, 36):
        if len(data) == 52 + cell_count * cell_size:
            return width, height, cell_size
    raise InitialCampError("初始营地地图格式不是平台支持的 type0/type2/type3")


def _walkable(data: bytes, width: int, height: int, cell_size: int, x: int, y: int) -> bool:
    if not (1 <= x < width - 1 and 1 <= y < height - 1):
        return False
    offset = 52 + (x * height + y) * cell_size
    front = struct.unpack_from("<H", data, offset + 4)[0]
    door = data[offset + 6] & 0x7F
    return not (front & 0x8000) and door == 0


def _occupied(merchant_text: str, map_code: str) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for line in merchant_text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and fields[1].casefold() == map_code.casefold():
            try:
                result.add((int(fields[2]), int(fields[3])))
            except ValueError:
                pass
    return result


def _auto_positions(data: bytes, width: int, height: int, cell_size: int, occupied: set[tuple[int, int]], count: int) -> list[tuple[int, int]]:
    preferred = [(-5, -3), (0, -4), (5, -3), (-5, 3), (0, 4), (5, 3)]
    candidates = [(SPAWN[0] + dx, SPAWN[1] + dy) for dx, dy in preferred]
    for radius in range(4, 13):
        for dx in range(-radius, radius + 1):
            for dy in (-radius, radius):
                candidates.append((SPAWN[0] + dx, SPAWN[1] + dy))
        for dy in range(-radius + 1, radius):
            for dx in (-radius, radius):
                candidates.append((SPAWN[0] + dx, SPAWN[1] + dy))
    chosen: list[tuple[int, int]] = []
    for point in candidates:
        if point in occupied or point in chosen or point == SPAWN:
            continue
        if any(abs(point[0] - x) + abs(point[1] - y) < 3 for x, y in chosen):
            continue
        if _walkable(data, width, height, cell_size, *point):
            chosen.append(point)
            if len(chosen) == count:
                return chosen
    raise InitialCampError("出生点附近找不到足够的可走空闲位置来放置七个NPC")


def _pending_script(name: str) -> str:
    return f"[@Main]\n#SAY\n【{name}】当前材料表尚未配置完整，暂不开放。\\\n<关闭/@exit>\n"


def _donate_values(row: dict[str, object]) -> dict[str, int]:
    columns = (
        "攻击下限", "攻击上限", "魔法下限", "魔法上限", "道术下限", "道术上限",
        "暴击", "基础爆率", "最大爆率",
    )
    values: dict[str, int] = {}
    for column in columns:
        value = _integer(row.get(column), 0)
        if value is None or value < 0:
            raise InitialCampError(f"捐献{column}必须填写非负整数")
        values[column] = value
    if values["暴击"] > 255:
        raise InitialCampError("捐献暴击必须是0到255的整数")
    return values


def _donate_summary(row: dict[str, object]) -> str:
    values = _donate_values(row)
    return (
        f"攻击+{values['攻击下限']}-{values['攻击上限']}；"
        f"魔法+{values['魔法下限']}-{values['魔法上限']}；"
        f"道术+{values['道术下限']}-{values['道术上限']}；"
        f"暴击+{values['暴击']}%；基础爆率+{values['基础爆率']}%；"
        f"最大爆率+{values['最大爆率']}%"
    )


def _donate_script(npc_name: str, title_name: str) -> str:
    return f"""[@Main]
#SAY
【{npc_name}】每个角色只能激活一次；已拥有【{title_name}】称号时不会重复扣费。\\
<确认捐献/@XY_CAMP_DONATE> <关闭/@exit>

[@XY_CAMP_DONATE]
#IF
#ACT
#CALL [\\玄渊功能\\捐献\\捐献核心.txt] @XY_DONATE_TRIGGER
"""


def _donate_anchor_contents(row: dict[str, object], title_name: str) -> dict[str, str]:
    values = _donate_values(row)

    def content(*increments: tuple[str, str]) -> str:
        actions = [f"INC {variable} {values[column]}" for column, variable in increments if values[column]]
        if not actions:
            return ""
        return "\n".join(["#IF", f"CHECKFENGHAO {title_name}", "#ACT", *actions])

    return {
        "XY_EQUIP_MAKER_DROP_ANCHOR": content(
            ("基础爆率", "N$XY_最终爆率"), ("最大爆率", "N$XY_最大爆率")
        ),
        "XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR": content(("基础爆率", "N$XY_RT_Drop")),
        "XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR": content(("最大爆率", "N$XY_RT_DropMax")),
    }


def _donate_fenghao_line(row: dict[str, object], title_name: str) -> str:
    return f"{title_name}={_donate_summary(row)}"


def _donate_itemdesc_line(row: dict[str, object], title_name: str) -> str:
    values = _donate_values(row)
    return (
        f"{title_name}=\\242/　玄渊捐献称号\\-\\146/　[称号属性]："
        f"\\251/　攻击+{values['攻击下限']}-{values['攻击上限']}"
        f"\\251/　魔法+{values['魔法下限']}-{values['魔法上限']}"
        f"\\251/　道术+{values['道术下限']}-{values['道术上限']}"
        f"\\251/　暴击+{values['暴击']}%"
        f"\\251/　基础爆率+{values['基础爆率']}%"
        f"\\251/　最大爆率+{values['最大爆率']}%"
    )


def _cost_lines(row: dict[str, object]) -> tuple[list[str], list[str]]:
    checks: list[str] = []
    actions: list[str] = []
    for name_key, count_key in (("材料A", "材料A数量"), ("材料B", "材料B数量")):
        name, count = _text(row.get(name_key)), _integer(row.get(count_key), 0) or 0
        if count < 0:
            raise InitialCampError(f"{count_key}不能小于0")
        if bool(name) != (count > 0):
            raise InitialCampError(f"{name_key}与{count_key}必须同时填写")
        if name and count > 0:
            token = _script_token(name, name_key)
            native = NATIVE_CURRENCY_SPECS.get(token)
            if native is not None:
                _cost_type, _display, check, action = native
                checks.append(check.format(amount=count, threshold=count - 1))
                actions.append(action.format(amount=count, threshold=count - 1))
            else:
                checks.append(f"CHECKITEM {token} {count}")
                actions.append(f"TAKE {token} {count}")
    for name_key, count_key in (("货币A", "货币A数量"), ("货币B", "货币B数量")):
        name, count = _text(row.get(name_key)), _integer(row.get(count_key), 0) or 0
        if count < 0:
            raise InitialCampError(f"{count_key}不能小于0")
        if bool(name) != (count > 0):
            raise InitialCampError(f"{name_key}与{count_key}必须同时填写")
        if not name:
            continue
        token = _script_token(name, name_key)
        native = NATIVE_CURRENCY_SPECS.get(token)
        if native is None:
            raise InitialCampError(
                f"{name_key}只允许填写原生货币：{NATIVE_CURRENCY_HELP}；"
                f"普通背包物品请填写到材料A/材料B，当前值：{token}"
            )
        _cost_type, _display, check, action = native
        checks.append(check.format(amount=count, threshold=count - 1))
        actions.append(action.format(amount=count, threshold=count - 1))
    return checks, actions


def _cost_summary(row: dict[str, object]) -> str:
    _cost_lines(row)
    parts: list[str] = []
    for name_key, count_key in (
        ("材料A", "材料A数量"), ("材料B", "材料B数量"),
        ("货币A", "货币A数量"), ("货币B", "货币B数量"),
    ):
        name = _text(row.get(name_key))
        count = _integer(row.get(count_key), 0) or 0
        if name and count > 0:
            native = NATIVE_CURRENCY_SPECS.get(name)
            display = native[1] if native is not None else name
            parts.append(f"{display}×{count}")
    if not parts:
        raise InitialCampError("单档逐级配置没有填写材料或货币消耗")
    return "、".join(parts)


def _single_tier_route_lines(
    prefix: str,
    states: tuple[str, ...],
    state_type: str,
    *,
    state_variable: str | None = None,
) -> list[str]:
    """生成只显示下一档的主路由；states按最低档到最高档排列。"""
    prefix = _script_token(prefix, "单档路由标签前缀")
    if not states or len(set(states)) != len(states):
        raise InitialCampError("单档路由状态不能为空或重复")
    if state_type not in {"title", "backpack_equipment", "variable"}:
        raise InitialCampError(f"不支持的单档状态类型：{state_type}")
    variable = ""
    if state_type == "variable":
        variable = _script_token(state_variable, "单档进度变量")

    lines = ["[@Main]"]
    for index in range(len(states) - 1, -1, -1):
        state = _script_token(states[index], f"单档状态{index + 1}")
        if state_type == "title":
            condition = f"CHECKFENGHAO {state}"
        elif state_type == "backpack_equipment":
            condition = f"CHECKITEM {state} 1"
        else:
            condition = f"EQUAL {variable} {state}"
        view_index = index + 2 if state_type == "title" else index + 1
        target = f"@{prefix}_FULL" if index == len(states) - 1 else f"@{prefix}_VIEW_{view_index}"
        lines += ["#IF", condition, "#ACT", f"GOTO {target}", "BREAK", ""]
    fallback = "INVALID" if state_type == "variable" else ("NONE" if state_type == "backpack_equipment" else "VIEW_1")
    lines += ["#IF", "#ACT", f"GOTO @{prefix}_{fallback}", "BREAK", ""]
    return lines


def _active_title_rows(
    feature: str,
    rows: tuple[dict[str, object], ...],
) -> list[tuple[dict[str, object], str, int]]:
    active = [row for row in rows if _text(row.get("状态")) == "可安装"]
    configured: list[tuple[dict[str, object], str, int]] = []
    for index, row in enumerate(active, 1):
        title = _script_token(row.get("称号名称"), f"{feature}第{index}行称号名称")
        shape = _integer(row.get("称号编号"))
        if shape is None or not 0 <= shape <= 255:
            raise InitialCampError(f"{feature}第{index}行称号编号必须是0到255的整数")
        configured.append((row, title, shape))
    titles = [item[1] for item in configured]
    shapes = [item[2] for item in configured]
    if len(set(titles)) != len(titles):
        raise InitialCampError(f"{feature}：可安装档位的称号名称不能重复")
    if len(set(shapes)) != len(shapes):
        raise InitialCampError(f"{feature}：可安装档位的称号编号不能重复")
    return configured


def _sponsor_rows(rows: tuple[dict[str, object], ...]) -> list[tuple[dict[str, object], str, int]]:
    configured = _active_title_rows("赞助称号", rows)
    for index, (row, _title, _shape) in enumerate(configured, 1):
        values: dict[str, int] = {}
        for column in ("处决", "韧性", "基础爆率", "最大爆率", "伤害系数"):
            value = _integer(row.get(column))
            if value is None or value < 0:
                raise InitialCampError(f"赞助称号第{index}行{column}必须填写非负整数")
            values[column] = value
        expected = (
            f"处决+{values['处决']}%；韧性+{values['韧性']}；基础爆率+{values['基础爆率']}%；"
            f"最大爆率+{values['最大爆率']}%；伤害系数+{values['伤害系数']}%"
        )
        if _text(row.get("属性与数值")) != expected:
            raise InitialCampError(
                f"赞助称号第{index}行属性与数值必须与独立属性列一致，应为：{expected}"
            )
    return configured


def _sponsor_values(row: dict[str, object]) -> dict[str, int]:
    return {
        column: _integer(row.get(column), 0) or 0
        for column in ("处决", "韧性", "基础爆率", "最大爆率", "伤害系数")
    }


def _sponsor_summary(row: dict[str, object], *, probability_label: bool = False) -> str:
    values = _sponsor_values(row)
    execution = "处决概率" if probability_label else "处决"
    return (
        f"{execution}+{values['处决']}%；韧性+{values['韧性']}；"
        f"基础爆率+{values['基础爆率']}%；最大爆率+{values['最大爆率']}%；"
        f"伤害系数+{values['伤害系数']}%"
    )


def _sponsor_script(
    rows: tuple[dict[str, object], ...],
    prefix: str,
    npc_name: str,
) -> str:
    configured = _sponsor_rows(rows)
    if not configured:
        return _pending_script(npc_name)
    lines = ["[@Main]", "#SAY", f"【{npc_name}】高级称号会覆盖低级称号。\\"]
    for row, title, _shape in configured:
        values = _sponsor_values(row)
        lines.append(
            f"{title}：处决{values['处决']}%、韧性{values['韧性']}、"
            f"基础爆率{values['基础爆率']}%、最大爆率{values['最大爆率']}%、"
            f"伤害系数{values['伤害系数']}%。\\"
        )
    for index, (row, title, _shape) in enumerate(configured, 1):
        cost_type, cost_name, cost_count = _single_cost(row, "赞助称号")
        cost_display = (
            f"{cost_count}灵符" if cost_type == "原生灵符"
            else f"{cost_count}{cost_name}"
        )
        lines.append(f"<升级{title}（{cost_display}）/@{prefix}_{index}> \\")
    lines.append(f"<查看当前赞助属性/@{prefix}_STATUS> <关闭/@exit>")

    titles = [item[1] for item in configured]
    for index, (row, title, _shape) in enumerate(configured, 1):
        checks, actions = _cost_lines(row)
        if not checks:
            level = _text(row.get("档位/等级")) or str(index)
            raise InitialCampError(f"赞助称号：{level} 标为可安装，但没有填写材料或货币消耗")
        previous = titles[index - 2] if index > 1 else ""
        lines += ["", f"[@{prefix}_{index}]", "#IF"]
        lines.append(f"CHECKFENGHAO {previous}" if previous else f"NOT CHECKFENGHAO {title}")
        lines += checks
        lines += ["#ACT", f"GIVEFENGHAO {title} 1", "", "#IF", f"CHECKFENGHAO {title}", "#ACT"]
        lines += actions
        if previous:
            lines.append(f"RECYCFENGHAO {previous}")
        lines += [
            f"SENDMSG 6 [赞助称号] 已升级为{title}；低级称号已回收。",
            "#CALL [\\玄渊功能\\非常驻\\属性总览\\玄渊三属性按钮.txt] @XY_UI_STATUS_REFRESH",
            "SENDMSG 6 属性总览已刷新；为确保爆率与韧性完整重算，请重新登录一次。",
            "BREAK", "#ELSEACT", "MESSAGEBOX 称号晋升未能完成，请稍后再试；本次未消耗物品和货币。", "BREAK",
        ]

    lines += ["", f"[@{prefix}_STATUS]"]
    for row, title, _shape in reversed(configured):
        lines += [
            "#IF", f"CHECKFENGHAO {title}", "#SAY",
            f"当前拥有：{title}。\\",
            f"{_sponsor_summary(row, probability_label=True)}。\\",
            "<返回/@Main>", "BREAK", "",
        ]
    lines += ["#IF", "#SAY", f"当前未检测到{titles[0]}至{titles[-1]}称号。\\", "<返回/@Main>", "BREAK"]
    return "\n".join(lines) + "\n"


def _sponsor_fenghao_lines(rows: tuple[dict[str, object], ...]) -> list[str]:
    return [
        f"{title}={_sponsor_summary(row, probability_label=True)}"
        for row, title, _shape in _sponsor_rows(rows)
    ]


def _sponsor_itemdesc_lines(rows: tuple[dict[str, object], ...]) -> list[str]:
    lines: list[str] = []
    for row, title, _shape in _sponsor_rows(rows):
        values = _sponsor_values(row)
        lines.append(
            f"{title}=\\242/　玄渊赞助称号\\-\\146/　[称号属性]："
            f"\\251/　处决概率+{values['处决']}%"
            f"\\251/　韧性+{values['韧性']}"
            f"\\251/　基础爆率+{values['基础爆率']}%"
            f"\\251/　最大爆率+{values['最大爆率']}%"
            f"\\251/　伤害系数+{values['伤害系数']}%"
        )
    return lines


def _merge_named_description_lines(document: TextDocument, entries: list[str]) -> bytes:
    replacements = {line.split("=", 1)[0]: line for line in entries}
    emitted: set[str] = set()
    merged_lines: list[str] = []
    for line in document.text.splitlines():
        key = line.split("=", 1)[0]
        replacement = replacements.get(key)
        if replacement is None:
            merged_lines.append(line)
        elif key not in emitted:
            merged_lines.append(replacement)
            emitted.add(key)
    merged_lines.extend(
        replacements[key]
        for key in replacements
        if key not in emitted
    )
    merged = document.newline.join(merged_lines) + document.newline
    return encode_text_document(document, merged)


def _enable_setup_flags(document: TextDocument, names: tuple[str, ...]) -> bytes:
    text = document.text
    for name in names:
        # Do not let ``\s*`` consume the carriage return of a CRLF line.
        # Replacing a match that owns ``\r`` silently turns that one line into
        # LF-only while leaving the rest of the target untouched.  The
        # lookahead validates the line ending without consuming it.
        pattern = re.compile(
            rf"(?im)^{re.escape(name)}[ \t]*=[ \t]*\d+[ \t]*(?=\r?$)"
        )
        matches = list(pattern.finditer(text))
        if len(matches) > 1:
            raise InitialCampError(f"!setup.txt 中 {name} 定义不唯一")
        if matches:
            text = pattern.sub(f"{name}=1", text, count=1)
        else:
            if text and not text.endswith(("\r", "\n")):
                text += document.newline
            text += f"{name}=1{document.newline}"
    return encode_text_document(document, text)


def _title_item_values(title: str, shape: int, color: int) -> dict[str, object]:
    return {
        "Name": title, "StdMode": 70, "Shape": shape, "Weight": 0, "Anicount": 1,
        "Source": 0, "Reserved": 0, "Looks": shape * 5, "DuraMax": 0,
        "Ac": 0, "Ac2": 0, "Mac": 0, "Mac2": 0, "Dc": 0, "Dc2": 0,
        "Mc": 0, "Mc2": 0, "Sc": 0, "Sc2": 0, "Need": 0, "NeedLevel": 0,
        "Price": 0, "Stock": 0, "Color": color, "OverLap": 0, "HP": 0, "MP": 0,
        "Light": 0, "Horse": 0,
    }


def _upsert_title_definitions(
    database: bytes,
    feature: str,
    rows: tuple[dict[str, object], ...],
    color: int,
) -> bytes:
    configured = _sponsor_rows(rows) if feature == "赞助称号" else _active_title_rows(feature, rows)
    for _row, title, shape in configured:
        database = apply_sqlite_upsert(database, {
            "type": "sqlite_upsert", "table": "StdItems", "unique_key": ["Name"],
            "conflict_keys": [["StdMode", "Shape"]], "allocate": {"Idx": "max_plus_one"},
            "on_conflict": "error", "values": _title_item_values(title, shape, color),
        })
    return database


def _sponsor_anchor_contents(rows: tuple[dict[str, object], ...]) -> dict[str, str]:
    configured = _sponsor_rows(rows)

    def content(*increments: tuple[str, str, int]) -> str:
        lines: list[str] = []
        for row, title, _shape in configured:
            actions: list[str] = []
            for column, variable, scale in increments:
                value = (_integer(row.get(column), 0) or 0) * scale
                if value:
                    actions.append(f"INC {variable} {value}")
            if actions:
                lines += ["#IF", f"CHECKFENGHAO {title}", "#ACT", *actions]
        return "\n".join(lines)

    return {
        "XY_EXECUTION_LAB_CHANCE_ANCHOR": content(("处决", "N$XY_EXEC_ChanceBP", 100)),
        "XY_EXECUTION_LAB_TOUGHNESS_ANCHOR": content(("韧性", "N$XY_EXEC_Toughness", 1)),
        "XY_EQUIP_MAKER_DROP_ANCHOR": content(
            ("基础爆率", "N$XY_最终爆率", 1), ("最大爆率", "N$XY_最大爆率", 1)
        ),
        "XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR": content(("基础爆率", "N$XY_RT_Drop", 1)),
        "XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR": content(("最大爆率", "N$XY_RT_DropMax", 1)),
        "XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR": content(
            ("伤害系数", "N$XY_RT_DamageCoeff", 1)
        ),
    }


def _title_chain_script(
    feature: str,
    rows: tuple[dict[str, object], ...],
    prefix: str,
    npc_name: str | None = None,
) -> str:
    configured = _sponsor_rows(rows) if feature == "赞助称号" else _active_title_rows(feature, rows)
    if not configured:
        return _pending_script(npc_name or feature)
    active = [item[0] for item in configured]
    titles = [item[1] for item in configured]
    for index, row in enumerate(active, 1):
        checks, _ = _cost_lines(row)
        if not checks:
            level = _text(row.get("档位/等级")) or str(index)
            raise InitialCampError(f"{feature}：{level} 标为可安装，但没有填写材料或货币消耗")
        if not _text(row.get("属性与数值")):
            level = _text(row.get("档位/等级")) or str(index)
            raise InitialCampError(f"{feature}：{level} 标为可安装，但没有填写属性与数值说明")

    lines = _single_tier_route_lines(prefix, tuple(titles), "title")
    for index, row in enumerate(active, 1):
        checks, actions = _cost_lines(row)
        previous = titles[index - 2] if index > 1 else ""
        target = titles[index - 1]
        level = _text(row.get("档位/等级")) or str(index)
        current_display = previous or f"未{feature}"
        property_summary = _text(row.get("属性与数值"))
        lines += [
            f"[@{prefix}_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            f"<> <{feature}进阶：/FCOLOR=158> <只显示当前可进行的下一重/FCOLOR=218>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> <当前{feature}:/FCOLOR=161>{{{current_display}/SCOLOR=249}}\\",
            f"<> <下一{feature}:/FCOLOR=161>{{{level}（{target}）/SCOLOR=253}}\\",
            f"<> <所需材料:/FCOLOR=161>{{{_cost_summary(row)}/SCOLOR=251}}\\",
            f"<> <{feature}属性:/FCOLOR=161>{{{property_summary}/SCOLOR=147}}\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> 【<确认{feature}/@{prefix}_{index}>】　<关闭/@exit>\\", "",
            f"[@{prefix}_{index}]", "#IF",
        ]
        if previous:
            lines.append(f"CHECKFENGHAO {previous}")
        for title in titles[index - 1:]:
            lines.append(f"NOT CHECKFENGHAO {title}")
        lines += checks + ["#ACT", f"GOTO @{prefix}_APPLY_{index}", "#ELSEACT",
                           f"MESSAGEBOX {feature}所需的物品或货币不足，请备齐后再来。", "BREAK", ""]

        lines += [f"[@{prefix}_APPLY_{index}]", "#IF"]
        if previous:
            lines.append(f"CHECKFENGHAO {previous}")
        for title in titles[index - 1:]:
            lines.append(f"NOT CHECKFENGHAO {title}")
        lines += checks + ["#ACT", f"GIVEFENGHAO {target} 1", f"GOTO @{prefix}_CONFIRM_{index}",
                           "BREAK", "#ELSEACT", f"MESSAGEBOX {feature}所需的物品或货币不足，请备齐后再来。",
                           "BREAK", ""]

        lines += [f"[@{prefix}_CONFIRM_{index}]", "#IF", f"CHECKFENGHAO {target}"]
        if previous:
            lines.append(f"CHECKFENGHAO {previous}")
        lines += ["#ACT"]
        lines += actions
        if previous:
            lines.append(f"RECYCFENGHAO {previous}")
        lines += [
            f"SENDMSG 6 [{feature}] 已升级为{target}。",
            "SENDMSG 6 脚本扩展属性将在重新登录后完整刷新。",
            "GOTO @Main", "BREAK", "#ELSEACT", "MESSAGEBOX 称号晋升未能完成，请稍后再试；本次未消耗物品和货币。", "BREAK", "",
        ]

    lines += [
        f"[@{prefix}_FULL]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        f"<> <{feature}进阶：/FCOLOR=158> <当前{feature}已经达到最高档/FCOLOR=218>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        f"<> <当前{feature}:/FCOLOR=161>{{{titles[-1]}/SCOLOR=249}}\\",
        "<> <状态:/FCOLOR=161>{已满级/SCOLOR=253}\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        "<> <关闭/@exit>\\", "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _rebirth_power_steps(rows: tuple[dict[str, object], ...]) -> list[int]:
    configured = _active_title_rows("转生", rows)
    if not configured:
        return []
    if len(configured) != 10:
        raise InitialCampError(f"转生：原生转生要求连续10档，实际{len(configured)}档")
    values: list[int] = []
    total = Decimal("0")
    for index, (row, _title, _shape) in enumerate(configured, 1):
        raw = row.get("神力增加")
        if raw in (None, ""):
            raise InitialCampError(f"转生：第{index}档没有填写神力增加")
        increment = Decimal(str(raw)) * Decimal("100")
        if increment != increment.to_integral_value() or increment <= 0:
            raise InitialCampError(f"转生：第{index}档神力增加必须换算为正整数百分比")
        total += increment
        values.append(int(total))
    return values


def _rebirth_power_hook(rows: tuple[dict[str, object], ...], variable: str) -> str:
    values = _rebirth_power_steps(rows)
    if not values:
        return ""
    lines = [
        "; 转生神力：以翎风引擎原生转生等级为唯一权威，称号只作显示镜像",
        "#IF",
        "#ACT",
        "MOV N$XY_REBIRTH_PowerBonus 0",
    ]
    for level, value in enumerate(values, 1):
        lines.append("#IF")
        if level == len(values):
            lines.append(f"CHECKRENEWLEVEL > {level - 1}")
        else:
            lines.append(f"CHECKRENEWLEVEL = {level}")
        lines += ["#ACT", f"MOV N$XY_REBIRTH_PowerBonus {value}"]
    lines += [
        "#IF",
        "LARGE N$XY_REBIRTH_PowerBonus 0",
        "#ACT",
        f"INC {variable} <$STR(N$XY_REBIRTH_PowerBonus)>",
    ]
    return "\n".join(lines)


def _rebirth_anchor_contents(rows: tuple[dict[str, object], ...]) -> dict[str, str]:
    return {
        "XY_EQUIP_MAKER_POWER_ANCHOR": _rebirth_power_hook(rows, "N$倍攻"),
        "XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR": _rebirth_power_hook(rows, "N$XY_RT_Power"),
    }


def _remove_other_titles(lines: list[str], titles: list[str], keep: str) -> None:
    for title in titles:
        if title != keep:
            lines.append(f"RECYCFENGHAO {title}")


def _rebirth_script(
    rows: tuple[dict[str, object], ...],
    prefix: str = "XY_REBIRTH",
    npc_name: str | None = None,
) -> str:
    configured = _active_title_rows("转生", rows)
    if not configured:
        return _pending_script(npc_name or "转生")
    active = [item[0] for item in configured]
    titles = [item[1] for item in configured]
    if len(active) != 10:
        raise InitialCampError(f"转生：原生转生要求连续10档，实际{len(active)}档")
    _rebirth_power_steps(rows)
    for index, row in enumerate(active, 1):
        checks, _ = _cost_lines(row)
        if not checks:
            raise InitialCampError(f"转生：第{index}档没有材料或货币消耗")
        if not _text(row.get("属性与数值")):
            raise InitialCampError(f"转生：第{index}档没有属性与数值说明")

    lines = ["[@Main]"]
    for index in range(len(titles), 0, -1):
        lines += [
            "#IF", "CHECKRENEWLEVEL = 0", f"CHECKFENGHAO {titles[index - 1]}",
            "#ACT", f"GOTO @{prefix}_MIGRATE_VIEW_{index}", "BREAK", "",
        ]
    lines += [
        "#IF", f"CHECKRENEWLEVEL > {len(titles) - 1}", "#ACT",
        f"GOTO @{prefix}_FULL", "BREAK", "",
    ]
    for current in range(len(titles) - 1, 0, -1):
        lines += [
            "#IF", f"CHECKRENEWLEVEL = {current}", "#ACT",
            f"GOTO @{prefix}_VIEW_{current + 1}", "BREAK", "",
        ]
    lines += [
        "#IF", "CHECKRENEWLEVEL = 0", "#ACT", f"GOTO @{prefix}_VIEW_1", "BREAK", "",
        "#IF", "#ACT", "MESSAGEBOX 当前转生状态异常，请联系管理员处理。", "BREAK", "",
    ]

    for index, row in enumerate(active, 1):
        checks, actions = _cost_lines(row)
        target = titles[index - 1]
        level = _text(row.get("档位/等级")) or f"{index}转"
        current_display = "未转生" if index == 1 else f"转生{index - 1}重"
        property_summary = _text(row.get("属性与数值"))
        previous_level = index - 1
        lines += [
            f"[@{prefix}_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            "<> <转生进阶：/FCOLOR=158> <突破桎梏，重塑根基/FCOLOR=218>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> <当前转生:/FCOLOR=161>{{{current_display}/SCOLOR=249}}\\",
            f"<> <下一转生:/FCOLOR=161>{{{level}（{target}）/SCOLOR=253}}\\",
            f"<> <所需材料:/FCOLOR=161>{{{_cost_summary(row)}/SCOLOR=251}}\\",
            f"<> <转生属性:/FCOLOR=161>{{{property_summary}/SCOLOR=147}}\\",
            "<> <规则说明:/FCOLOR=161>{转生后人物等级不变，当前经验将清空/SCOLOR=245}\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> 【<确认转生/@{prefix}_{index}>】　<关闭/@exit>\\", "",
            f"[@{prefix}_{index}]", "#IF", f"CHECKRENEWLEVEL = {previous_level}", *checks,
            "#ACT", f"GOTO @{prefix}_APPLY_{index}", "#ELSEACT",
            "MESSAGEBOX 当前转生阶段不符，或所需物品、货币不足。", "BREAK", "",
            f"[@{prefix}_APPLY_{index}]", "#IF", f"CHECKRENEWLEVEL = {previous_level}", *checks,
            "#ACT", f"GIVEFENGHAO {target} 1", f"GOTO @{prefix}_TITLE_CONFIRM_{index}",
            "BREAK", "#ELSEACT", "MESSAGEBOX 当前转生阶段不符，或所需物品、货币不足。",
            "BREAK", "",
            f"[@{prefix}_TITLE_CONFIRM_{index}]", "#IF", f"CHECKRENEWLEVEL = {previous_level}",
            f"CHECKFENGHAO {target}", "#ACT", "RENEWLEVEL 1",
            f"GOTO @{prefix}_ENGINE_CONFIRM_{index}", "BREAK", "#ELSEACT",
            "MESSAGEBOX 转生称号未能授予，本次未消耗物品和货币。", "BREAK", "",
            f"[@{prefix}_ENGINE_CONFIRM_{index}]", "#IF", f"CHECKRENEWLEVEL = {index}",
            f"CHECKFENGHAO {target}", "#ACT", *actions,
        ]
        _remove_other_titles(lines, titles, target)
        lines += [
            f"SENDMSG 6 [转生] 恭喜您晋升至转生{index}重，获得称号{target}。",
            "GOTO @Main", "BREAK", "#ELSEACT", f"RECYCFENGHAO {target}",
            "MESSAGEBOX 转生未能完成，本次未扣除物品和货币。", "BREAK", "",
        ]

    for index, title in enumerate(titles, 1):
        lines += [
            f"[@{prefix}_MIGRATE_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            "<> <转生传承：/FCOLOR=158> <找回您曾经达到的转生境界/FCOLOR=218>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> <昔日称号:/FCOLOR=161>{{{title}/SCOLOR=249}}\\",
            f"<> <恢复境界:/FCOLOR=161>{{转生{index}重/SCOLOR=253}}\\",
            "<> <传承消耗:/FCOLOR=161>{不消耗材料和货币/SCOLOR=251}\\",
            "<> <重要说明:/FCOLOR=161>{人物等级不变，当前经验将清空/SCOLOR=245}\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> 【<确认传承/@{prefix}_MIGRATE_{index}>】　<关闭/@exit>\\", "",
            f"[@{prefix}_MIGRATE_{index}]", "#IF", "CHECKRENEWLEVEL = 0",
            f"CHECKFENGHAO {title}", "#ACT", f"RENEWLEVEL {index}",
            f"GOTO @{prefix}_MIGRATE_CONFIRM_{index}", "BREAK", "#ELSEACT",
            "MESSAGEBOX 当前转生状态已变化，请重新打开转生界面。", "BREAK", "",
            f"[@{prefix}_MIGRATE_CONFIRM_{index}]", "#IF", f"CHECKRENEWLEVEL = {index}",
            f"CHECKFENGHAO {title}", "#ACT",
        ]
        _remove_other_titles(lines, titles, title)
        lines += [
            f"SENDMSG 6 [转生] 往日转生境界已恢复至{index}重。",
            "GOTO @Main", "BREAK", "#ELSEACT",
            "MESSAGEBOX 转生境界恢复未能完成，请联系管理员处理。", "BREAK", "",
        ]

    lines += [
        f"[@{prefix}_FULL]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        "<> <转生进阶：/FCOLOR=158> <当前已达到最高档/FCOLOR=218>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        f"<> <当前转生:/FCOLOR=161>{{转生{len(titles)}重/SCOLOR=249}}\\",
        f"<> <对应称号:/FCOLOR=161>{{{titles[-1]}/SCOLOR=253}}\\",
        "<> <状态:/FCOLOR=161>{已满级/SCOLOR=253}\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        "<> <关闭/@exit>\\", "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _single_cost(row: dict[str, object], feature: str) -> tuple[str, str, int]:
    configured: list[tuple[str, str, int]] = []
    for name_key, count_key, kind in (
        ("材料A", "材料A数量", "材料"),
        ("材料B", "材料B数量", "材料"),
        ("货币A", "货币A数量", "货币"),
        ("货币B", "货币B数量", "货币"),
    ):
        name = _text(row.get(name_key))
        count = _integer(row.get(count_key), 0) or 0
        if count < 0 or bool(name) != (count > 0):
            raise InitialCampError(f"{feature}：{name_key}与{count_key}必须同时填写正数")
        if name:
            configured.append((kind, _script_token(name, name_key), count))
    if len(configured) != 1:
        raise InitialCampError(f"{feature}：材料/货币四组中必须恰好填写一组")
    kind, name, count = configured[0]
    native = NATIVE_CURRENCY_SPECS.get(name)
    if native is not None:
        cost_type, display, _check, _action = native
        return cost_type, display, count
    if kind == "货币":
        raise InitialCampError(
            f"{feature}：货币栏只允许填写原生货币：{NATIVE_CURRENCY_HELP}；当前值：{name}"
        )
    return "材料", name, count


def _donate_cost(row: dict[str, object]) -> tuple[str, str, int]:
    return _single_cost(row, "捐献")


def _equipment_counts(database: bytes, names: set[str]) -> dict[str, int]:
    if not names:
        return {}
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(database)
    try:
        connection = sqlite3.connect(temp)
        try:
            result: dict[str, int] = {}
            for name in names:
                result[name] = int(connection.execute(
                    "SELECT COUNT(*) FROM StdItems WHERE Name = ?", (name,)
                ).fetchone()[0])
            return result
        finally:
            connection.close()
    finally:
        temp.unlink(missing_ok=True)


def _sync_sponsor_panel_values(
    text: str,
    rows: tuple[dict[str, object], ...],
    newline: str,
) -> str:
    """Update only sponsor values in an already extended attribute panel.

    The live panel contains equipment, necklace-luck, collection and task
    display hooks that are newer than the base ``xy.ui.attr-overview`` render
    payload. Re-rendering that payload would delete those unrelated accepted
    features. Toughness is intentionally not duplicated here because the
    panel reads the final shared ``N$XY_EXEC_Toughness`` value.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    required = (
        "; XY_EQUIP_MAKER_PANEL_EXEC_CHANCE_ANCHOR",
        "MOV N$XY_UI_C_Value01 <$STR(N$XY_EXEC_Toughness)>",
    )
    for token in required:
        if normalized.count(token) != 1:
            raise InitialCampError(f"目标属性总览缺少唯一扩展锚点：{token}")

    configured = _sponsor_rows(rows)
    for row, title, _shape in configured:
        values = _sponsor_values(row)
        for variable, column in (
            ("N$XY_UI_A_Value02", "伤害系数"),
            ("N$XY_UI_C_Value02", "处决"),
        ):
            pattern = re.compile(
                rf"(#IF\nCHECKFENGHAO {re.escape(title)}\n#ACT\nINC {re.escape(variable)} )-?\d+"
            )
            matches = list(pattern.finditer(normalized))
            if len(matches) != 1:
                raise InitialCampError(
                    f"属性总览中{title}/{column}显示块应唯一，实际{len(matches)}处"
                )
            normalized = pattern.sub(rf"\g<1>{values[column]}", normalized, count=1)
    return normalized.replace("\n", newline)


def _equipment_indices(database: bytes, names: set[str], feature: str) -> dict[str, int]:
    if not names:
        return {}
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(database)
    try:
        connection = sqlite3.connect(temp)
        try:
            result: dict[str, int] = {}
            errors: list[str] = []
            for name in sorted(names):
                records = connection.execute(
                    "SELECT Idx FROM StdItems WHERE Name = ?", (name,)
                ).fetchall()
                if len(records) != 1:
                    errors.append(f"{name}({len(records)}条)")
                    continue
                try:
                    item_index = int(records[0][0])
                except (TypeError, ValueError):
                    errors.append(f"{name}(Idx无效)")
                    continue
                if item_index <= 0:
                    errors.append(f"{name}(Idx={item_index})")
                    continue
                result[name] = item_index
            duplicate_ids = sorted({value for value in result.values() if list(result.values()).count(value) > 1})
            if duplicate_ids:
                errors.append("不同装备共用Idx=" + "、".join(str(value) for value in duplicate_ids))
            if errors:
                raise InitialCampError(f"{feature}装备名或Idx无法唯一识别：" + "、".join(errors))
            return result
        finally:
            connection.close()
    finally:
        temp.unlink(missing_ok=True)


def _validate_equipment_chain(
    feature: str,
    rows: tuple[dict[str, object], ...],
    database: bytes,
) -> list[tuple[dict[str, object], str, str]]:
    if _status(rows) != "可安装":
        return []
    active = [row for row in rows if _text(row.get("状态")) == "可安装"]
    configured: list[tuple[dict[str, object], str, str]] = []
    for index, row in enumerate(active, 1):
        current = _script_token(row.get("当前装备"), f"{feature}第{index}行当前装备")
        next_item = _script_token(row.get("下一装备"), f"{feature}第{index}行下一装备")
        checks, _ = _cost_lines(row)
        if not checks:
            raise InitialCampError(f"{feature}第{index}行没有填写材料或货币消耗")
        if current and current == next_item:
            raise InitialCampError(f"{feature}第{index}行当前装备和下一装备不能相同")
        configured.append((row, current, next_item))
    for index in range(1, len(configured)):
        if configured[index][1] != configured[index - 1][2]:
            raise InitialCampError(
                f"{feature}升级链断开：第{index + 1}行当前装备必须等于上一行下一装备"
            )
    next_names = [item[2] for item in configured]
    if len(set(next_names)) != len(next_names):
        raise InitialCampError(f"{feature}下一装备存在重复名称")
    names = {name for _, current, next_item in configured for name in (current, next_item) if name}
    counts = _equipment_counts(database, names)
    errors = [f"{name}({counts.get(name, 0)}条)" for name in sorted(names) if counts.get(name) != 1]
    if errors:
        raise InitialCampError(f"{feature}装备名必须在目标服StdItems中唯一存在：" + "、".join(errors))
    return configured


def _equipment_chain_script(
    feature: str,
    npc_name: str,
    rows: tuple[dict[str, object], ...],
    prefix: str,
    database: bytes,
) -> str:
    configured = _validate_equipment_chain(feature, rows, database)
    if not configured:
        return _pending_script(npc_name)
    states = [configured[0][1], *(next_item for _, _, next_item in configured)]
    indices = _equipment_indices(database, set(states), feature)
    lines = _single_tier_route_lines(prefix, tuple(states), "backpack_equipment")
    for index, (row, current, next_item) in enumerate(configured, 1):
        checks, actions = _cost_lines(row)
        lines += [
            f"[@{prefix}_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            f"<> <{npc_name}进阶：/FCOLOR=158> <只显示当前可升级的下一件/FCOLOR=218>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> <当前装备:/FCOLOR=161>{{{current}/SCOLOR=249}}\\",
            f"<> <下一装备:/FCOLOR=161>{{{next_item}/SCOLOR=253}}\\",
            f"<> <升级消耗:/FCOLOR=161>{{{_cost_summary(row)}/SCOLOR=251}}\\",
            "<> <将鼠标移到图标查看下一装备的完整属性。/FCOLOR=147>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<ItemShow:{indices[next_item]}:0:{SINGLE_TIER_ITEMSHOW_X}:{SINGLE_TIER_ITEMSHOW_Y}:1>　【<确认升级/@{prefix}_{index}>】　<关闭/@exit>\\",
            "", f"[@{prefix}_{index}]", "#IF", "CHECKBAGSIZE 1", f"CHECKITEM {current} 1",
        ]
        for higher in states[index:]:
            lines.append(f"NOT CHECKITEM {higher} 1")
        lines += [*checks, "#ACT"]
        lines += [f"TAKE {current} 1", *actions, f"GIVE {next_item} 1"]
        lines += [
            f"SENDMSG 6 [{npc_name}] 已将{current}升级为{next_item}。",
            "GOTO @Main",
            "BREAK",
            "#ELSEACT",
            "MESSAGEBOX 当前装备不是背包内最高档，或材料、货币、背包空间不满足。",
            "BREAK",
            "",
        ]

    lines += [
        f"[@{prefix}_NONE]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        f"<> <{npc_name}进阶：/FCOLOR=158> <未找到可升级装备/FCOLOR=218>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        f"<> <请先将{feature}放入背包；穿戴中的装备不参与识别。/FCOLOR=251>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\", "<> <关闭/@exit>\\", "",
        f"[@{prefix}_FULL]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        f"<> <{npc_name}进阶：/FCOLOR=158> <当前装备已经达到最高档/FCOLOR=218>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        f"<> <当前装备:/FCOLOR=161>{{{states[-1]}/SCOLOR=249}}\\",
        "<> <状态:/FCOLOR=161>{已满级/SCOLOR=253}\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\", "<> <关闭/@exit>\\", "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _newbie_gift_script(
    npc_name: str,
    rows: tuple[dict[str, object], ...],
    database: bytes,
) -> str:
    if _status(rows) != "可安装":
        return _pending_script(npc_name)
    if len(rows) != 1:
        raise InitialCampError("07_新手礼包.xlsx：必须恰好填写一行且状态为可安装")
    row = rows[0]
    code = _script_token(row.get("礼包码"), "新手礼包码")
    reward_a = _script_token(row.get("奖励装备A"), "新手礼包奖励装备A")
    reward_b = _script_token(row.get("奖励装备B"), "新手礼包奖励装备B")
    if reward_a == reward_b:
        raise InitialCampError("新手礼包的两件奖励装备不能相同")
    counts = _equipment_counts(database, {reward_a, reward_b})
    errors = [f"{name}({counts.get(name, 0)}条)" for name in sorted(counts) if counts.get(name) != 1]
    if errors:
        raise InitialCampError("新手礼包奖励装备名必须在目标服StdItems中唯一存在：" + "、".join(errors))
    return f"""[@Main]
#SAY
【{npc_name}】每个角色只能领取一次，请输入礼包码。\\
<INPUTTEXT:1:15:80:180:18:0:249:255:1:32:礼包码格式错误:请输入礼包码:160>\\
<TEXT:提交礼包码:15:110:1/@XY_GIFT_CLAIM>\\
<关闭/@exit>

[@XY_GIFT_CLAIM]
#IF
NOT CHECKNAMELIST ..\\QuestDiary\\玄渊数据\\新手礼包\\已领取.txt
EQUAL <$NPCINPUT(1)> {code}
CHECKBAGSIZE 2
#ACT
ForceDirectories ..\\QuestDiary\\玄渊数据\\新手礼包\\
GiveStateItem {reward_a} 1 0 0 0 0 0 0 1
GiveStateItem {reward_b} 1 0 0 0 0 0 0 1
ADDNAMELIST ..\\QuestDiary\\玄渊数据\\新手礼包\\已领取.txt
SENDMSG 6 [{npc_name}] 已领取绑定装备：{reward_a}、{reward_b}。
BREAK
#ELSEACT
MESSAGEBOX 礼包码错误、已经领取或背包空间不足。
BREAK
"""


def _config_text(cost_type: str, cost_name: str, cost_count: int) -> str:
    return (f"[基础]\n功能开关=1\n\n[消耗]\n消耗类型={cost_type}\n"
            f"消耗名称={cost_name}\n消耗数量={cost_count}\n\n"
            "[文案]\n功能关闭=[捐献] 当前功能尚未开放\n"
            "捐献成功=[捐献] 激活成功，称号与属性已经生效\n"
            "条件不足=[捐献] 所需货币或材料不足\n"
            "已经激活=[捐献] 你已经完成捐献，请勿重复操作\n"
            "发放失败=[捐献] 称号激活失败，本次未扣除货币或材料\n"
            "结算失败=[捐献] 结算未能完成，本次未扣除货币或材料\n")


class InitialCampService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root)
        self.repository = PackageRepository(self.root / "packages")
        self.repository.refresh()
        self.installer = Installer(self.repository, self.root / "backups")

    def load_materials(
        self,
        materials: Path,
        filenames: tuple[str, ...] = EXPECTED_FILES,
        overrides: dict[str, Path] | None = None,
    ) -> dict[str, SheetData]:
        materials = Path(materials)
        sources = {
            name: Path(overrides[name]) if overrides and name in overrides else materials / name
            for name in filenames
        }
        missing = [name for name, path in sources.items() if not path.is_file()]
        if missing:
            raise InitialCampError("材料表缺失：" + "、".join(missing))
        return {name: read_workbook(sources[name]) for name in filenames}

    def _sponsor_panel_parameters(self, rows: tuple[dict[str, object], ...]) -> dict[str, object]:
        package = self.repository.packages.get("xy.ui.attr-overview")
        if package is None:
            raise InitialCampError("缺少属性总览成果包：xy.ui.attr-overview")
        panel_a = copy.deepcopy(package.parameters["panel_a"]["default"])
        panel_c = copy.deepcopy(package.parameters["panel_c"]["default"])
        configured = _sponsor_rows(rows)

        def replace(panel: dict[str, object], label: str, column: str) -> None:
            items = [item for item in panel["items"] if item.get("label") == label]
            if len(items) != 1:
                raise InitialCampError(f"属性总览中{label}显示项不唯一")
            items[0]["title_additions"] = [
                {"name": title, "amount": _sponsor_values(row)[column]}
                for row, title, _shape in configured
            ]

        replace(panel_a, "伤害系数", "伤害系数")
        replace(panel_c, "韧性", "韧性")
        replace(panel_c, "处决概率", "处决")
        return {"panel_a": panel_a, "panel_c": panel_c}

    @staticmethod
    def _merge_change(
        changes: dict[str, PlannedChange],
        root: Path,
        relative: str,
        after: bytes,
        operation: str,
        scope: str = "server",
    ) -> None:
        key = relative if scope == "server" else f"{scope}:{relative}"
        path = root / Path(relative.replace("/", "\\"))
        if key in changes:
            old = changes[key]
            changes[key] = PlannedChange(relative, old.before, after, operation, PACKAGE_ID, scope)
        else:
            before = path.read_bytes() if path.exists() else None
            changes[key] = PlannedChange(relative, before, after, operation, PACKAGE_ID, scope)

    def preflight(self, server: Path, materials: Path, client: Path | None = None) -> InitialCampPlan:
        plan = InitialCampPlan(str(Path(server).absolute()), str(Path(materials).absolute()), "")
        try:
            if client is None:
                raise InitialCampError("赞助称号说明需要客户端目录，请先选择同引擎客户端")
            client_root = Path(client).resolve()
            if not client_root.is_dir():
                raise InitialCampError(f"客户端根目录不存在：{client_root}")
            plan.client = str(client_root)
            sheets = self.load_materials(materials)
            plan.materials_hash = hashlib.sha256("".join(sheets[name].sha256 for name in EXPECTED_FILES).encode()).hexdigest()
            target = TargetInspector.inspect(Path(server))
            map_doc = read_text_document(target.envir / "MapInfo.txt")
            map_file = target.root / "Mir200" / "Map" / _map_file_from_mapinfo(map_doc.text)
            if not map_file.is_file():
                raise InitialCampError(f"初始营地地图文件不存在：{map_file}")
            map_data = map_file.read_bytes()
            width, height, cell_size = _map_geometry(map_data)
            merchant_path = target.envir / "MerChant.txt"
            merchant_doc = read_text_document(merchant_path) if merchant_path.exists() else TextDocument("", "gb18030", "\r\n")
            specs = (
                ("01_狂暴.xlsx", "rage", "玄渊运营/狂暴之力"),
                ("02_捐献.xlsx", "donate", "玄渊运营/沙城捐献"),
                ("03_赞助称号.xlsx", "sponsor", "玄渊运营/赞助称号"),
                ("04_转生.xlsx", "rebirth", "玄渊成长/转生"),
                ("05_圣律之剑.xlsx", "horse", "玄渊成长/马牌升级"),
                ("06_黄金圣物.xlsx", "relic", "玄渊成长/军鼓升级"),
                ("07_新手礼包.xlsx", "gift", "玄渊新手/新手礼包"),
            )
            stable_paths = {item[2].casefold() for item in specs}
            occupancy_text = "\n".join(
                line for line in merchant_doc.text.splitlines()
                if not line.split("\t", 1)[0].casefold() in stable_paths
            )
            occupied = _occupied(occupancy_text, MAP_CODE)
            auto = _auto_positions(map_data, width, height, cell_size, occupied, len(specs))
            used = set(occupied)
            for index, (filename, feature_id, script_path) in enumerate(specs):
                sheet = sheets[filename]
                name = _npc_name(_consistent_first(sheet.rows, "NPC名称", filename), filename)
                map_code = _text(_consistent_first(sheet.rows, "地图", filename))
                if map_code.casefold() != MAP_CODE.casefold():
                    raise InitialCampError(f"{filename}：初始之地功能的地图必须填写 {MAP_CODE}")
                x = _integer(_consistent_first(sheet.rows, "X坐标", filename, "自动"))
                y = _integer(_consistent_first(sheet.rows, "Y坐标", filename, "自动"))
                if (x is None) != (y is None):
                    raise InitialCampError(f"{filename}：X/Y坐标必须同时填写或同时留空")
                point = auto[index] if x is None else (x, y)
                assert point[0] is not None and point[1] is not None
                point = (int(point[0]), int(point[1]))
                if point in used:
                    raise InitialCampError(f"{filename}：NPC坐标已占用 {point[0]},{point[1]}")
                if not _walkable(map_data, width, height, cell_size, *point):
                    raise InitialCampError(f"{filename}：NPC坐标不可走 {point[0]},{point[1]}")
                used.add(point)
                appearance = _integer(_consistent_first(sheet.rows, "外观", filename))
                if appearance is None or appearance < 0:
                    raise InitialCampError(f"{filename}：外观必须填写非负整数")
                plan.npcs.append(CampNpc(
                    feature_id, name, script_path, map_code, *point, appearance, _status(sheet.rows)
                ))

            rage = plan.npcs[0]
            rage_rows = sheets["01_狂暴.xlsx"].rows
            if _status(rage_rows) != "可安装" or len(rage_rows) != 1:
                raise InitialCampError("01_狂暴.xlsx：唯一狂暴核心要求恰好一行且状态为可安装")
            rage_cost_type, _, rage_cost = _single_cost(rage_rows[0], "狂暴")
            if rage_cost_type != "原生灵符":
                raise InitialCampError("01_狂暴.xlsx：当前唯一狂暴入口只允许使用原生货币灵符")
            donate_rows = sheets["02_捐献.xlsx"].rows
            if _status(donate_rows) != "可安装" or len(donate_rows) != 1:
                raise InitialCampError("02_捐献.xlsx：唯一捐献核心要求恰好一行且状态为可安装")
            donate_row = donate_rows[0]
            donate_title = _script_token(donate_row.get("称号名称"), "捐献称号名称")
            donate_values = _donate_values(donate_row)
            sponsor_panels = self._sponsor_panel_parameters(sheets["03_赞助称号.xlsx"].rows)
            base = self.installer.preflight(
                target.root,
                ["xy.optional.rage.core", "xy.optional.donate.core", "xy.ui.attr-overview"],
                {"rage_npc_map": MAP_CODE, "rage_npc_x": rage.x, "rage_npc_y": rage.y,
                 "rage_npc_display": rage.name, "rage_appearance": rage.appearance,
                 "rage_cost": rage_cost, "rage_cost_threshold": rage_cost - 1,
                 "donate_title": donate_title,
                 "donate_critical_rate": donate_values["暴击"],
                 **sponsor_panels},
                client_root=client_root,
                operation_type=plan.operation,
            )
            changes = {item.relative_path: item for item in base.changes}

            db_relative = "Mud2/DB/ApexM2.DB"
            db_path = target.root / "Mud2" / "DB" / "ApexM2.DB"
            database = changes[db_relative].after if db_relative in changes else db_path.read_bytes()
            npc_by_id = {item.feature_id: item for item in plan.npcs}
            scripts = {
                "donate": _donate_script(npc_by_id["donate"].name, donate_title),
                "sponsor": _sponsor_script(
                    sheets["03_赞助称号.xlsx"].rows, "XY_SPONSOR", npc_by_id["sponsor"].name
                ),
                "rebirth": _rebirth_script(
                    sheets["04_转生.xlsx"].rows, "XY_REBIRTH", npc_by_id["rebirth"].name
                ),
                "horse": _equipment_chain_script(
                    "圣律之剑", npc_by_id["horse"].name, sheets["05_圣律之剑.xlsx"].rows,
                    "XY_HORSE", database
                ),
                "relic": _equipment_chain_script(
                    "黄金圣物", npc_by_id["relic"].name, sheets["06_黄金圣物.xlsx"].rows,
                    "XY_RELIC", database
                ),
                "gift": _newbie_gift_script(
                    npc_by_id["gift"].name, sheets["07_新手礼包.xlsx"].rows, database
                ),
            }
            for npc in plan.npcs[1:]:
                relative = f"Mir200/Envir/Market_Def/{npc.script_path}-{npc.map_code}.txt"
                text = scripts[npc.feature_id].replace("\n", "\r\n").encode("gb18030")
                self._merge_change(changes, target.root, relative, text, "initial-camp-npc-script")

            merchant_relative = "Mir200/Envir/MerChant.txt"
            merchant_before = changes[merchant_relative].after if merchant_relative in changes else (merchant_path.read_bytes() if merchant_path.exists() else None)
            staged_doc = _decode_document(merchant_before)
            merchant_text = staged_doc.text
            for npc in plan.npcs:
                line = f"{npc.script_path}\t{npc.map_code}\t{npc.x}\t{npc.y}\t{npc.name}\t0\t{npc.appearance}\t0"
                merchant_text = set_exclusive_unique_line(merchant_text, line, [0], staged_doc.newline).text
            self._merge_change(changes, target.root, merchant_relative, encode_text_document(staged_doc, merchant_text), "initial-camp-exclusive-register")

            cost_type, cost_name, cost_count = _donate_cost(donate_row)
            config_relative = "Mir200/Envir/QuestDiary/玄渊配置/沙城捐献配置.txt"
            self._merge_change(changes, target.root, config_relative, _config_text(cost_type, cost_name, cost_count).replace("\n", "\r\n").encode("gb18030"), "initial-camp-donate-config")

            database = apply_sqlite_upsert(database, {
                "type": "sqlite_upsert", "table": "StdItems", "unique_key": ["Name"],
                "conflict_keys": [["StdMode", "Shape"]], "allocate": {"Idx": "max_plus_one"}, "on_conflict": "error",
                "values": {"Name": donate_title, "StdMode": 70, "Shape": 1, "Weight": 0, "Anicount": 1,
                           "Source": 0, "Reserved": 0, "Looks": 5, "DuraMax": 0, "Ac": 0, "Ac2": 0,
                           "Mac": 0, "Mac2": 0,
                           "Dc": donate_values["攻击下限"],
                           "Dc2": donate_values["攻击上限"],
                           "Mc": donate_values["魔法下限"],
                           "Mc2": donate_values["魔法上限"],
                           "Sc": donate_values["道术下限"],
                           "Sc2": donate_values["道术上限"],
                           "Need": 0, "NeedLevel": 0, "Price": 0, "Stock": 0,
                           "Color": 250, "OverLap": 0, "HP": _integer(donate_row.get("生命"), 0) or 0,
                           "MP": 0, "Light": 0, "Horse": 0},
            })
            database = _upsert_title_definitions(
                database, "赞助称号", sheets["03_赞助称号.xlsx"].rows, 249
            )
            database = _upsert_title_definitions(
                database, "转生", sheets["04_转生.xlsx"].rows, 248
            )
            self._merge_change(changes, target.root, db_relative, database, "initial-camp-title-definitions")

            qfunction_relative = "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction_path = target.envir / "Market_Def" / "QFunction-0.txt"
            qfunction_before = (
                changes[qfunction_relative].after
                if qfunction_relative in changes
                else qfunction_path.read_bytes()
            )
            qfunction_doc = _decode_document(qfunction_before)
            qfunction_text = qfunction_doc.text
            donate_anchor_contents = _donate_anchor_contents(donate_row, donate_title)
            sponsor_anchor_contents = _sponsor_anchor_contents(sheets["03_赞助称号.xlsx"].rows)
            rebirth_anchor_contents = _rebirth_anchor_contents(sheets["04_转生.xlsx"].rows)
            for stale_anchor in (
                "XY_EQUIP_MAKER_POWER_ANCHOR",
                "XY_EQUIP_MAKER_ATTACK_ANCHOR",
                *donate_anchor_contents,
            ):
                qfunction_text = remove_managed_anchor_hook(
                    qfunction_text, LEGACY_DONATE_TITLE_PACKAGE_ID, stale_anchor
                ).text
            managed_anchors = (
                set(sponsor_anchor_contents) | set(donate_anchor_contents) | set(rebirth_anchor_contents)
            )
            for anchor in sorted(managed_anchors):
                content = "\n".join(
                    part for part in (
                        donate_anchor_contents.get(anchor, ""),
                        sponsor_anchor_contents.get(anchor, ""),
                        rebirth_anchor_contents.get(anchor, ""),
                    ) if part
                )
                if content:
                    qfunction_text = install_managed_anchor_hook(
                        qfunction_text, PACKAGE_ID, anchor, content, qfunction_doc.newline,
                        canonical_before_existing_hooks=True,
                    ).text
                else:
                    qfunction_text = remove_managed_anchor_hook(
                        qfunction_text, PACKAGE_ID, anchor
                    ).text
            self._merge_change(
                changes, target.root, qfunction_relative,
                encode_text_document(qfunction_doc, qfunction_text), "initial-camp-sponsor-title-hooks"
            )

            sponsor_rows = sheets["03_赞助称号.xlsx"].rows
            itemdesc_relative = "Mir200/Envir/ItemDescList.txt"
            itemdesc_path = target.root / "Mir200" / "Envir" / "ItemDescList.txt"
            itemdesc_before = (
                changes[itemdesc_relative].after
                if itemdesc_relative in changes
                else (itemdesc_path.read_bytes() if itemdesc_path.exists() else None)
            )
            itemdesc_doc = _decode_document(itemdesc_before)
            self._merge_change(
                changes, target.root, itemdesc_relative,
                _merge_named_description_lines(
                    itemdesc_doc,
                    [_donate_itemdesc_line(donate_row, donate_title), *_sponsor_itemdesc_lines(sponsor_rows)],
                ),
                "initial-camp-sponsor-itemdesc",
            )

            setup_relative = "Mir200/!setup.txt"
            setup_path = target.root / "Mir200" / "!setup.txt"
            setup_before = (
                changes[setup_relative].after
                if setup_relative in changes
                else setup_path.read_bytes()
            )
            setup_doc = _decode_document(setup_before)
            self._merge_change(
                changes, target.root, setup_relative,
                _enable_setup_flags(setup_doc, ("SendItemDescList", "SendTzItemDescList")),
                "initial-camp-enable-title-description",
            )

            fenghao_candidates = ["data/fenghao.dat", "Resources/fenghao.dat"]
            existing_fenghao = [
                relative for relative in fenghao_candidates
                if (client_root / Path(relative.replace("/", "\\"))).is_file()
            ]
            fenghao_targets = existing_fenghao or [fenghao_candidates[0]]
            for fenghao_relative in fenghao_targets:
                fenghao_path = client_root / Path(fenghao_relative.replace("/", "\\"))
                fenghao_doc = (
                    read_text_document(fenghao_path)
                    if fenghao_path.exists()
                    else TextDocument("", "gb18030", "\r\n")
                )
                self._merge_change(
                    changes, client_root, fenghao_relative,
                    _merge_named_description_lines(
                        fenghao_doc,
                        [_donate_fenghao_line(donate_row, donate_title), *_sponsor_fenghao_lines(sponsor_rows)],
                    ),
                    "initial-camp-sponsor-fenghao", scope="client",
                )

            real_changes = [item for item in changes.values() if item.before != item.after]
            plan.warnings.extend(base.warnings)
            plan.warnings.append("狂暴只迁移唯一NPC和入口；费用数量读取01表，灵符统一使用原生GAMEGIRD。")
            plan.warnings.append("圣律之剑、黄金圣物只按XLSX兑换名称与消耗；属性完全读取目标服StdItems，不由平台写入。")
            plan.warnings.append("赞助、转生、圣律之剑、黄金圣物、新手礼包未填完整时只显示待配置，不扣材料。")
            plan.warnings.append("新手礼包码按XLSX校验并一次发放两件绑定装备，仍需在独立服完成一次游戏内验收。")
            plan.warnings.append("转生进度只认翎风原生CHECKRENEWLEVEL；RENEWLEVEL成功后称号仅作显示镜像且不叠加。")
            plan.warnings.append("赞助和转生称号由XLSX称号编号创建；同名称号或Shape占用不一致时阻止安装。")
            plan.warnings.append("赞助属性从XLSX生成处决、韧性、爆率、最大爆率和伤害系数受管钩子。")
            plan.warnings.append("捐献称号严格读取02_捐献.xlsx：攻魔道写称号定义，暴击写原生称号属性0，基础爆率和最大爆率写统一重算钩子；旧打怪伤害与旧最大爆率钩子会安全接管清理。")
            plan.warnings.append("赞助称号说明同步到服务端ItemDescList和客户端fenghao.dat；属性总览只读取称号显示值，不复制实效公式。")
            plan.warnings.append("初始之地事务会启用SendItemDescList与SendTzItemDescList；新说明需由用户重载/重启M2并重新打开客户端后生效。")
            plan.warnings.append("转生神力按引擎原生转生等级接入静态与攻击前双重算：1至10重累计+5%至+50%。")
            plan.install_plan = InstallPlan(
                target_root=base.target_root, client_root=str(client_root),
                package_ids=[*base.package_ids, PACKAGE_ID],
                package_versions={**base.package_versions, PACKAGE_ID: PACKAGE_VERSION},
                parameters={**base.parameters, "materials": str(Path(materials).absolute()), "materials_hash": plan.materials_hash,
                            "npcs": [asdict(item) for item in plan.npcs]},
                changes=real_changes, warnings=plan.warnings, operation_type=plan.operation,
                candidate_packages=list(dict.fromkeys([*base.candidate_packages, PACKAGE_ID])),
                superseded_package_ids=list(dict.fromkeys([*base.superseded_package_ids, LEGACY_PACKAGE_ID])),
            )
            plan.changes = real_changes
        except (OSError, ValueError, InstallError, TextPatchError, SqlitePatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def preflight_selected(
        self,
        server: Path,
        materials: Path,
        selected_features: set[str],
        client: Path | None = None,
        operation: str = "config-sync",
        material_overrides: dict[str, Path] | None = None,
    ) -> InitialCampPlan:
        """Compile only explicitly selected initial-camp documents.

        Donation and sponsor share one historical managed-hook owner.  When either
        document is selected both workbooks are read to rebuild that single shared
        hook without deleting the unselected feature.  Other NPC scripts and
        merchant registrations are not regenerated.
        """
        plan = InitialCampPlan(
            str(Path(server).absolute()), str(Path(materials).absolute()), "",
            operation=operation,
        )
        try:
            spec_by_id = {feature_id: (filename, script_path) for filename, feature_id, script_path in FEATURE_SPECS}
            unknown = sorted(set(selected_features) - set(spec_by_id))
            if unknown:
                raise InitialCampError("未知初始之地配置：" + "、".join(unknown))
            if not selected_features:
                raise InitialCampError("没有选择需要同步的初始之地配置")

            required_ids = set(selected_features)
            if selected_features & {"donate", "sponsor"}:
                required_ids.update({"donate", "sponsor"})
            required_files = tuple(
                filename for filename, feature_id, _script_path in FEATURE_SPECS
                if feature_id in required_ids
            )
            sheets = self.load_materials(materials, required_files, material_overrides)
            selected_files = tuple(
                spec_by_id[feature_id][0]
                for feature_id in sorted(selected_features, key=lambda item: list(spec_by_id).index(item))
            )
            plan.materials_hash = hashlib.sha256(
                "".join(sheets[name].sha256 for name in selected_files).encode()
            ).hexdigest()

            target = TargetInspector.inspect(Path(server))
            needs_client = bool(selected_features & {"donate", "sponsor"})
            client_root: Path | None = None
            if needs_client:
                if client is None:
                    raise InitialCampError("捐献/赞助称号说明需要客户端目录，请先选择同引擎客户端")
                client_root = Path(client).resolve()
                if not client_root.is_dir():
                    raise InitialCampError(f"客户端根目录不存在：{client_root}")
                plan.client = str(client_root)
            elif client is not None:
                candidate = Path(client).resolve()
                if candidate.is_dir():
                    client_root = candidate
                    plan.client = str(candidate)

            map_doc = read_text_document(target.envir / "MapInfo.txt")
            map_file = target.root / "Mir200" / "Map" / _map_file_from_mapinfo(map_doc.text)
            if not map_file.is_file():
                raise InitialCampError(f"初始营地地图文件不存在：{map_file}")
            map_data = map_file.read_bytes()
            width, height, cell_size = _map_geometry(map_data)
            merchant_path = target.envir / "MerChant.txt"
            merchant_doc = (
                read_text_document(merchant_path)
                if merchant_path.exists()
                else TextDocument("", "gb18030", "\r\n")
            )
            selected_specs = [spec for spec in FEATURE_SPECS if spec[1] in selected_features]
            selected_paths = {script_path.casefold() for _filename, _feature, script_path in selected_specs}
            occupancy_text = "\n".join(
                line for line in merchant_doc.text.splitlines()
                if line.split("\t", 1)[0].casefold() not in selected_paths
            )
            occupied = _occupied(occupancy_text, MAP_CODE)
            auto = _auto_positions(map_data, width, height, cell_size, occupied, len(selected_specs))
            used = set(occupied)
            npc_by_id: dict[str, CampNpc] = {}
            for index, (filename, feature_id, script_path) in enumerate(selected_specs):
                sheet = sheets[filename]
                name = _npc_name(_consistent_first(sheet.rows, "NPC名称", filename), filename)
                map_code = _text(_consistent_first(sheet.rows, "地图", filename))
                if map_code.casefold() != MAP_CODE.casefold():
                    raise InitialCampError(f"{filename}：初始之地功能的地图必须填写 {MAP_CODE}")
                x = _integer(_consistent_first(sheet.rows, "X坐标", filename, "自动"))
                y = _integer(_consistent_first(sheet.rows, "Y坐标", filename, "自动"))
                if (x is None) != (y is None):
                    raise InitialCampError(f"{filename}：X/Y坐标必须同时填写或同时留空")
                point = auto[index] if x is None else (x, y)
                point = (int(point[0]), int(point[1]))
                if point in used:
                    raise InitialCampError(f"{filename}：NPC坐标已占用 {point[0]},{point[1]}")
                if not _walkable(map_data, width, height, cell_size, *point):
                    raise InitialCampError(f"{filename}：NPC坐标不可走 {point[0]},{point[1]}")
                used.add(point)
                appearance = _integer(_consistent_first(sheet.rows, "外观", filename))
                if appearance is None or appearance < 0:
                    raise InitialCampError(f"{filename}：外观必须填写非负整数")
                npc = CampNpc(feature_id, name, script_path, map_code, *point, appearance, _status(sheet.rows))
                plan.npcs.append(npc)
                npc_by_id[feature_id] = npc

            requested_packages: list[str] = []
            parameters: dict[str, object] = {}
            if "rage" in selected_features:
                rage_rows = sheets["01_狂暴.xlsx"].rows
                if _status(rage_rows) != "可安装" or len(rage_rows) != 1:
                    raise InitialCampError("01_狂暴.xlsx：唯一狂暴核心要求恰好一行且状态为可安装")
                rage_cost_type, _, rage_cost = _single_cost(rage_rows[0], "狂暴")
                if rage_cost_type != "原生灵符":
                    raise InitialCampError("01_狂暴.xlsx：当前唯一狂暴入口只允许使用原生货币灵符")
                rage_npc = npc_by_id.get("rage")
                if rage_npc is None:
                    filename, script_path = spec_by_id["rage"]
                    rowset = sheets[filename].rows
                    rage_npc = CampNpc(
                        "rage",
                        _npc_name(_consistent_first(rowset, "NPC名称", filename), filename),
                        script_path,
                        _text(_consistent_first(rowset, "地图", filename)),
                        _integer(_consistent_first(rowset, "X坐标", filename), SPAWN[0]) or SPAWN[0],
                        _integer(_consistent_first(rowset, "Y坐标", filename), SPAWN[1]) or SPAWN[1],
                        _integer(_consistent_first(rowset, "外观", filename), 15) or 15,
                        _status(rowset),
                    )
                requested_packages.append("xy.optional.rage.core")
                parameters.update({
                    "rage_npc_map": rage_npc.map_code,
                    "rage_npc_x": rage_npc.x,
                    "rage_npc_y": rage_npc.y,
                    "rage_npc_display": rage_npc.name,
                    "rage_appearance": rage_npc.appearance,
                    "rage_cost": rage_cost,
                    "rage_cost_threshold": rage_cost - 1,
                })
            if "donate" in selected_features:
                requested_packages.append("xy.optional.donate.core")
                donate_rows = sheets["02_捐献.xlsx"].rows
                if _status(donate_rows) != "可安装" or len(donate_rows) != 1:
                    raise InitialCampError("02_捐献.xlsx：唯一捐献核心要求恰好一行且状态为可安装")
                donate_row = donate_rows[0]
                donate_title = _script_token(donate_row.get("称号名称"), "捐献称号名称")
                donate_values = _donate_values(donate_row)
                parameters.update({
                    "donate_title": donate_title,
                    "donate_critical_rate": donate_values["暴击"],
                })
            sponsor_panels: dict[str, object] = {}
            if "sponsor" in selected_features:
                sponsor_panels = self._sponsor_panel_parameters(sheets["03_赞助称号.xlsx"].rows)

            if requested_packages:
                base = self.installer.preflight(
                    target.root,
                    list(dict.fromkeys(requested_packages)),
                    parameters,
                    client_root=client_root,
                    operation_type=operation,
                )
            else:
                qfunction_path = target.envir / "Market_Def" / "QFunction-0.txt"
                if qfunction_path.exists():
                    duplicates = scan_labels(read_text_document(qfunction_path).text).duplicates
                    if duplicates:
                        detail = ", ".join(f"{name}:{lines}" for name, lines in duplicates.items())
                        raise InitialCampError(f"目标脚本存在重复标签，禁止安装：{detail}")
                base = InstallPlan(str(target.root), str(client_root) if client_root else None, [], {}, {}, [])

            changes: dict[str, PlannedChange] = {
                (item.relative_path if item.scope == "server" else f"{item.scope}:{item.relative_path}"): item
                for item in base.changes
            }

            if "sponsor" in selected_features:
                panel_relative = "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt"
                panel_path = target.root / Path(panel_relative.replace("/", "\\"))
                if not panel_path.is_file():
                    raise InitialCampError("目标服尚未安装属性总览；请先安装属性总览成果包，再单独同步赞助表")
                panel_doc = read_text_document(panel_path)
                before = panel_path.read_bytes()
                after = encode_text_document(
                    panel_doc,
                    _sync_sponsor_panel_values(
                        panel_doc.text,
                        sheets["03_赞助称号.xlsx"].rows,
                        panel_doc.newline,
                    ),
                )
                if before != after:
                    changes[panel_relative] = PlannedChange(
                        panel_relative, before, after, "config-sync-sponsor-panel-values", PACKAGE_ID, "server"
                    )

            def staged(relative: str, scope: str = "server") -> bytes | None:
                key = relative if scope == "server" else f"{scope}:{relative}"
                existing = changes.get(key)
                if existing is not None:
                    return existing.after
                root = target.root if scope == "server" else client_root
                if root is None:
                    return None
                path = root / Path(relative.replace("/", "\\"))
                return path.read_bytes() if path.exists() else None

            db_relative = "Mud2/DB/ApexM2.DB"
            database = staged(db_relative)
            if database is None:
                raise InitialCampError("目标服缺少 Mud2/DB/ApexM2.DB")

            scripts: dict[str, str] = {}
            if "donate" in selected_features:
                scripts["donate"] = _donate_script(npc_by_id["donate"].name, donate_title)
                cost_type, cost_name, cost_count = _donate_cost(donate_row)
                config_relative = "Mir200/Envir/QuestDiary/玄渊配置/沙城捐献配置.txt"
                self._merge_change(
                    changes, target.root, config_relative,
                    _config_text(cost_type, cost_name, cost_count).replace("\n", "\r\n").encode("gb18030"),
                    "config-sync-donate-config",
                )
                database = apply_sqlite_upsert(database, {
                    "type": "sqlite_upsert", "table": "StdItems", "unique_key": ["Name"],
                    "conflict_keys": [["StdMode", "Shape"]], "allocate": {"Idx": "max_plus_one"}, "on_conflict": "error",
                    "values": {"Name": donate_title, "StdMode": 70, "Shape": 1, "Weight": 0, "Anicount": 1,
                               "Source": 0, "Reserved": 0, "Looks": 5, "DuraMax": 0, "Ac": 0, "Ac2": 0,
                               "Mac": 0, "Mac2": 0, "Dc": donate_values["攻击下限"], "Dc2": donate_values["攻击上限"],
                               "Mc": donate_values["魔法下限"], "Mc2": donate_values["魔法上限"],
                               "Sc": donate_values["道术下限"], "Sc2": donate_values["道术上限"],
                               "Need": 0, "NeedLevel": 0, "Price": 0, "Stock": 0, "Color": 250,
                               "OverLap": 0, "HP": _integer(donate_row.get("生命"), 0) or 0,
                               "MP": 0, "Light": 0, "Horse": 0},
                })
            if "sponsor" in selected_features:
                scripts["sponsor"] = _sponsor_script(
                    sheets["03_赞助称号.xlsx"].rows, "XY_SPONSOR", npc_by_id["sponsor"].name
                )
                database = _upsert_title_definitions(database, "赞助称号", sheets["03_赞助称号.xlsx"].rows, 249)
            if "rebirth" in selected_features:
                scripts["rebirth"] = _rebirth_script(
                    sheets["04_转生.xlsx"].rows, "XY_REBIRTH", npc_by_id["rebirth"].name
                )
                database = _upsert_title_definitions(database, "转生", sheets["04_转生.xlsx"].rows, 248)
            if "horse" in selected_features:
                scripts["horse"] = _equipment_chain_script(
                    "圣律之剑", npc_by_id["horse"].name, sheets["05_圣律之剑.xlsx"].rows, "XY_HORSE", database
                )
            if "relic" in selected_features:
                scripts["relic"] = _equipment_chain_script(
                    "黄金圣物", npc_by_id["relic"].name, sheets["06_黄金圣物.xlsx"].rows, "XY_RELIC", database
                )
            if "gift" in selected_features:
                scripts["gift"] = _newbie_gift_script(
                    npc_by_id["gift"].name, sheets["07_新手礼包.xlsx"].rows, database
                )

            for npc in plan.npcs:
                if npc.feature_id == "rage":
                    continue
                relative = f"Mir200/Envir/Market_Def/{npc.script_path}-{npc.map_code}.txt"
                self._merge_change(
                    changes, target.root, relative,
                    scripts[npc.feature_id].replace("\n", "\r\n").encode("gb18030"),
                    f"config-sync-{npc.feature_id}-npc-script",
                )

            merchant_relative = "Mir200/Envir/MerChant.txt"
            merchant_before = staged(merchant_relative)
            merchant_stage = _decode_document(merchant_before)
            merchant_text = merchant_stage.text
            for npc in plan.npcs:
                if npc.feature_id == "rage":
                    continue
                line = f"{npc.script_path}\t{npc.map_code}\t{npc.x}\t{npc.y}\t{npc.name}\t0\t{npc.appearance}\t0"
                merchant_text = set_exclusive_unique_line(merchant_text, line, [0], merchant_stage.newline).text
            if any(npc.feature_id != "rage" for npc in plan.npcs):
                self._merge_change(
                    changes, target.root, merchant_relative,
                    encode_text_document(merchant_stage, merchant_text), "config-sync-selected-npc-register",
                )

            if selected_features & {"donate", "sponsor", "rebirth"}:
                self._merge_change(changes, target.root, db_relative, database, "config-sync-title-definitions")

            if selected_features & {"donate", "sponsor", "rebirth"}:
                qfunction_relative = "Mir200/Envir/Market_Def/QFunction-0.txt"
                qfunction_doc = _decode_document(staged(qfunction_relative))
                qfunction_text = qfunction_doc.text
                donate_anchor_contents: dict[str, str] = {}
                sponsor_anchor_contents: dict[str, str] = {}
                rebirth_anchor_contents: dict[str, str] = {}
                if "02_捐献.xlsx" in sheets:
                    donate_row = sheets["02_捐献.xlsx"].rows[0]
                    donate_title = _script_token(donate_row.get("称号名称"), "捐献称号名称")
                    donate_anchor_contents = _donate_anchor_contents(donate_row, donate_title)
                if "03_赞助称号.xlsx" in sheets:
                    sponsor_anchor_contents = _sponsor_anchor_contents(sheets["03_赞助称号.xlsx"].rows)
                if "04_转生.xlsx" in sheets:
                    rebirth_anchor_contents = _rebirth_anchor_contents(sheets["04_转生.xlsx"].rows)
                if "donate" in selected_features:
                    for stale_anchor in (
                        "XY_EQUIP_MAKER_POWER_ANCHOR", "XY_EQUIP_MAKER_ATTACK_ANCHOR", *donate_anchor_contents,
                    ):
                        qfunction_text = remove_managed_anchor_hook(
                            qfunction_text, LEGACY_DONATE_TITLE_PACKAGE_ID, stale_anchor
                        ).text
                changed_anchors: set[str] = set()
                if "donate" in selected_features:
                    changed_anchors.update(donate_anchor_contents)
                if "sponsor" in selected_features:
                    changed_anchors.update(sponsor_anchor_contents)
                if "rebirth" in selected_features:
                    changed_anchors.update(rebirth_anchor_contents)
                for anchor in sorted(changed_anchors):
                    content = "\n".join(
                        part for part in (
                            donate_anchor_contents.get(anchor, ""),
                            sponsor_anchor_contents.get(anchor, ""),
                            rebirth_anchor_contents.get(anchor, ""),
                        ) if part
                    )
                    if content:
                        qfunction_text = install_managed_anchor_hook(
                            qfunction_text, PACKAGE_ID, anchor, content, qfunction_doc.newline,
                        ).text
                    else:
                        qfunction_text = remove_managed_anchor_hook(
                            qfunction_text, PACKAGE_ID, anchor
                        ).text
                self._merge_change(
                    changes, target.root, qfunction_relative,
                    encode_text_document(qfunction_doc, qfunction_text), "config-sync-shared-title-hooks",
                )

            if selected_features & {"donate", "sponsor"}:
                description_lines: list[str] = []
                fenghao_lines: list[str] = []
                if "donate" in selected_features:
                    description_lines.append(_donate_itemdesc_line(donate_row, donate_title))
                    fenghao_lines.append(_donate_fenghao_line(donate_row, donate_title))
                if "sponsor" in selected_features:
                    sponsor_rows = sheets["03_赞助称号.xlsx"].rows
                    description_lines.extend(_sponsor_itemdesc_lines(sponsor_rows))
                    fenghao_lines.extend(_sponsor_fenghao_lines(sponsor_rows))
                itemdesc_relative = "Mir200/Envir/ItemDescList.txt"
                itemdesc_doc = _decode_document(staged(itemdesc_relative))
                self._merge_change(
                    changes, target.root, itemdesc_relative,
                    _merge_named_description_lines(itemdesc_doc, description_lines),
                    "config-sync-title-itemdesc",
                )
                setup_relative = "Mir200/!setup.txt"
                setup_doc = _decode_document(staged(setup_relative))
                self._merge_change(
                    changes, target.root, setup_relative,
                    _enable_setup_flags(setup_doc, ("SendItemDescList", "SendTzItemDescList")),
                    "config-sync-enable-title-description",
                )
                assert client_root is not None
                candidates = ["data/fenghao.dat", "Resources/fenghao.dat"]
                targets = [name for name in candidates if (client_root / Path(name.replace("/", "\\"))).is_file()] or [candidates[0]]
                for relative in targets:
                    document = _decode_document(staged(relative, "client"))
                    self._merge_change(
                        changes, client_root, relative,
                        _merge_named_description_lines(document, fenghao_lines),
                        "config-sync-title-fenghao", scope="client",
                    )

            real_changes = [item for item in changes.values() if item.before != item.after]
            selected_names = [spec_by_id[item][0] for item in selected_features]
            plan.warnings.extend(base.warnings)
            plan.warnings.append("本事务只重建所选文档对应的NPC；未选择的NPC脚本和MerChant注册不参与生成。")
            if selected_features & {"donate", "sponsor"}:
                plan.warnings.append("捐献与赞助共用历史受管属性钩子；预检会读取02和03表重建该共享块，防止未选功能被删除。")
            if "sponsor" in selected_features:
                plan.warnings.append("赞助显示只重绘目标服现有属性总览按钮脚本；不会读取复活名单、迁移狂暴NPC或重装属性总览包。")
            if "rebirth" in selected_features:
                plan.warnings.append("转生只认引擎原生等级并同步静态/攻击前神力双钩子；显示称号不再作为进度或神力权威。")
            plan.warnings.append("实际安装前仍会核对预检后哈希；任一文件变化或占用都会整笔失败并回滚。")
            plan.install_plan = InstallPlan(
                target_root=base.target_root,
                client_root=str(client_root) if client_root else None,
                package_ids=[*base.package_ids, CONFIG_SYNC_PACKAGE_ID],
                package_versions={**base.package_versions, CONFIG_SYNC_PACKAGE_ID: CONFIG_SYNC_PACKAGE_VERSION},
                parameters={
                    **base.parameters,
                    "selected_documents": selected_names,
                    "selected_document_hashes": {name: sheets[name].sha256 for name in selected_files},
                    "materials": str(Path(materials).absolute()),
                    "materials_hash": plan.materials_hash,
                    "npcs": [asdict(item) for item in plan.npcs],
                },
                changes=real_changes,
                warnings=plan.warnings,
                operation_type=operation,
                candidate_packages=list(dict.fromkeys(base.candidate_packages)),
                superseded_package_ids=list(dict.fromkeys(base.superseded_package_ids)),
            )
            plan.changes = real_changes
        except (OSError, ValueError, InstallError, TextPatchError, SqlitePatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: InitialCampPlan):
        if plan.blockers or plan.install_plan is None:
            label = "脚本配置同步" if plan.operation == "config-sync" else "初始之地七NPC导入"
            raise InitialCampError(label + "被阻止：\n" + "\n".join(plan.blockers))
        return self.installer.install(plan.install_plan)

    def rollback_latest(self, server: Path) -> str:
        state = Path(server) / ".xydp" / "installed.json"
        if not state.is_file():
            raise InitialCampError("目标服没有平台安装状态")
        data = json.loads(state.read_text(encoding="utf-8"))
        for transaction in reversed(data.get("transactions", [])):
            receipt = self.root / "backups" / transaction / "receipt.json"
            if receipt.is_file():
                record = json.loads(receipt.read_text(encoding="utf-8"))
                if record.get("operation_type") in {"initial-camp-seven-npc", "initial-camp-six-npc"}:
                    self.installer.rollback(Path(server), transaction)
                    return transaction
        raise InitialCampError("目标服没有可回滚的初始之地七NPC事务")
