from __future__ import annotations

"""Table-driven equipment recycle compiler for LFM2.

The workbook is the only editable business source.  Preflight renders the
whole QFunction/QManage candidate on temporary bytes, validates target item
names and occupied flags, and returns an InstallPlan without writing the
server.  Installation is delegated to the existing byte-transaction core.
"""

import hashlib
import math
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .encoding import TextDocument, encode_text_document, read_text_document
from .installer import InstallPlan, InstallReceipt, Installer, PlannedChange
from .repository import PackageRepository
from .target import TargetInspector, is_executable_running
from .textpatch import (
    TextPatchError,
    add_unique_line,
    ensure_event_label,
    install_event_hook,
    install_managed_block,
    scan_labels,
)
from .user_documents import documents_root


PACKAGE_ID = "xy.optional.recycle.configurable"
PACKAGE_VERSION = "1.0.0-candidate.7"
DEFAULT_WORKBOOK = "19_装备回收配置.xlsx"
QFUNCTION = "Mir200/Envir/Market_Def/QFunction-0.txt"
QMANAGE = "Mir200/Envir/MapQuest_Def/QManage.txt"
USERCMD = "Mir200/Envir/UserCmd.txt"
BUTTON_ID = 21
TIMER_ID = 20
PAGE_SIZE = 18
FLAG_POOL = tuple(range(11, 100))
AUTO_FLAG_POOL = tuple(range(11, 100))
MATERIAL_TIMER_ID = 21
EQUIPMENT_BONUS_QFUNCTION_ANCHOR = "; XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR"
EQUIPMENT_BONUS_QMANAGE_ANCHOR = "; XY_EQUIP_MAKER_RECYCLE_BONUS_QMANAGE_ANCHOR"
EQUIPMENT_BONUS_VARIABLE = "N$XY_RecycleEquipBonus"
EQUIPMENT_BONUS_REWARD_VARIABLE = "N$XY_RecycleBatchBonusReward"

REWARD_COMMANDS = {
    "原生金币": "GOLDCOUNT",
    "原生元宝": "GAMEGOLD",
    "原生灵符": "GAMEGIRD",
    "原生金刚石": "GAMEDIAMOND",
}
REWARD_ALIASES = {
    "金币": "原生金币",
    "元宝": "原生元宝",
    "灵符": "原生灵符",
    "金刚石": "原生金刚石",
    "材料": "背包材料",
    "物品": "背包材料",
}

# Only the game-accepted candidate.9 blocks may be automatically taken over.
_CANDIDATE_HASHES = {
    "qfunction-main": "3333b446efaa182c34e7efa659734fce6425aa3a5c4b020d53ad70685339988f",
    "PlayLogin": "404afb79c46a1c56eaa4e169fe7161365b7d8f9c852c2356b796b20ccb91ef28",
    "PickUpItemEX": "cb511c0f7fa114e8e89ce8766f497e8f985e060463a7adad12040dbd88dcbce5",
    "CustomButtonClick": "be08f2bf116e1fbbca8f9cdcde2fa8798e6cf317fb334cf654bd2beb73f870a7",
    "qmanage-main": "b336a3cefdaf3723d3229af19591d693bd1780e94d5f8ff1a332c75fe0660784",
}

# candidate.6 was game-accepted after the empty-bag/old-count fix, but later
# equipment-bonus insertion left its managed header on the pre-hotfix digest.
# Only these exact marker/body pairs may be normalized before recompilation.
_ACCEPTED_STALE_MANAGED_DIGESTS = {
    "qfunction-main": {
        (
            "3f122dcea6f904462359057666caf497935b2593d2ccb08d3582a77b369051a6",
            "850e8f96ad8b3a5288725a8c971643b7f857e18148bfd98847af32e00455065b",
        ),
    },
    "qmanage-main": {
        (
            "53c5728f6eacdeac8bc57fdbd62c0419e711ee5fafa7b2a950c7e0db0deb2a24",
            "74a89ffda12fa0ecd84c06c9f1e0847cbc1baf09295cad15db602676c6245cac",
        ),
    },
}


class RecycleConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RecycleRule:
    category_id: str
    category_name: str
    item_name: str
    reward_type: str
    reward_name: str
    unit_reward: int
    category_order: int
    item_order: int
    note: str = ""
    extra_reward_type: str = ""
    extra_reward_name: str = ""
    extra_unit_reward: int = 0

    @property
    def reward_specs(self) -> tuple[tuple[str, str, int], ...]:
        rewards = [(self.reward_type, self.reward_name, self.unit_reward)]
        if self.extra_reward_type:
            rewards.append((self.extra_reward_type, self.extra_reward_name, self.extra_unit_reward))
        return tuple(rewards)


@dataclass(frozen=True)
class RecycleCategory:
    id: str
    name: str
    order: int
    rules: tuple[RecycleRule, ...]


@dataclass(frozen=True)
class RecycleWorkbook:
    path: str
    sha256: str
    threshold: int
    page_size: int
    button_id: int
    timer_id: int
    title: str
    categories: tuple[RecycleCategory, ...]
    background_resource: str = ""
    background_frame: int = 0

    @property
    def rules(self) -> tuple[RecycleRule, ...]:
        return tuple(rule for category in self.categories for rule in category.rules)


MATERIAL_RECYCLE_PACKAGE_ID = "xy.optional.material-recycle"
MATERIAL_RECYCLE_PACKAGE_VERSION = "1.0.0-candidate.2"


@dataclass(frozen=True)
class MaterialRecycleWorkbook:
    """Manual, whitelist-only material-to-currency recycle contract."""
    path: str
    sha256: str
    title: str
    categories: tuple[RecycleCategory, ...]
    mode: str = "手动"
    unit: int = 1
    threshold: int = 40
    auto_enabled_default: bool = False
    page_size: int = PAGE_SIZE
    background_resource: str = ""
    background_frame: int = 0

    @property
    def rules(self) -> tuple[RecycleRule, ...]:
        return tuple(rule for category in self.categories for rule in category.rules)


@dataclass(frozen=True)
class RecycleCategoryPlan:
    id: str
    name: str
    flag: int
    page: int
    item_count: int


@dataclass
class RecycleConfigPlan:
    server: str
    workbook: str
    workbook_hash: str
    categories: list[RecycleCategoryPlan] = field(default_factory=list)
    item_names: list[str] = field(default_factory=list)
    reward_types: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    install_plan: InstallPlan | None = None
    operation: str = "recycle-config-update"
    page_count: int = 0


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError) as exc:
        raise RecycleConfigError(f"{field_name}必须填写整数：{value}") from exc
    if number < minimum:
        raise RecycleConfigError(f"{field_name}不能小于{minimum}：{number}")
    return number


def _enabled(value: object) -> bool:
    text = _text(value).casefold()
    if text in {"", "是", "1", "true", "yes", "启用", "可安装"}:
        return True
    if text in {"否", "0", "false", "no", "禁用", "停用"}:
        return False
    raise RecycleConfigError(f"启用列只能填写是或否：{value}")


def _parse_reward(
    row: dict[str, object],
    row_number: int,
    *,
    prefix: str = "",
) -> tuple[str, str, int]:
    type_field = f"{prefix}奖励类型" if prefix else "奖励类型"
    name_field = f"{prefix}奖励名称" if prefix else "奖励名称"
    amount_field = f"{prefix}单件奖励" if prefix else "单件奖励"
    raw_type = row.get(type_field, "")
    raw_name = row.get(name_field, "")
    raw_amount = row.get(amount_field, "")
    if prefix and not any(_text(value) for value in (raw_type, raw_name, raw_amount)):
        return "", "", 0
    reward_type = _text(raw_type)
    if not reward_type:
        raise RecycleConfigError(f"回收明细第{row_number}行{type_field}不能为空")
    reward_type = REWARD_ALIASES.get(reward_type, reward_type)
    reward_name = _text(raw_name)
    if reward_type not in {*REWARD_COMMANDS, "背包材料"}:
        raise RecycleConfigError(f"回收明细第{row_number}行{type_field}无效：{reward_type}")
    if reward_type == "背包材料":
        if not reward_name or len(reward_name) > 40 or re.search(r"[\s<>@;\\]", reward_name):
            raise RecycleConfigError(f"回收明细第{row_number}行{name_field}无效：{reward_name}")
    elif reward_name:
        raise RecycleConfigError(f"回收明细第{row_number}行使用原生货币时{name_field}必须留空")
    unit_reward = _integer(raw_amount, f"回收明细第{row_number}行{amount_field}", minimum=0)
    return reward_type, reward_name, unit_reward


def _split_item_names(value: object, row_number: int) -> tuple[str, ...]:
    """Expand one workbook cell into exact item names.

    A vertical bar or an Excel in-cell newline is an explicit separator.  Each
    expanded name still goes through the original exact-name safety checks;
    fuzzy matching and wildcard expansion are deliberately unsupported.
    """
    raw = _text(value)
    if not raw:
        raise RecycleConfigError(f"回收明细第{row_number}行装备名称不能为空")
    parts = re.split(r"\||\r\n|\r|\n", raw)
    if any(not _text(part) for part in parts):
        raise RecycleConfigError(
            f"回收明细第{row_number}行装备名称存在空项；请删除连续、开头或结尾的分隔符"
        )
    names: list[str] = []
    for part in parts:
        item_name = _text(part)
        if len(item_name) > 40 or re.search(r"[\s<>@;\\]", item_name):
            raise RecycleConfigError(f"回收明细第{row_number}行装备名称无效：{item_name}")
        names.append(item_name)
    return tuple(names)


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return 0
    value = 0
    for letter in letters.group(0):
        value = value * 26 + ord(letter) - 64
    return value - 1


def _cell_value(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> object:
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


def _read_xlsx(path: Path) -> tuple[dict[str, list[list[object]]], str]:
    raw = path.read_bytes()
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    try:
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.findall(".//m:t", ns))
                    for item in root.findall("m:si", ns)
                ]
            book = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", rel_ns)}
            result: dict[str, list[list[object]]] = {}
            for sheet in book.findall("m:sheets/m:sheet", ns):
                name = sheet.attrib["name"]
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
                        values[index] = _cell_value(cell, shared, ns)
                    matrix.append(values)
                result[name] = matrix
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise RecycleConfigError(f"无法读取回收配置表：{exc}") from exc
    return result, hashlib.sha256(raw).hexdigest()


def _rows(matrix: list[list[object]], sheet_name: str) -> list[dict[str, object]]:
    if not matrix:
        raise RecycleConfigError(f"工作表为空：{sheet_name}")
    headers = [_text(value) for value in matrix[0]]
    rows: list[dict[str, object]] = []
    for values in matrix[1:]:
        item = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(_text(value) for value in item.values()):
            rows.append(item)
    return rows


def read_recycle_workbook(path: Path) -> RecycleWorkbook:
    path = Path(path).resolve()
    if not path.is_file():
        raise RecycleConfigError(f"回收配置表不存在：{path}")
    sheets, digest = _read_xlsx(path)
    detail_headers = {_text(value) for value in sheets.get("回收明细", [[]])[0]}
    if "材料名称" in detail_headers:
        return _read_material_recycle_workbook(path, sheets, digest)
    if "基础设置" not in sheets or "回收明细" not in sheets:
        raise RecycleConfigError("回收配置表必须包含“基础设置”和“回收明细”两个工作表")
    settings: dict[str, object] = {}
    for row in _rows(sheets["基础设置"], "基础设置"):
        name = _text(row.get("设置项"))
        if not name:
            continue
        if name in settings:
            raise RecycleConfigError(f"基础设置重复：{name}")
        settings[name] = row.get("值", "")
    threshold = _integer(settings.get("自动回收触发空余格数", 40), "自动回收触发空余格数", minimum=1)
    page_size = _integer(settings.get("每页分类数", PAGE_SIZE), "每页分类数", minimum=1)
    button_id = _integer(settings.get("背包按钮编号", BUTTON_ID), "背包按钮编号", minimum=1)
    timer_id = _integer(settings.get("人物定时器编号", TIMER_ID), "人物定时器编号", minimum=1)
    title = _text(settings.get("面板标题", "装备自动回收")) or "装备自动回收"
    if threshold > 200:
        raise RecycleConfigError("自动回收触发空余格数不能超过200")
    if page_size not in {3, PAGE_SIZE}:
        raise RecycleConfigError("“每页分类数”只接受旧版3或新版18")
    if button_id != BUTTON_ID or timer_id != TIMER_ID:
        raise RecycleConfigError("当前接口固定使用背包按钮21和人物定时器20，不允许在表格中改写")
    if len(title) > 28 or any(char in title for char in "<>@\\\r\n"):
        raise RecycleConfigError(f"面板标题包含脚本不安全字符：{title}")

    required = {"启用", "分类ID", "分类名称", "装备名称", "奖励类型", "奖励名称", "单件奖励", "分类排序", "装备排序"}
    extra_fields = {"附加奖励类型", "附加奖励名称", "附加单件奖励"}
    detail_matrix = sheets["回收明细"]
    headers = {_text(value) for value in detail_matrix[0]} if detail_matrix else set()
    missing = sorted(required - headers)
    if missing:
        raise RecycleConfigError("回收明细缺少字段：" + "、".join(missing))
    extra_present = headers & extra_fields
    if extra_present and extra_present != extra_fields:
        raise RecycleConfigError("回收明细附加奖励字段必须成组出现，缺少：" + "、".join(sorted(extra_fields - headers)))
    has_extra_columns = extra_present == extra_fields

    rules: list[RecycleRule] = []
    item_owners: dict[str, str] = {}
    category_specs: dict[str, tuple[str, int]] = {}
    category_names: dict[str, str] = {}
    for row_number, row in enumerate(_rows(detail_matrix, "回收明细"), start=2):
        if not _enabled(row.get("启用", "是")):
            continue
        category_id = _text(row.get("分类ID"))
        category_name = _text(row.get("分类名称"))
        item_names = _split_item_names(row.get("装备名称"), row_number)
        reward_type, reward_name, unit_reward = _parse_reward(row, row_number)
        if has_extra_columns:
            extra_reward_type, extra_reward_name, extra_unit_reward = _parse_reward(
                row, row_number, prefix="附加"
            )
        else:
            extra_reward_type, extra_reward_name, extra_unit_reward = "", "", 0
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", category_id):
            raise RecycleConfigError(f"回收明细第{row_number}行分类ID无效：{category_id}")
        if not category_name or len(category_name) > 20 or any(char in category_name for char in "<>@/\\\r\n"):
            raise RecycleConfigError(f"回收明细第{row_number}行分类名称无效：{category_name}")
        category_order = _integer(row.get("分类排序"), f"回收明细第{row_number}行分类排序", minimum=1)
        item_order = _integer(row.get("装备排序"), f"回收明细第{row_number}行装备排序", minimum=1)
        spec = (category_name, category_order)
        if category_id in category_specs and category_specs[category_id] != spec:
            raise RecycleConfigError(f"分类{category_id}在不同行的分类名称或排序不一致")
        category_specs[category_id] = spec
        name_key = category_name.casefold()
        if name_key in category_names and category_names[name_key] != category_id:
            raise RecycleConfigError(f"分类名称重复但分类ID不同：{category_name}")
        category_names[name_key] = category_id
        for item_name in item_names:
            identity = item_name.casefold()
            if identity in item_owners:
                raise RecycleConfigError(
                    f"装备名称重复登记：{item_name}（{item_owners[identity]} 与 {category_id}）"
                )
            item_owners[identity] = category_id
            rules.append(RecycleRule(
                category_id=category_id,
                category_name=category_name,
                item_name=item_name,
                reward_type=reward_type,
                reward_name=reward_name,
                unit_reward=unit_reward,
                category_order=category_order,
                item_order=item_order,
                note=_text(row.get("备注")),
                extra_reward_type=extra_reward_type,
                extra_reward_name=extra_reward_name,
                extra_unit_reward=extra_unit_reward,
            ))
    if not rules:
        raise RecycleConfigError("回收明细没有任何启用的装备")
    grouped: dict[str, list[RecycleRule]] = {}
    for rule in rules:
        grouped.setdefault(rule.category_id, []).append(rule)
    if len(grouped) > PAGE_SIZE:
        raise RecycleConfigError(f"回收分类最多支持{PAGE_SIZE}类")
    categories = tuple(
        RecycleCategory(
            category_id,
            category_specs[category_id][0],
            category_specs[category_id][1],
            tuple(sorted(items, key=lambda item: (item.item_order, item.item_name.casefold()))),
        )
        for category_id, items in sorted(grouped.items(), key=lambda item: (category_specs[item[0]][1], item[0]))
    )
    recycle_names = {rule.item_name.casefold() for rule in rules}
    for rule in rules:
        for reward_type, reward_name, _unit_reward in rule.reward_specs:
            if reward_type == "背包材料" and reward_name.casefold() in recycle_names:
                raise RecycleConfigError(f"奖励材料同时位于回收清单，可能形成循环：{reward_name}")
    background_resource = _text(settings.get("面板背景图库", ""))
    background_frame = _integer(settings.get("面板背景帧", 0), "面板背景帧", minimum=0)
    if background_resource and (not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", background_resource) or not background_resource.casefold().endswith(".wzl")):
        raise RecycleConfigError(f"面板背景图库无效：{background_resource}")
    return RecycleWorkbook(str(path), digest, threshold, page_size, button_id, timer_id, title, categories, background_resource, background_frame)


def _read_material_recycle_workbook(
    path: Path,
    sheets: dict[str, list[list[object]]],
    digest: str,
) -> MaterialRecycleWorkbook:
    if "基础设置" not in sheets or "回收明细" not in sheets:
        raise RecycleConfigError("材料回收配置表必须包含“基础设置”和“回收明细”两个工作表")
    settings = {
        _text(row.get("设置项")): row.get("值", "")
        for row in _rows(sheets["基础设置"], "基础设置")
        if _text(row.get("设置项"))
    }
    mode = _text(settings.get("回收模式", "手动"))
    if mode not in {"手动", "自动+手动"}:
        raise RecycleConfigError("材料回收模式只能填写“手动”或“自动+手动”")
    if _integer(settings.get("每次回收单位", 1), "每次回收单位", minimum=1) != 1:
        raise RecycleConfigError("材料回收本轮每次回收单位必须为1")
    if _text(settings.get("货币回收增加适用")) != "否":
        raise RecycleConfigError("材料回收的“货币回收增加适用”必须为否")
    title = _text(settings.get("面板标题", "材料手动回收")) or "材料手动回收"
    threshold = _integer(settings.get("自动回收触发空余格数", 40), "自动回收触发空余格数", minimum=1)
    page_size = _integer(settings.get("每页分类数", PAGE_SIZE), "每页分类数", minimum=1)
    if page_size not in {3, PAGE_SIZE}:
        raise RecycleConfigError("“每页分类数”只接受旧版3或新版18")
    if len(title) > 28 or any(char in title for char in "<>@\\\r\n"):
        raise RecycleConfigError(f"材料回收面板标题包含脚本不安全字符：{title}")
    required = {
        "启用", "分类ID", "分类名称", "材料名称", "奖励类型", "奖励名称", "单件奖励",
        "附加奖励类型", "附加奖励名称", "附加单件奖励", "分类排序", "材料排序", "默认勾选",
    }
    matrix = sheets["回收明细"]
    headers = {_text(value) for value in matrix[0]} if matrix else set()
    missing = sorted(required - headers)
    if missing:
        raise RecycleConfigError("材料回收明细缺少字段：" + "、".join(missing))
    rules: list[RecycleRule] = []
    owners: dict[str, str] = {}
    category_specs: dict[str, tuple[str, int]] = {}
    for row_number, row in enumerate(_rows(matrix, "回收明细"), start=2):
        if not _enabled(row.get("启用", "否")):
            continue
        if _enabled(row.get("默认勾选", "否")):
            raise RecycleConfigError(f"材料回收明细第{row_number}行默认勾选必须为否，需由玩家主动选择")
        category_id = _text(row.get("分类ID"))
        category_name = _text(row.get("分类名称"))
        item_name = _text(row.get("材料名称"))
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", category_id):
            raise RecycleConfigError(f"材料回收明细第{row_number}行分类ID无效：{category_id}")
        if not category_name or len(category_name) > 20 or any(char in category_name for char in "<>@/\\\r\n"):
            raise RecycleConfigError(f"材料回收明细第{row_number}行分类名称无效：{category_name}")
        if not item_name or len(item_name) > 40 or re.search(r"[\s<>@;\\]", item_name):
            raise RecycleConfigError(f"材料回收明细第{row_number}行材料名称无效：{item_name}")
        reward_type, reward_name, unit_reward = _parse_reward(row, row_number)
        extra_type, extra_name, extra_amount = _parse_reward(row, row_number, prefix="附加")
        if reward_type == "背包材料" or extra_type == "背包材料":
            raise RecycleConfigError("材料回收只允许原生货币奖励")
        category_order = _integer(row.get("分类排序"), f"材料回收明细第{row_number}行分类排序", minimum=1)
        item_order = _integer(row.get("材料排序"), f"材料回收明细第{row_number}行材料排序", minimum=1)
        spec = (category_name, category_order)
        if category_id in category_specs and category_specs[category_id] != spec:
            raise RecycleConfigError(f"材料回收分类{category_id}名称或排序不一致")
        category_specs[category_id] = spec
        key = item_name.casefold()
        if key in owners:
            raise RecycleConfigError(f"材料名称重复登记：{item_name}（{owners[key]} 与 {category_id}）")
        owners[key] = category_id
        rules.append(RecycleRule(category_id, category_name, item_name, reward_type, reward_name, unit_reward,
                                 category_order, item_order, _text(row.get("备注")), extra_type, extra_name, extra_amount))
    if not rules:
        raise RecycleConfigError("材料回收明细没有任何启用材料")
    grouped: dict[str, list[RecycleRule]] = {}
    for rule in rules:
        grouped.setdefault(rule.category_id, []).append(rule)
    if len(grouped) > PAGE_SIZE:
        raise RecycleConfigError(f"材料回收分类最多支持{PAGE_SIZE}类")
    categories = tuple(
        RecycleCategory(category_id, category_specs[category_id][0], category_specs[category_id][1],
                        tuple(sorted(items, key=lambda item: (item.item_order, item.item_name.casefold()))))
        for category_id, items in sorted(grouped.items(), key=lambda item: (category_specs[item[0]][1], item[0]))
    )
    background_resource = _text(settings.get("面板背景图库", ""))
    background_frame = _integer(settings.get("面板背景帧", 0), "面板背景帧", minimum=0)
    if background_resource and (not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", background_resource) or not background_resource.casefold().endswith(".wzl")):
        raise RecycleConfigError(f"材料回收面板背景图库无效：{background_resource}")
    return MaterialRecycleWorkbook(str(path), digest, title, categories, mode=mode, threshold=threshold,
                                   page_size=page_size, background_resource=background_resource,
                                   background_frame=background_frame)


def _normalized_hash(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\r\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _repair_known_stale_managed_digest(text: str, kind: str) -> str:
    pattern = re.compile(
        rf"^; XYDP-BEGIN {re.escape(PACKAGE_ID)} SHA256=(?P<sha>[0-9a-f]{{64}})\r?\n"
        rf"(?P<body>.*?)"
        rf"^; XYDP-END {re.escape(PACKAGE_ID)}\r?(?:\n|$)",
        re.MULTILINE | re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return text
    if len(matches) != 1:
        raise RecycleConfigError(f"回收受管块不唯一：{kind}")
    match = matches[0]
    marker = match.group("sha")
    actual = _normalized_hash(match.group("body"))
    if marker == actual:
        return text
    if (marker, actual) not in _ACCEPTED_STALE_MANAGED_DIGESTS.get(kind, set()):
        raise RecycleConfigError(f"回收受管块摘要不一致且不属于已验收版本：{kind}")
    start, end = match.span("sha")
    return text[:start] + actual + text[end:]


def _strip_candidate(text: str, kind: str) -> str:
    if kind == "qfunction-main":
        generic = "; XY-CANDIDATE-BEGIN xy.optional.recycle.panel"
        pattern = re.compile(
            r"^; XY-CANDIDATE-BEGIN xy\.optional\.recycle\.panel candidate\.9\r?\n"
            r"(?P<body>.*?)"
            r"^; XY-CANDIDATE-END xy\.optional\.recycle\.panel\r?(?:\n|$)",
            re.MULTILINE | re.DOTALL,
        )
    elif kind == "qmanage-main":
        generic = "; XY-CANDIDATE-BEGIN xy.optional.recycle.panel OnTimer20"
        pattern = re.compile(
            r"^; XY-CANDIDATE-BEGIN xy\.optional\.recycle\.panel OnTimer20 candidate\.9\r?\n"
            r"(?P<body>.*?)"
            r"^; XY-CANDIDATE-END xy\.optional\.recycle\.panel OnTimer20\r?(?:\n|$)",
            re.MULTILINE | re.DOTALL,
        )
    else:
        generic = f"; XY-CANDIDATE-HOOK-BEGIN xy.optional.recycle.panel {kind}"
        pattern = re.compile(
            rf"^; XY-CANDIDATE-HOOK-BEGIN xy\.optional\.recycle\.panel {re.escape(kind)}\r?\n"
            rf"(?P<body>.*?)"
            rf"^; XY-CANDIDATE-HOOK-END xy\.optional\.recycle\.panel {re.escape(kind)}\r?(?:\n|$)",
            re.MULTILINE | re.DOTALL,
        )
    matches = list(pattern.finditer(text))
    if not matches:
        if generic in text:
            raise RecycleConfigError(f"发现无法识别的旧回收候选块，禁止猜测覆盖：{kind}")
        return text
    if len(matches) != 1:
        raise RecycleConfigError(f"旧回收候选块不唯一：{kind}")
    match = matches[0]
    if _normalized_hash(match.group("body")) != _CANDIDATE_HASHES[kind]:
        raise RecycleConfigError(f"旧回收候选块已被手工修改，禁止接管：{kind}")
    return text[:match.start()] + text[match.end():]


def _strip_known_recycle_regions(text: str) -> str:
    patterns = (
        r"^; XYDP-BEGIN xy\.optional\.recycle\.configurable SHA256=[0-9a-f]{64}\r?\n.*?^; XYDP-END xy\.optional\.recycle\.configurable\r?(?:\n|$)",
        r"^; XYDP-BEGIN xy\.optional\.material-recycle SHA256=[0-9a-f]{64}\r?\n.*?^; XYDP-END xy\.optional\.material-recycle\r?(?:\n|$)",
        r"^; XY-CANDIDATE-BEGIN xy\.optional\.recycle\.panel(?: OnTimer20)? candidate\.9\r?\n.*?^; XY-CANDIDATE-END xy\.optional\.recycle\.panel(?: OnTimer20)?\r?(?:\n|$)",
        r"^; XYDP-HOOK-BEGIN xy\.optional\.recycle\.configurable [^\r\n]+\r?\n.*?^; XYDP-HOOK-END xy\.optional\.recycle\.configurable [^\r\n]+\r?(?:\n|$)",
        r"^; XYDP-HOOK-BEGIN xy\.optional\.material-recycle [^\r\n]+\r?\n.*?^; XYDP-HOOK-END xy\.optional\.material-recycle [^\r\n]+\r?(?:\n|$)",
        r"^; XY-CANDIDATE-HOOK-BEGIN xy\.optional\.recycle\.panel [^\r\n]+\r?\n.*?^; XY-CANDIDATE-HOOK-END xy\.optional\.recycle\.panel [^\r\n]+\r?(?:\n|$)",
        r"^; XYDP-HOOK-BEGIN xy\.optional\.recycle\.bag-entry CustomButtonClick SHA256=[0-9a-f]{64}\r?\n.*?^; XYDP-HOOK-END xy\.optional\.recycle\.bag-entry CustomButtonClick\r?(?:\n|$)",
    )
    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return result


def _existing_mapping(text: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for category_id, flag in re.findall(
        r"^; XY-RECYCLE-CATEGORY ([A-Za-z0-9_.-]+) FLAG=(\d+) STATUS=(?:ACTIVE|RETIRED)\r?$",
        text,
        flags=re.MULTILINE,
    ):
        number = int(flag)
        if category_id in mapping and mapping[category_id] != number:
            raise RecycleConfigError(f"现有回收分类映射重复：{category_id}")
        mapping[category_id] = number
    if "; XY-CANDIDATE-BEGIN xy.optional.recycle.panel candidate.9" in text:
        for category_id, number in (("A", 11), ("B", 12), ("C", 13)):
            mapping.setdefault(category_id, number)
    if len(set(mapping.values())) != len(mapping):
        raise RecycleConfigError("现有回收分类映射存在重复标志位")
    return mapping


def _scan_occupied_flags(envir: Path) -> tuple[set[int], list[str]]:
    occupied: set[int] = set()
    evidence: list[str] = []
    for path in sorted(envir.rglob("*.txt")):
        try:
            text = read_text_document(path).text
        except (OSError, UnicodeError, ValueError):
            continue
        clean = _strip_known_recycle_regions(text)
        found = {int(value) for value in re.findall(r"(?:CHECK|SET)\s+\[(\d{1,3})\]", clean, flags=re.IGNORECASE)}
        if found:
            occupied.update(found)
            evidence.append(f"{path.relative_to(envir).as_posix()}:{','.join(map(str, sorted(found)))}")
    return occupied, evidence


def _allocate_flags(workbook: RecycleWorkbook, qfunction_text: str, envir: Path) -> tuple[dict[str, int], dict[str, int]]:
    existing = _existing_mapping(qfunction_text)
    occupied, evidence = _scan_occupied_flags(envir)
    for category_id, flag in existing.items():
        if flag in occupied:
            detail = next((item for item in evidence if re.search(rf"(?:^|,){flag}(?:,|$)", item.split(":", 1)[-1])), "其他脚本")
            raise RecycleConfigError(f"回收分类{category_id}的标志位[{flag}]已被其他脚本占用：{detail}")
    mapping = dict(existing)
    unavailable = occupied | _all_recycle_reserved_flags(qfunction_text)
    for category in workbook.categories:
        if category.id in mapping:
            continue
        flag = next((value for value in FLAG_POOL if value not in unavailable), None)
        if flag is None:
            raise RecycleConfigError("没有可用的人物标志位，请先清理其他脚本占用")
        mapping[category.id] = flag
        unavailable.add(flag)
    active = {category.id: mapping[category.id] for category in workbook.categories}
    return mapping, active


def _existing_auto_flag(text: str, marker: str) -> int | None:
    found = {int(value) for value in re.findall(rf"^; {re.escape(marker)} FLAG=(\d+)\r?$", text, flags=re.MULTILINE)}
    if len(found) > 1:
        raise RecycleConfigError(f"{marker}映射不唯一")
    return next(iter(found), None)


def _all_recycle_reserved_flags(text: str) -> set[int]:
    values = {
        int(flag)
        for _kind, _category_id, flag in re.findall(
            r"^; XY-(RECYCLE|MATERIAL-RECYCLE)-CATEGORY ([A-Za-z0-9_.-]+) FLAG=(\d+) STATUS=(?:ACTIVE|RETIRED)\r?$",
            text, flags=re.MULTILINE,
        )
    }
    for marker in ("XY-RECYCLE-AUTO-FLAG", "XY-MATERIAL-RECYCLE-AUTO-FLAG"):
        flag = _existing_auto_flag(text, marker)
        if flag is not None:
            values.add(flag)
    return values


def _allocate_auto_flag(text: str, envir: Path, marker: str, reserved: set[int]) -> int:
    existing = _existing_auto_flag(text, marker)
    occupied, evidence = _scan_occupied_flags(envir)
    all_reserved = _all_recycle_reserved_flags(text) | reserved
    if existing is not None:
        if existing in occupied:
            detail = next((item for item in evidence if re.search(rf"(?:^|,){existing}(?:,|$)", item.split(":", 1)[-1])), "其他脚本")
            raise RecycleConfigError(f"{marker}的标志位[{existing}]已被其他脚本占用：{detail}")
        if existing in (all_reserved - {existing}):
            raise RecycleConfigError(f"{marker}的标志位[{existing}]与回收分类或另一自动开关冲突")
        return existing
    flag = next((value for value in AUTO_FLAG_POOL if value not in occupied | all_reserved), None)
    if flag is None:
        raise RecycleConfigError(f"没有可用人物标志位供{marker}使用")
    return flag


def _resolve_dialog_background(envir: Path, resource_name: str) -> int | None:
    if not resource_name:
        return None
    path = envir / "EffectImageList.txt"
    if not path.is_file():
        raise RecycleConfigError(f"面板背景已配置但EffectImageList不存在：{path}")
    entries = read_text_document(path).text.splitlines()
    matches = [index for index, entry in enumerate(entries) if entry.strip().casefold() == resource_name.casefold()]
    if len(matches) != 1:
        raise RecycleConfigError(f"面板背景图库未在EffectImageList唯一登记：{resource_name}")
    return matches[0]


def _allocate_material_flags(workbook: MaterialRecycleWorkbook, text: str, envir: Path) -> tuple[dict[str, int], dict[str, int]]:
    existing = {category_id: int(flag) for category_id, flag in re.findall(r"^; XY-MATERIAL-RECYCLE-CATEGORY ([A-Za-z0-9_.-]+) FLAG=(\d+) STATUS=(?:ACTIVE|RETIRED)\r?$", text, flags=re.MULTILINE)}
    if len(set(existing.values())) != len(existing):
        raise RecycleConfigError("现有材料回收分类映射存在重复标志位")
    equipment = _existing_mapping(text)
    occupied, _evidence = _scan_occupied_flags(envir)
    unavailable = occupied | _all_recycle_reserved_flags(text)
    for category in workbook.categories:
        if category.id not in existing:
            flag = next((value for value in FLAG_POOL if value not in unavailable), None)
            if flag is None:
                raise RecycleConfigError("没有可用的人物标志位供材料回收分类使用")
            existing[category.id] = flag
            unavailable.add(flag)
    return existing, {category.id: existing[category.id] for category in workbook.categories}


def _text_link(text: str, x: int, y: int, color: int, label: str | None = None) -> str:
    return f"<&Text:{text}:{x}:{y}{{FCOLOR={color}}}{f'/{label}' if label else ''}>"


def _open_dialog(background_index: int | None, frame: int) -> list[str]:
    return [] if background_index is None else [f"OPENMERCHANTBIGDLG {background_index} {frame} 1 4 0 -50 1 536 25 1"]


def _panel_main_lines(prefix: str, title: str, threshold: int, categories: tuple[RecycleCategory, ...], flags: dict[str, int], auto_flag: int | None, background_index: int | None, background_frame: int, item_word: str, other_mode: tuple[str, str] | None) -> list[str]:
    """One fixed 3×6 panel. Individual S$ marks avoid a 2^N label tree."""
    parts = prefix.split("_")
    stem = parts[0].upper() + "".join(part.title() for part in parts[1:])
    lines = [f"[@{prefix}_PANEL_MAIN]", "#IF", "#ACT"]
    for ordinal, category in enumerate(categories, 1):
        mark = f"S${stem}Mark{ordinal:03d}"
        lines.extend(["#IF", "#ACT", f"MOV {mark} □", "#IF", f"CHECK [{flags[category.id]}] 1", "#ACT", f"MOV {mark} √"])
    if auto_flag is not None:
        lines.extend(["#IF", "#ACT", f"MOV S${stem}AutoState 自动：关闭", f"MOV S${stem}AutoAction 开启自动", "#IF", f"CHECK [{auto_flag}] 1", "#ACT", f"MOV S${stem}AutoState 自动：开启", f"MOV S${stem}AutoAction 关闭自动"])
    lines.extend(["#IF", "#ACT", *_open_dialog(background_index, background_frame), "#SAY", _text_link(title, 226, 42, 253), _text_link(f"一键回收只处理已勾选{item_word}。", 54, 80, 146), _text_link("第1页 共1页", 400, 80, 146)])
    for ordinal, category in enumerate(categories, 1):
        row, column = divmod(ordinal - 1, 3)
        x, mark_x = ((54, 181), (209, 336), (364, 491))[column]
        y = 105 + row * 29
        lines.extend([_text_link(category.name, x, y, 230), _text_link(f"<$STR(S${stem}Mark{ordinal:03d})>", mark_x, y, 251, f"@{prefix}_TOGGLE_{ordinal:03d}")])
    lines.extend([_text_link(f"一键回收已勾选{item_word}", 54, 295, 251, f"@{prefix}_PANEL_APPLY"), _text_link("取消全部勾选", 245, 295, 146, f"@{prefix}_CLEAR_SELECTIONS")])
    if auto_flag is not None:
        lines.extend([_text_link(f"<$STR(S${stem}AutoState)>", 54, 326, 250), _text_link(f"<$STR(S${stem}AutoAction)>", 245, 326, 251, f"@{prefix}_AUTO_SWITCH")])
    lines.append(_text_link(f"空余少于{threshold}格时自动回收", 54, 350, 146))
    if other_mode:
        lines.append(_text_link(other_mode[0], 364, 350, 218, f"@{other_mode[1]}"))
    lines.extend([_text_link("关闭", 489, 350, 161, "@EXIT"), ""])
    return lines


def _equipment_bonus_blocks(text: str) -> tuple[str, ...]:
    """Read only exact platform-managed equipment recycle bonus blocks.

    Rebuilding the table-driven recycle block must not erase bonus branches
    previously generated from the equipment workbook.  Unknown or hand-edited
    branches are deliberately rejected instead of being guessed or overwritten.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    marker = re.compile(r"^; XY-EQUIP-MAKER (.+): 回收增加\+([0-9]+)%$")
    while index < len(lines):
        match = marker.match(lines[index])
        if not match:
            index += 1
            continue
        item_name, value = match.groups()
        block = lines[index:index + 5]
        expected = [
            lines[index],
            "#IF",
            f"CHECKITEMW {item_name} 1",
            "#ACT",
            f"INC {EQUIPMENT_BONUS_VARIABLE} {value}",
        ]
        if block != expected:
            raise RecycleConfigError(
                f"装备“{item_name}”的回收增加受管块已被修改，已阻止更新回收配置"
            )
        blocks.append("\n".join(block))
        index += 5
    if len(blocks) != len(set(blocks)):
        raise RecycleConfigError("装备回收增加受管块存在重复项，已阻止更新")
    return tuple(blocks)


def _remove_equipment_bonus_blocks(text: str, newline: str) -> str:
    """Remove only validated equipment bonus branches before managed-hash checks."""
    # Validation happens first, so an unknown or edited branch can never be
    # normalized away before the managed-block integrity gate sees it.
    _equipment_bonus_blocks(text)
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    marker = re.compile(r"^; XY-EQUIP-MAKER (.+): 回收增加\+([0-9]+)%$")
    while index < len(lines):
        if marker.match(lines[index]):
            if output and not output[-1].strip():
                output.pop()
            index += 5
            continue
        output.append(lines[index])
        index += 1
    suffix = newline if text.endswith(("\r", "\n")) else ""
    return newline.join(output) + suffix


def _reward_lines(rule: RecycleRule) -> list[str]:
    lines: list[str] = []
    for index, (reward_type, reward_name, unit_reward) in enumerate(rule.reward_specs):
        label = "主奖励" if index == 0 else "附加奖励"
        if unit_reward <= 0:
            lines.append(
                f"SENDMSG 6 回收：{rule.item_name}×<$STR(N$XY_RecycleBatchRemoved)>，{label}为0。"
            )
            continue
        lines.extend([
            "MOV N$XY_RecycleBatchReward 0",
            f"MOV {EQUIPMENT_BONUS_REWARD_VARIABLE} 0",
            f"FORMULATION <$STR(N$XY_RecycleBatchRemoved)>*{unit_reward} N$XY_RecycleBatchReward",
        ])
        lines.extend([
            "FORMULATION "
            f"(<$STR(N$XY_RecycleBatchReward)>*<$STR({EQUIPMENT_BONUS_VARIABLE})>)/100 "
            f"{EQUIPMENT_BONUS_REWARD_VARIABLE}",
            f"INC N$XY_RecycleBatchReward <$STR({EQUIPMENT_BONUS_REWARD_VARIABLE})>",
        ])
        if reward_type == "背包材料":
            lines.append(f"GIVE {reward_name} <$STR(N$XY_RecycleBatchReward)>")
            display = reward_name
        else:
            lines.append(f"{REWARD_COMMANDS[reward_type]} + <$STR(N$XY_RecycleBatchReward)>")
            display = reward_type.removeprefix("原生")
        action = "获得" if index == 0 else "附加获得"
        lines.append(
            f"SENDMSG 6 回收：{rule.item_name}×<$STR(N$XY_RecycleBatchRemoved)>，{action}{display}"
            f"<$STR(N$XY_RecycleBatchReward)>（装备回收增加<$STR({EQUIPMENT_BONUS_VARIABLE})>%）。"
        )
    return lines


def _apply_lines(
    workbook: RecycleWorkbook,
    active_flags: dict[str, int],
    equipment_bonus_blocks: tuple[str, ...] = (),
) -> list[str]:
    lines = [
        "[@XY_RECYCLE_SELECTED_APPLY]",
        "#IF",
        "#ACT",
        f"MOV {EQUIPMENT_BONUS_VARIABLE} 0",
        EQUIPMENT_BONUS_QFUNCTION_ANCHOR,
        *equipment_bonus_blocks,
    ]
    for category in workbook.categories:
        flag = active_flags[category.id]
        for rule in category.rules:
            lines.extend([
                f"; 分类{category.id} => {rule.item_name}",
                "#IF", "#ACT",
                "MOV N$XY_RecycleBatchBefore 0",
                "MOV N$XY_RecycleBatchAfter 0",
                "MOV N$XY_RecycleBatchRemoved 0",
                "#IF", f"CHECK [{flag}] 1", f"CHECKITEM {rule.item_name} 1", "#ACT",
                f"GetItemCount 0 {rule.item_name} N$XY_RecycleBatchBefore",
                f"TAKE {rule.item_name} <$STR(N$XY_RecycleBatchBefore)>",
                f"GetItemCount 0 {rule.item_name} N$XY_RecycleBatchAfter",
                "FORMULATION <$STR(N$XY_RecycleBatchBefore)>-<$STR(N$XY_RecycleBatchAfter)> N$XY_RecycleBatchRemoved",
                "#IF", f"CHECK [{flag}] 1", "LARGE N$XY_RecycleBatchRemoved 0", "#ACT",
                *_reward_lines(rule),
            ])
    lines.extend(["BREAK", ""])
    return lines


def compile_qfunction(
    workbook: RecycleWorkbook,
    all_mapping: dict[str, int],
    active_flags: dict[str, int],
    equipment_bonus_blocks: tuple[str, ...] = (),
    *,
    auto_flag: int = 99,
    background_index: int | None = None,
    material_available: bool = False,
) -> str:
    lines = [
        "; 表格驱动装备回收；分类映射注释用于升级时保留人物勾选状态。",
        f"; XY-RECYCLE-AUTO-FLAG FLAG={auto_flag}",
    ]
    active_ids = set(active_flags)
    for category_id, flag in sorted(all_mapping.items(), key=lambda item: item[1]):
        status = "ACTIVE" if category_id in active_ids else "RETIRED"
        lines.append(f"; XY-RECYCLE-CATEGORY {category_id} FLAG={flag} STATUS={status}")
    lines.extend([
        "",
        "[@UserCmd31]", "#IF", "#ACT", "GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", "",
        "[@XY_RECYCLE_COMMAND]", "#IF", "#ACT", "GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", "",
    ])
    lines.extend(_panel_main_lines("XY_RECYCLE", workbook.title, workbook.threshold, workbook.categories, active_flags, auto_flag, background_index, workbook.background_frame, "装备", ("材料回收", "XY_MATERIAL_RECYCLE_COMMAND") if material_available else None))
    for ordinal, category in enumerate(workbook.categories, start=1):
        flag = active_flags[category.id]
        lines.extend([
            f"[@XY_RECYCLE_TOGGLE_{ordinal:03d}]",
            "#IF", f"CHECK [{flag}] 1", "#ACT", f"SET [{flag}] 0",
            f"GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK",
            "#ELSEACT", f"SET [{flag}] 1", f"GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", "",
        ])
    zero_checks = [f"CHECK [{active_flags[category.id]}] 0" for category in workbook.categories]
    lines.extend([
        "[@XY_RECYCLE_PANEL_APPLY]", "#IF", *zero_checks, "#ACT",
        "MESSAGEBOX 请先勾选至少一个回收分类。", "BREAK", "#ELSEACT",
        "GOTO @XY_RECYCLE_SELECTED_APPLY", "BREAK", "",
        "[@XY_RECYCLE_AUTO_COMMAND]", "#IF", "#ACT", "GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", "",
        "[@XY_RECYCLE_AUTO_SWITCH]", "#IF", f"CHECK [{auto_flag}] 1", "#ACT", "GOTO @XY_RECYCLE_AUTO_DISABLE", "BREAK", "#ELSEACT", "GOTO @XY_RECYCLE_AUTO_ENABLE", "BREAK", "",
        "[@XY_RECYCLE_AUTO_ENABLE]", "#IF", "#ACT", f"SET [{auto_flag}] 1", f"SetOnTimer {workbook.timer_id} 1", "GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", "",
        "[@XY_RECYCLE_AUTO_DISABLE]", "#IF", "#ACT", f"SET [{auto_flag}] 0", f"SetOffTimer {workbook.timer_id}", "GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", "",
        "[@XY_RECYCLE_CLEAR_SELECTIONS]", "#IF", "#ACT",
    ])
    for category in workbook.categories:
        lines.append(f"SET [{active_flags[category.id]}] 0")
    lines.extend(["GOTO @XY_RECYCLE_PANEL_MAIN", "BREAK", ""])
    lines.extend(_apply_lines(workbook, active_flags, equipment_bonus_blocks))
    return "\n".join(lines).rstrip()


def _material_reward_lines(rule: RecycleRule) -> list[str]:
    """Pay only after one material was actually removed; never apply equipment bonus."""
    lines: list[str] = []
    for reward_type, _reward_name, unit_reward in rule.reward_specs:
        lines.extend([
            "MOV N$XY_MaterialRecycleReward 0",
            f"FORMULATION <$STR(N$XY_MaterialRecycleRemoved)>*{unit_reward} N$XY_MaterialRecycleReward",
            f"{REWARD_COMMANDS[reward_type]} + <$STR(N$XY_MaterialRecycleReward)>",
        ])
    return lines


def _material_reward_summary(rule: RecycleRule) -> str:
    return "；".join(
        f"{reward_type.removeprefix('原生')}×{unit_reward}"
        for reward_type, _reward_name, unit_reward in rule.reward_specs
    )


def _material_apply_lines(categories: tuple[RecycleCategory, ...], flags: dict[str, int], label: str) -> list[str]:
    lines = [f"[@{label}]", "#IF", "#ACT"]
    for category in categories:
        for rule in category.rules:
            lines.extend([
                f"; 材料分类{category.id} => {rule.item_name}", "#IF", "#ACT",
                "MOV N$XY_MaterialRecycleBefore 0", "MOV N$XY_MaterialRecycleAfter 0", "MOV N$XY_MaterialRecycleRemoved 0",
                "#IF", f"CHECK [{flags[category.id]}] 1", f"CHECKITEM {rule.item_name} 1", "#ACT",
                f"GetItemCount 0 {rule.item_name} N$XY_MaterialRecycleBefore",
                f"TAKE {rule.item_name} <$STR(N$XY_MaterialRecycleBefore)>",
                f"GetItemCount 0 {rule.item_name} N$XY_MaterialRecycleAfter",
                "FORMULATION <$STR(N$XY_MaterialRecycleBefore)>-<$STR(N$XY_MaterialRecycleAfter)> N$XY_MaterialRecycleRemoved",
                "#IF", "LARGE N$XY_MaterialRecycleRemoved 0", "#ACT", *_material_reward_lines(rule),
            ])
    return lines + ["BREAK", ""]


def compile_material_qfunction(workbook: MaterialRecycleWorkbook, flags: dict[str, int] | None = None, command_id: int = 32, *, all_mapping: dict[str, int] | None = None, auto_flag: int = 98, background_index: int | None = None, equipment_available: bool = False) -> str:
    flags = flags or {category.id: 30 + index for index, category in enumerate(workbook.categories)}
    all_mapping = all_mapping or flags
    auto = auto_flag if workbook.mode == "自动+手动" else None
    lines = ["; 表格驱动材料回收；只处理启用的精确名称，不使用装备回收加成。"]
    if auto is not None:
        lines.append(f"; XY-MATERIAL-RECYCLE-AUTO-FLAG FLAG={auto_flag}")
    for category_id, flag in sorted(all_mapping.items(), key=lambda item: item[1]):
        lines.append(f"; XY-MATERIAL-RECYCLE-CATEGORY {category_id} FLAG={flag} STATUS={'ACTIVE' if category_id in flags else 'RETIRED'}")
    lines.extend([f"[@UserCmd{command_id}]", "#IF", "#ACT", "GOTO @XY_MATERIAL_RECYCLE_COMMAND", "BREAK", "", "[@XY_MATERIAL_RECYCLE_COMMAND]", "#IF", "#ACT", "GOTO @XY_MATERIAL_RECYCLE_PANEL_MAIN", "BREAK", ""])
    lines.extend(_panel_main_lines("XY_MATERIAL_RECYCLE", workbook.title, workbook.threshold, workbook.categories, flags, auto, background_index, workbook.background_frame, "材料", ("装备回收", "XY_RECYCLE_COMMAND") if equipment_available else None))
    for ordinal, category in enumerate(workbook.categories, 1):
        flag = flags[category.id]
        lines.extend([f"[@XY_MATERIAL_RECYCLE_TOGGLE_{ordinal:03d}]", "#IF", f"CHECK [{flag}] 1", "#ACT", f"SET [{flag}] 0", "GOTO @XY_MATERIAL_RECYCLE_PANEL_MAIN", "BREAK", "#ELSEACT", f"SET [{flag}] 1", "GOTO @XY_MATERIAL_RECYCLE_PANEL_MAIN", "BREAK", ""])
    zero_checks = [f"CHECK [{flags[category.id]}] 0" for category in workbook.categories]
    lines.extend(["[@XY_MATERIAL_RECYCLE_PANEL_APPLY]", "#IF", *zero_checks, "#ACT", "MESSAGEBOX 请先勾选至少一个材料分类。", "BREAK", "#ELSEACT", "GOTO @XY_MATERIAL_RECYCLE_SELECTED_APPLY", "BREAK", "", "[@XY_MATERIAL_RECYCLE_CLEAR_SELECTIONS]", "#IF", "#ACT"])
    lines.extend(f"SET [{flags[category.id]}] 0" for category in workbook.categories)
    lines.extend(["GOTO @XY_MATERIAL_RECYCLE_PANEL_MAIN", "BREAK", ""])
    if auto is not None:
        lines.extend(["[@XY_MATERIAL_RECYCLE_AUTO_SWITCH]", "#IF", f"CHECK [{auto}] 1", "#ACT", "GOTO @XY_MATERIAL_RECYCLE_AUTO_DISABLE", "BREAK", "#ELSEACT", "GOTO @XY_MATERIAL_RECYCLE_AUTO_ENABLE", "BREAK", "", "[@XY_MATERIAL_RECYCLE_AUTO_ENABLE]", "#IF", "#ACT", f"SET [{auto}] 1", f"SetOnTimer {MATERIAL_TIMER_ID} 1", "GOTO @XY_MATERIAL_RECYCLE_PANEL_MAIN", "BREAK", "", "[@XY_MATERIAL_RECYCLE_AUTO_DISABLE]", "#IF", "#ACT", f"SET [{auto}] 0", f"SetOffTimer {MATERIAL_TIMER_ID}", "GOTO @XY_MATERIAL_RECYCLE_PANEL_MAIN", "BREAK", ""])
    lines.extend(_material_apply_lines(workbook.categories, flags, "XY_MATERIAL_RECYCLE_SELECTED_APPLY"))
    return "\n".join(lines).rstrip()


def compile_material_qmanage(workbook: MaterialRecycleWorkbook, flags: dict[str, int], auto_flag: int) -> str:
    if workbook.mode != "自动+手动":
        return ""
    lines = [f"[@OnTimer{MATERIAL_TIMER_ID}]", "#IF", f"CHECK [{auto_flag}] 0", "#ACT", f"SetOffTimer {MATERIAL_TIMER_ID}", "BREAK", "", "#IF", f"CHECKBAGSIZE {workbook.threshold}", "#ACT", "BREAK", ""]
    for category in workbook.categories:
        lines.extend(["#IF", f"CHECK [{flags[category.id]}] 1", "#ACT", "GOTO @XY_MATERIAL_RECYCLE_AUTO_TIMER_APPLY", "BREAK"])
    lines.extend(["", *(_material_apply_lines(workbook.categories, flags, "XY_MATERIAL_RECYCLE_AUTO_TIMER_APPLY"))])
    return "\n".join(lines).rstrip()


def compile_qmanage(
    workbook: RecycleWorkbook,
    active_flags: dict[str, int],
    equipment_bonus_blocks: tuple[str, ...] = (),
    *,
    auto_flag: int = 99,
) -> str:
    lines = [
        f"[@OnTimer{workbook.timer_id}]", "#IF", f"CHECK [{auto_flag}] 0", "#ACT",
        f"SetOffTimer {workbook.timer_id}", "BREAK", "",
        "#IF", f"CHECKBAGSIZE {workbook.threshold}", "#ACT", "BREAK", "",
    ]
    for category in workbook.categories:
        lines.extend([
            "#IF", f"CHECK [{active_flags[category.id]}] 1", "#ACT",
            "GOTO @XY_RECYCLE_AUTO_TIMER_APPLY", "BREAK",
        ])
    lines.extend([
        "",
        "[@XY_RECYCLE_AUTO_TIMER_APPLY]",
        "#IF",
        "#ACT",
        f"MOV {EQUIPMENT_BONUS_VARIABLE} 0",
        EQUIPMENT_BONUS_QMANAGE_ANCHOR,
        *equipment_bonus_blocks,
    ])
    for category in workbook.categories:
        flag = active_flags[category.id]
        for rule in category.rules:
            lines.extend([
                f"; 分类{category.id} => {rule.item_name}",
                "#IF", "#ACT",
                "MOV N$XY_RecycleBatchBefore 0",
                "MOV N$XY_RecycleBatchAfter 0",
                "MOV N$XY_RecycleBatchRemoved 0",
                "#IF", f"CHECK [{flag}] 1", f"CHECKITEM {rule.item_name} 1", "#ACT",
                f"GetItemCount 0 {rule.item_name} N$XY_RecycleBatchBefore",
                f"TAKE {rule.item_name} <$STR(N$XY_RecycleBatchBefore)>",
                f"GetItemCount 0 {rule.item_name} N$XY_RecycleBatchAfter",
                "FORMULATION <$STR(N$XY_RecycleBatchBefore)>-<$STR(N$XY_RecycleBatchAfter)> N$XY_RecycleBatchRemoved",
                "#IF", f"CHECK [{flag}] 1", "LARGE N$XY_RecycleBatchRemoved 0", "#ACT",
                *_reward_lines(rule),
            ])
    lines.extend(["BREAK", ""])
    return "\n".join(lines).rstrip()


def _pickup_hook(workbook: RecycleWorkbook, active_flags: dict[str, int], auto_flag: int) -> str:
    lines: list[str] = []
    for category in workbook.categories:
        lines.extend([
            "#IF", f"CHECK [{auto_flag}] 1", f"NOT CHECKBAGSIZE {workbook.threshold}", f"CHECK [{active_flags[category.id]}] 1",
            "#ACT", "GOTO @XY_RECYCLE_SELECTED_APPLY", "BREAK",
        ])
    return "\n".join(lines)


def _decode_bytes(data: bytes | None) -> TextDocument:
    if data is None:
        return TextDocument("", "gb18030", "\r\n")
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        path = Path(handle.name)
        handle.write(data)
    try:
        return read_text_document(path)
    finally:
        path.unlink(missing_ok=True)


def _target_database(server: Path) -> Path:
    candidates = (
        server / "Mud2" / "DB" / "ApexM2.DB",
        server / "Mud2" / "DB" / "StdItems.DB",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise RecycleConfigError("目标服缺少 Mud2/DB/ApexM2.DB（或兼容StdItems.DB）")


def _validate_names(server: Path, workbook: RecycleWorkbook) -> list[str]:
    db = _target_database(server)
    wanted = {rule.item_name for rule in workbook.rules}
    materials = {
        reward_name
        for rule in workbook.rules
        for reward_type, reward_name, _unit_reward in rule.reward_specs
        if reward_type == "背包材料"
    }
    names = sorted(wanted | materials)
    placeholders = ",".join("?" for _ in names)
    try:
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                f"SELECT Name, COUNT(*) FROM StdItems WHERE Name IN ({placeholders}) GROUP BY Name",
                names,
            ).fetchall()
            columns = {str(row[1]).casefold(): str(row[1]) for row in connection.execute("PRAGMA table_info(StdItems)")}
            overlap_column = columns.get("overlap")
            overlap: dict[str, int] = {}
            if materials and overlap_column:
                material_list = sorted(materials)
                marks = ",".join("?" for _ in material_list)
                overlap = {
                    str(name): int(value or 0)
                    for name, value in connection.execute(
                        f"SELECT Name, {overlap_column} FROM StdItems WHERE Name IN ({marks})",
                        material_list,
                    )
                }
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RecycleConfigError(f"无法只读检查StdItems：{exc}") from exc
    counts = {str(name): int(count) for name, count in rows}
    errors = [f"目标服物品不存在：{name}" for name in names if counts.get(name, 0) == 0]
    errors.extend(f"目标服物品名称不唯一：{name}" for name in names if counts.get(name, 0) > 1)
    if errors:
        raise RecycleConfigError("\n".join(errors))
    return [
        f"材料奖励“{name}”不是可叠加物品；大量发放时请游戏内验证背包容量。"
        for name in sorted(materials)
        if overlap.get(name, 0) <= 1
    ]


def _material_user_command(text: str) -> int:
    """Reserve one unused UserCmd without altering equipment recycle's command 31."""
    occupied: dict[int, set[str]] = {}
    existing: set[int] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            command = int(parts[-1])
            occupied.setdefault(command, set()).add(" ".join(parts[:-1]))
            if " ".join(parts[:-1]) == "材料回收":
                existing.add(command)
    conflicts = {command: names for command, names in occupied.items() if len(names) > 1}
    if conflicts:
        raise RecycleConfigError(f"UserCmd命令号存在多名称冲突：{conflicts}")
    if len(existing) > 1:
        raise RecycleConfigError("材料回收存在多个UserCmd命令号，拒绝猜测复用")
    if existing:
        return next(iter(existing))
    for command in range(32, 100):
        if command not in occupied:
            return command
    raise RecycleConfigError("UserCmd 32-99均已占用，无法为材料回收分配独立命令")


def _change(root: Path, relative: str, after: bytes, operation: str, package_id: str = PACKAGE_ID) -> PlannedChange:
    path = root / Path(relative.replace("/", "\\"))
    before = path.read_bytes() if path.exists() else None
    return PlannedChange(relative, before, after, operation, package_id)


class RecycleConfigService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        self.default_workbook = documents_root(self.root) / DEFAULT_WORKBOOK
        self.repository = PackageRepository(self.root / "packages")
        self.repository.refresh()
        self.installer = Installer(self.repository, self.root / "backups")

    def inspect_workbook(self, workbook: Path) -> RecycleWorkbook:
        return read_recycle_workbook(workbook)

    def search(self, workbook: Path, keyword: str) -> list[dict[str, object]]:
        compiled = read_recycle_workbook(workbook)
        wanted = keyword.strip().casefold()
        result: list[dict[str, object]] = []
        for rule in compiled.rules:
            haystack = (
                f"{rule.category_id} {rule.category_name} {rule.item_name} "
                f"{rule.reward_type} {rule.reward_name} {rule.extra_reward_type} {rule.extra_reward_name}"
            ).casefold()
            if not wanted or wanted in haystack:
                result.append({
                    "category_id": rule.category_id,
                    "category_name": rule.category_name,
                    "item_name": rule.item_name,
                    "reward_type": rule.reward_type,
                    "reward_name": rule.reward_name,
                    "unit_reward": rule.unit_reward,
                    "extra_reward_type": rule.extra_reward_type,
                    "extra_reward_name": rule.extra_reward_name,
                    "extra_unit_reward": rule.extra_unit_reward,
                })
        return result

    def preflight(self, workbook_path: Path, server: Path) -> RecycleConfigPlan:
        plan = RecycleConfigPlan(str(Path(server).absolute()), str(Path(workbook_path).absolute()), "")
        try:
            workbook = read_recycle_workbook(workbook_path)
            plan.workbook = workbook.path
            plan.workbook_hash = workbook.sha256
            if isinstance(workbook, MaterialRecycleWorkbook):
                return self._preflight_material(plan, workbook, Path(server))
            target = TargetInspector.inspect(Path(server))
            plan.warnings.extend(_validate_names(target.root, workbook))
            qfunction_path = target.root / Path(QFUNCTION.replace("/", "\\"))
            qmanage_path = target.root / Path(QMANAGE.replace("/", "\\"))
            usercmd_path = target.root / Path(USERCMD.replace("/", "\\"))
            for path in (qfunction_path, qmanage_path, usercmd_path):
                if not path.is_file():
                    raise RecycleConfigError(f"目标脚本不存在：{path}")
            qfunction_doc = read_text_document(qfunction_path)
            qmanage_doc = read_text_document(qmanage_path)
            usercmd_doc = read_text_document(usercmd_path)
            all_mapping, active_flags = _allocate_flags(workbook, qfunction_doc.text, target.envir)
            auto_flag = _allocate_auto_flag(qfunction_doc.text, target.envir, "XY-RECYCLE-AUTO-FLAG", set(all_mapping.values()))
            background_index = _resolve_dialog_background(target.envir, workbook.background_resource)
            material_available = MATERIAL_RECYCLE_PACKAGE_ID in qfunction_doc.text

            qfunction_bonus_blocks = _equipment_bonus_blocks(qfunction_doc.text)
            qmanage_bonus_blocks = _equipment_bonus_blocks(qmanage_doc.text)
            if sorted(qfunction_bonus_blocks) != sorted(qmanage_bonus_blocks):
                raise RecycleConfigError(
                    "QFunction与QManage中的装备回收增加受管块不一致，已阻止更新"
                )

            qf_text = _remove_equipment_bonus_blocks(qfunction_doc.text, qfunction_doc.newline)
            qf_text = _repair_known_stale_managed_digest(qf_text, "qfunction-main")
            qf_text = _strip_candidate(qf_text, "qfunction-main")
            for event in ("PlayLogin", "PickUpItemEX", "CustomButtonClick"):
                qf_text = _strip_candidate(qf_text, event)
            qm_text = _remove_equipment_bonus_blocks(qmanage_doc.text, qmanage_doc.newline)
            qm_text = _repair_known_stale_managed_digest(qm_text, "qmanage-main")
            qm_text = _strip_candidate(qm_text, "qmanage-main")

            qf_content = compile_qfunction(
                workbook, all_mapping, active_flags, qfunction_bonus_blocks,
                auto_flag=auto_flag, background_index=background_index, material_available=material_available,
            )
            qf_text = install_managed_block(
                qf_text, PACKAGE_ID, qf_content, qfunction_doc.newline,
                legacy_package_ids=("xy.optional.recycle.core",),
            ).text
            for event in ("PlayLogin", "PickUpItemEX", "CustomButtonClick"):
                qf_text = ensure_event_label(qf_text, PACKAGE_ID, event, qfunction_doc.newline).text
            qf_text = install_event_hook(
                qf_text, PACKAGE_ID, "PlayLogin",
                f"#IF\nCHECK [{auto_flag}] 1\n#ACT\nSetOnTimer {workbook.timer_id} 1",
                qfunction_doc.newline,
            ).text
            qf_text = install_event_hook(
                qf_text, PACKAGE_ID, "PickUpItemEX", _pickup_hook(workbook, active_flags, auto_flag),
                qfunction_doc.newline,
            ).text
            qf_text = install_event_hook(
                qf_text, PACKAGE_ID, "CustomButtonClick",
                f"#IF\nEQUAL <$CustomButtonID> {workbook.button_id}\n#ACT\nGOTO @XY_RECYCLE_PANEL_MAIN\nBREAK",
                qfunction_doc.newline,
                legacy_package_ids=("xy.optional.recycle.bag-entry",),
            ).text

            if re.search(rf"^\[@OnTimer{workbook.timer_id}\]\s*$", _strip_known_recycle_regions(qm_text), re.MULTILINE | re.IGNORECASE):
                raise RecycleConfigError(f"人物定时器OnTimer{workbook.timer_id}已被其他脚本占用")
            qm_text = install_managed_block(
                qm_text,
                PACKAGE_ID,
                compile_qmanage(workbook, active_flags, qmanage_bonus_blocks, auto_flag=auto_flag),
                qmanage_doc.newline,
            ).text
            usercmd_text = add_unique_line(
                usercmd_doc.text, "快捷回收\t31", [0], usercmd_doc.newline,
            ).text

            qf_labels = scan_labels(qf_text)
            qm_labels = scan_labels(qm_text)
            if qf_labels.duplicates:
                raise RecycleConfigError(f"生成后的QFunction存在重复标签：{qf_labels.duplicates}")
            if qm_labels.duplicates:
                raise RecycleConfigError(f"生成后的QManage存在重复标签：{qm_labels.duplicates}")
            if "\x00" in qf_text or "\x00" in qm_text:
                raise RecycleConfigError("生成脚本包含空字符")

            changes = [
                _change(target.root, QFUNCTION, encode_text_document(TextDocument(qf_text, qfunction_doc.encoding, qfunction_doc.newline, qfunction_doc.bom)), "recycle-qfunction"),
                _change(target.root, QMANAGE, encode_text_document(TextDocument(qm_text, qmanage_doc.encoding, qmanage_doc.newline, qmanage_doc.bom)), "recycle-qmanage"),
                _change(target.root, USERCMD, encode_text_document(TextDocument(usercmd_text, usercmd_doc.encoding, usercmd_doc.newline, usercmd_doc.bom)), "recycle-user-command"),
            ]
            plan.changes = [change for change in changes if change.before != change.after]
            plan.categories = [
                RecycleCategoryPlan(
                    category.id, category.name, active_flags[category.id],
                    1, len(category.rules),
                )
                for category in workbook.categories
            ]
            plan.page_count = 1
            plan.item_names = [rule.item_name for rule in workbook.rules]
            plan.reward_types = sorted({
                reward_type
                for rule in workbook.rules
                for reward_type, _reward_name, _unit_reward in rule.reward_specs
            })
            plan.warnings.append("M2运行时也允许生成脚本；新配置需由你重载或重启M2后才会生效。")
            if is_executable_running(target.mir200 / "M2Server.exe"):
                plan.warnings.append("检测到M2Server.exe正在运行：本次只提示，不阻止预检或确认更新。")
            plan.install_plan = InstallPlan(
                target_root=str(target.root), client_root=None,
                package_ids=[PACKAGE_ID], package_versions={PACKAGE_ID: PACKAGE_VERSION},
                parameters={
                    "workbook": workbook.path,
                    "workbook_hash": workbook.sha256,
                    "threshold": workbook.threshold,
                    "page_size": workbook.page_size,
                    "category_flags": active_flags, "auto_flag": auto_flag,
                    "category_count": len(workbook.categories),
                    "item_count": len(workbook.rules),
                },
                changes=plan.changes,
                warnings=list(plan.warnings),
                operation_type=plan.operation,
                candidate_packages=[PACKAGE_ID],
                superseded_package_ids=[
                    "xy.optional.recycle.core",
                    "xy.optional.recycle.auto",
                    "xy.optional.recycle.bonus",
                    "xy.optional.recycle.bag-entry",
                ],
            )
        except (OSError, ValueError, RuntimeError, TextPatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def _preflight_material(
        self,
        plan: RecycleConfigPlan,
        workbook: MaterialRecycleWorkbook,
        server: Path,
    ) -> RecycleConfigPlan:
        plan.operation = "material-recycle-config"
        try:
            target = TargetInspector.inspect(server)
            plan.warnings.extend(_validate_names(target.root, workbook))
            qfunction_path = target.root / Path(QFUNCTION.replace("/", "\\"))
            qmanage_path = target.root / Path(QMANAGE.replace("/", "\\"))
            usercmd_path = target.root / Path(USERCMD.replace("/", "\\"))
            required_paths = (qfunction_path, usercmd_path, qmanage_path) if workbook.mode == "自动+手动" else (qfunction_path, usercmd_path)
            for path in required_paths:
                if not path.is_file():
                    raise RecycleConfigError(f"目标脚本不存在：{path}")
            qfunction_doc = read_text_document(qfunction_path)
            usercmd_doc = read_text_document(usercmd_path)
            qmanage_doc = read_text_document(qmanage_path) if workbook.mode == "自动+手动" else None
            command_id = _material_user_command(usercmd_doc.text)
            all_material_mapping, flags = _allocate_material_flags(workbook, qfunction_doc.text, target.envir)
            auto_flag = _allocate_auto_flag(qfunction_doc.text, target.envir, "XY-MATERIAL-RECYCLE-AUTO-FLAG", set(flags.values()) | set(_existing_mapping(qfunction_doc.text).values())) if workbook.mode == "自动+手动" else None
            background_index = _resolve_dialog_background(target.envir, workbook.background_resource)
            equipment_available = PACKAGE_ID in qfunction_doc.text
            qf_text = install_managed_block(
                qfunction_doc.text, MATERIAL_RECYCLE_PACKAGE_ID,
                compile_material_qfunction(workbook, flags, command_id, all_mapping=all_material_mapping, auto_flag=auto_flag or 98, background_index=background_index, equipment_available=equipment_available), qfunction_doc.newline,
            ).text
            if workbook.mode == "自动+手动":
                qf_text = ensure_event_label(qf_text, MATERIAL_RECYCLE_PACKAGE_ID, "PlayLogin", qfunction_doc.newline).text
                qf_text = ensure_event_label(qf_text, MATERIAL_RECYCLE_PACKAGE_ID, "PickUpItemEX", qfunction_doc.newline).text
                qf_text = install_event_hook(qf_text, MATERIAL_RECYCLE_PACKAGE_ID, "PlayLogin", f"#IF\nCHECK [{auto_flag}] 1\n#ACT\nSetOnTimer {MATERIAL_TIMER_ID} 1", qfunction_doc.newline).text
                material_pickup = "\n".join(["#IF", f"CHECK [{auto_flag}] 1", f"NOT CHECKBAGSIZE {workbook.threshold}", "#ACT", "GOTO @XY_MATERIAL_RECYCLE_SELECTED_APPLY", "BREAK"])
                qf_text = install_event_hook(qf_text, MATERIAL_RECYCLE_PACKAGE_ID, "PickUpItemEX", material_pickup, qfunction_doc.newline).text
            labels = scan_labels(qf_text)
            if labels.duplicates:
                raise RecycleConfigError(f"生成后的QFunction存在重复标签：{labels.duplicates}")
            usercmd_text = add_unique_line(
                usercmd_doc.text, f"材料回收\t{command_id}", [0], usercmd_doc.newline,
            ).text
            changes = [
                _change(target.root, QFUNCTION, encode_text_document(TextDocument(qf_text, qfunction_doc.encoding, qfunction_doc.newline, qfunction_doc.bom)), "material-recycle-qfunction", MATERIAL_RECYCLE_PACKAGE_ID),
                _change(target.root, USERCMD, encode_text_document(TextDocument(usercmd_text, usercmd_doc.encoding, usercmd_doc.newline, usercmd_doc.bom)), "material-recycle-user-command", MATERIAL_RECYCLE_PACKAGE_ID),
            ]
            if qmanage_doc is not None:
                if re.search(rf"^\[@OnTimer{MATERIAL_TIMER_ID}\]\s*$", _strip_known_recycle_regions(qmanage_doc.text), re.MULTILINE | re.IGNORECASE):
                    raise RecycleConfigError(f"人物定时器OnTimer{MATERIAL_TIMER_ID}已被其他脚本占用")
                qm_text = install_managed_block(qmanage_doc.text, MATERIAL_RECYCLE_PACKAGE_ID, compile_material_qmanage(workbook, flags, auto_flag or 98), qmanage_doc.newline).text
                changes.append(_change(target.root, QMANAGE, encode_text_document(TextDocument(qm_text, qmanage_doc.encoding, qmanage_doc.newline, qmanage_doc.bom)), "material-recycle-qmanage", MATERIAL_RECYCLE_PACKAGE_ID))
            plan.changes = [change for change in changes if change.before != change.after]
            first_rule_position = 1
            plan.categories = []
            for category in workbook.categories:
                plan.categories.append(RecycleCategoryPlan(category.id, category.name, flags[category.id], 1, len(category.rules)))
                first_rule_position += len(category.rules)
            plan.page_count = 1
            plan.item_names = [rule.item_name for rule in workbook.rules]
            plan.reward_types = sorted({reward_type for rule in workbook.rules for reward_type, _name, _amount in rule.reward_specs})
            plan.warnings.append("材料回收仅处理启用精确白名单；不会写入装备回收加成变量或锚点。")
            plan.install_plan = InstallPlan(
                target_root=str(target.root), client_root=None,
                package_ids=[MATERIAL_RECYCLE_PACKAGE_ID], package_versions={MATERIAL_RECYCLE_PACKAGE_ID: MATERIAL_RECYCLE_PACKAGE_VERSION},
                parameters={"workbook": workbook.path, "workbook_hash": workbook.sha256, "mode": workbook.mode,
                            "unit": workbook.unit, "user_command": command_id, "item_count": len(workbook.rules), "category_flags": flags, "auto_flag": auto_flag, "timer_id": MATERIAL_TIMER_ID if auto_flag is not None else None},
                changes=plan.changes, warnings=list(plan.warnings), operation_type=plan.operation,
                candidate_packages=[MATERIAL_RECYCLE_PACKAGE_ID], superseded_package_ids=[],
            )
        except (OSError, ValueError, RuntimeError, TextPatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: RecycleConfigPlan) -> InstallReceipt:
        if plan.blockers or plan.install_plan is None:
            raise RecycleConfigError("回收配置被阻止：\n" + "\n".join(plan.blockers))
        workbook = Path(plan.workbook)
        if not workbook.is_file() or hashlib.sha256(workbook.read_bytes()).hexdigest() != plan.workbook_hash:
            raise RecycleConfigError("预检后回收配置表已变化，请重新预检")
        if not plan.changes:
            raise RecycleConfigError("没有需要应用的变更，目标已处于当前回收配置")
        return self.installer.install(plan.install_plan)

    def rollback(self, server: Path, transaction_id: str) -> str:
        self.installer.rollback(server, transaction_id)
        return transaction_id
