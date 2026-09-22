from __future__ import annotations

"""Workbook-driven equipment collection candidate for LFM2.

The workbook contains equipment names, never donor item indexes.  Preflight
resolves every enabled name against the target server's unique ``StdItems``
row and compiles ``ItemShow:<target Idx>``.  This keeps equipment appearance
and hover attributes owned by the target server/client rather than by the
donor version.
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
    install_event_hook,
    install_managed_anchor_hook,
    install_managed_block,
    remove_managed_anchor_hook,
    scan_labels,
)
from .user_documents import documents_root


PACKAGE_ID = "xy.optional.equipment-collection"
PACKAGE_VERSION = "1.0.0-candidate.13"
DEFAULT_WORKBOOK = "33_装备收集图鉴.xlsx"
QFUNCTION = "Mir200/Envir/Market_Def/QFunction-0.txt"
QMANAGE = "Mir200/Envir/MapQuest_Def/QManage.txt"
USERCMD = "Mir200/Envir/UserCmd.txt"
EFFECT_IMAGE_LIST = "Mir200/Envir/EffectImageList.txt"
GRAPHIC_RESOURCE_ENTRY = "XY_EquipmentCollection.wz"
GRAPHIC_WZL = "XY_EquipmentCollection.wzl"
GRAPHIC_WZX = "XY_EquipmentCollection.wzx"
GRAPHIC_WZL_SHA256 = "81a6229e3e8b1a00914cc0fd2996eb288b09d14d6a6c4b022e5473641cb3bd96"
GRAPHIC_WZX_SHA256 = "bb0ac9eba56450cf0441b24759ae250a80156bd46b5fadded78a2e11956c88bc"
GRAPHIC_CLIENT_WZL = f"data/{GRAPHIC_WZL}"
GRAPHIC_CLIENT_WZX = f"data/{GRAPHIC_WZX}"
GRAPHIC_PAGE_SIZE = 21
GRAPHIC_CATEGORY_PAGE_SIZE = 6
REWARD_HOVER_LABEL = "鼠标移此可显示点亮属性"
REWARD_HOVER_X = 525
REWARD_HOVER_Y = 27
PAGE_INFO_X = 70
PAGE_INFO_Y = 27
DONE_COUNT_X = 70
DONE_COUNT_Y = 49
BATCH_COLLECT_X = 525
BATCH_COLLECT_Y = 49
ATTR_OVERVIEW = "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt"
ATTR_OVERVIEW_DAMAGE_COEFFICIENT_ANCHOR = "XY_EQUIPMENT_COLLECTION_DAMAGE_COEFFICIENT_DISPLAY_ANCHOR"
ITEM_FLAG_START = 400
GROUP_FLAG_START = 600
MAX_COLLECTION_ID = 5000
MAX_CATEGORY_COUNT = 100
COLLECTION_VAR_FILE = r"..\QuestDiary\XY_System\XuanYuanCollectionVar.txt"
COLLECTION_STATE_RELATIVE = "Mir200/Envir/QuestDiary/XY_System/XuanYuanCollectionVar.txt"


BASE_FIELDS = (
    "攻击下限", "攻击上限", "魔法下限", "魔法上限", "道术下限", "道术上限",
    "防御下限", "防御上限", "魔御下限", "魔御上限", "HP", "MP",
)
SPECIAL_FIELDS = (
    "神力倍攻%", "打怪伤害%", "暴击伤害%", "固定切割", "爆率%", "最大爆率%",
    "首刀斩杀%", "尾刀斩杀%", "鞭尸概率%", "处决%", "韧性", "处决倍率%",
    "处决时间秒", "伤害系数%", "对怪吸收%", "伤害吸收上限%", "吸血%",
    "每秒回血", "回收增加%",
)
REWARD_FIELDS = BASE_FIELDS + SPECIAL_FIELDS


ABILITY_IDS = {
    "防御下限": 1, "防御上限": 2, "魔御下限": 3, "魔御上限": 4,
    "攻击下限": 5, "攻击上限": 6, "魔法下限": 7, "魔法上限": 8,
    "道术下限": 9, "道术上限": 10, "HP": 11, "MP": 12,
}


# field -> (target, anchor, script action)
SPECIAL_OUTLETS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "神力倍攻%": (
        ("qfunction", "XY_EQUIP_MAKER_POWER_ANCHOR", "INC N$倍攻 {value}"),
        ("qfunction", "XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR", "INC N$XY_RT_Power {value}"),
    ),
    "打怪伤害%": (
        ("qfunction", "XY_EQUIP_MAKER_POWER_ANCHOR", "INC N$XY_PVE {value}"),
        ("qfunction", "XY_EQUIP_MAKER_ATTACK_ANCHOR", "INC N$XY_PVE_Extra {value}"),
    ),
    "暴击伤害%": (
        ("qfunction", "XY_EQUIP_MAKER_BLAST_ANCHOR", "INC N$XY_最终爆伤 {value}"),
        ("qfunction", "XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR", "INC N$XY_RT_Blast {value}"),
    ),
    "固定切割": (("qfunction", "XY_EQUIP_MAKER_ATTACK_ANCHOR", "ChangeDamageValue 0 + {value}"),),
    "爆率%": (
        ("qfunction", "XY_EQUIP_MAKER_DROP_ANCHOR", "INC N$XY_最终爆率 {value}"),
        ("qfunction", "XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR", "INC N$XY_RT_Drop {value}"),
    ),
    "最大爆率%": (
        ("qfunction", "XY_EQUIP_MAKER_DROP_ANCHOR", "INC N$XY_最大爆率 {value}"),
        ("qfunction", "XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR", "INC N$XY_RT_DropMax {value}"),
    ),
    "首刀斩杀%": (("qfunction", "XY_EQUIP_MAKER_ATTACK_ANCHOR", "INC N$XY_FirstKillRate {value}"),),
    "尾刀斩杀%": (("qfunction", "XY_EQUIP_MAKER_ATTACK_ANCHOR", "INC N$XY_TailKillRate {value}"),),
    "鞭尸概率%": (("qfunction", "XY_EQUIP_MAKER_CORPSE_ANCHOR", "INC N$XY_CorpseRate {value}"),),
    "处决%": (("qfunction", "XY_EXECUTION_LAB_CHANCE_ANCHOR", "INC N$XY_EXEC_ChanceBP {value}00"),),
    "韧性": (("qfunction", "XY_EXECUTION_LAB_TOUGHNESS_ANCHOR", "INC N$XY_EXEC_Toughness {value}"),),
    "处决倍率%": (("qfunction", "XY_EXECUTION_LAB_PVE_BONUS_ANCHOR", "INC N$XY_EXEC_PVEEquipBonusPercent {value}"),),
    "处决时间秒": (("qfunction", "XY_EXECUTION_LAB_PVE_DURATION_ANCHOR", "INC N$XY_EXEC_PVEEquipDurationMs {value}000"),),
    "伤害系数%": (("qfunction", "XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR", "INC N$XY_RT_DamageCoeff {value}"),),
    "对怪吸收%": (("qfunction", "XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR", "INC N$XY_MDA_Raw {value}"),),
    "伤害吸收上限%": (("qfunction", "XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR", "INC N$XY_MDA_CapBonus {value}"),),
    "吸血%": (("qfunction", "XY_EQUIP_MAKER_LIFESTEAL_ANCHOR", "INC N$XY_SUS_LifeSteal {value}"),),
    "每秒回血": (
        ("qfunction", "XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR", "MOV N$XY_SUS_HPActive 1"),
        ("qmanage", "XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR", "HumanHP + {value}"),
    ),
    "回收增加%": (
        ("qfunction", "XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR", "INC N$XY_RecycleEquipBonus {value}"),
        ("qmanage", "XY_EQUIP_MAKER_RECYCLE_BONUS_QMANAGE_ANCHOR", "INC N$XY_RecycleEquipBonus {value}"),
    ),
}


class EquipmentCollectionError(ValueError):
    pass


@dataclass(frozen=True)
class CollectionReward:
    values: dict[str, int]

    @property
    def nonzero(self) -> dict[str, int]:
        return {name: value for name, value in self.values.items() if value}


@dataclass(frozen=True)
class CollectionItem:
    collection_id: int
    category_id: str
    category_name: str
    category_order: int
    item_order: int
    item_name: str
    required_count: int
    consume: bool
    reward: CollectionReward
    note: str = ""

    @property
    def flag(self) -> int:
        return ITEM_FLAG_START + self.collection_id - 1


@dataclass(frozen=True)
class CollectionGroupReward:
    category_id: str
    category_name: str
    category_order: int
    reward: CollectionReward
    message: str
    note: str = ""


@dataclass(frozen=True)
class CollectionCategory:
    category_id: str
    category_name: str
    category_order: int
    note: str = ""


@dataclass(frozen=True)
class CollectionWorkbook:
    path: str
    sha256: str
    title: str
    page_size: int
    player_command: str
    usercmd_number: int
    items: tuple[CollectionItem, ...]
    groups: tuple[CollectionGroupReward, ...]
    categories: tuple[CollectionCategory, ...] = ()


@dataclass(frozen=True)
class ResolvedCollectionItem:
    item: CollectionItem
    idx: int
    stdmode: int
    shape: int
    looks: int


@dataclass
class EquipmentCollectionPlan:
    server: str
    workbook: str
    workbook_hash: str
    client: str = ""
    resource_id: int = -1
    items: list[dict[str, object]] = field(default_factory=list)
    group_flags: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    install_plan: InstallPlan | None = None
    operation: str = "equipment-collection-config"


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _integer(value: object, field_name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError) as exc:
        raise EquipmentCollectionError(f"{field_name}必须填写整数：{value}") from exc
    if number < minimum or (maximum is not None and number > maximum):
        suffix = f"且不能大于{maximum}" if maximum is not None else ""
        raise EquipmentCollectionError(f"{field_name}不能小于{minimum}{suffix}：{number}")
    return number


def _enabled(value: object) -> bool:
    text = _text(value).casefold()
    if text in {"是", "1", "true", "yes", "启用", "可安装"}:
        return True
    if text in {"", "否", "0", "false", "no", "禁用", "停用"}:
        return False
    raise EquipmentCollectionError(f"状态列只能填写是或否：{value}")


def _column_index(reference: str) -> int:
    match = re.match(r"[A-Z]+", reference.upper())
    if not match:
        return 0
    value = 0
    for letter in match.group(0):
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
                    row_number = int(row.attrib.get("r", len(matrix) + 1))
                    while len(matrix) < row_number:
                        matrix.append([])
                    values = matrix[row_number - 1]
                    for cell in row.findall("m:c", ns):
                        index = _column_index(cell.attrib.get("r", "A1"))
                        while len(values) <= index:
                            values.append("")
                        values[index] = _cell_value(cell, shared, ns)
                result[name] = matrix
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise EquipmentCollectionError(f"无法读取装备收集配置表：{exc}") from exc
    return result, hashlib.sha256(raw).hexdigest()


def _rows(matrix: list[list[object]], sheet_name: str, header_row: int = 0) -> list[dict[str, object]]:
    if len(matrix) <= header_row:
        raise EquipmentCollectionError(f"工作表缺少表头：{sheet_name}")
    headers = [_text(value) for value in matrix[header_row]]
    rows: list[dict[str, object]] = []
    for values in matrix[header_row + 1:]:
        item = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(_text(value) for value in item.values()):
            rows.append(item)
    return rows


def _safe_name(value: object, field_name: str, *, maximum: int = 40) -> str:
    name = _text(value)
    if not name or len(name) > maximum or re.search(r"[<>@;\\\r\n\t]", name):
        raise EquipmentCollectionError(f"{field_name}无效：{name}")
    return name


def _reward(row: dict[str, object], row_number: int, sheet_name: str) -> CollectionReward:
    values: dict[str, int] = {}
    for field_name in REWARD_FIELDS:
        raw = row.get(field_name, "")
        values[field_name] = 0 if _text(raw) == "" else _integer(
            raw, f"{sheet_name}第{row_number}行{field_name}", minimum=0
        )
    return CollectionReward(values)


def read_collection_workbook(path: Path) -> CollectionWorkbook:
    path = Path(path).resolve()
    if not path.is_file():
        raise EquipmentCollectionError(f"装备收集配置表不存在：{path}")
    sheets, digest = _read_xlsx(path)
    required_sheets = {"界面设置", "收集明细", "分类奖励"}
    missing = sorted(required_sheets - set(sheets))
    if missing:
        raise EquipmentCollectionError("装备收集配置表缺少工作表：" + "、".join(missing))

    settings: dict[str, object] = {}
    for row in _rows(sheets["界面设置"], "界面设置", 2):
        key = _text(row.get("设置项"))
        if key:
            settings[key] = row.get("当前值", "")
    title = _safe_name(settings.get("系统标题", "装备收集图鉴"), "系统标题", maximum=20)
    page_size = _integer(
        settings.get("每页条目数", GRAPHIC_PAGE_SIZE),
        "每页条目数",
        minimum=GRAPHIC_PAGE_SIZE,
        maximum=GRAPHIC_PAGE_SIZE,
    )
    player_command = _safe_name(settings.get("玩家命令", "装备收集"), "玩家命令", maximum=12).lstrip("@")
    usercmd_number = _integer(settings.get("UserCmd编号", 92), "UserCmd编号", minimum=1, maximum=99)
    flag_start = _integer(settings.get("状态编号起点", ITEM_FLAG_START), "状态编号起点")
    max_id = _integer(settings.get("最大收集ID", 200), "最大收集ID", minimum=1, maximum=MAX_COLLECTION_ID)
    if flag_start != ITEM_FLAG_START:
        raise EquipmentCollectionError("装备收集状态编号起点固定为400，不允许修改")

    categories: list[CollectionCategory] = []
    category_contract: dict[str, tuple[str, int]] = {}
    if "大陆分页" in sheets:
        category_rows = _rows(sheets["大陆分页"], "大陆分页")
        seen_category_names: set[str] = set()
        seen_category_orders: set[int] = set()
        for row_number, row in enumerate(category_rows, start=2):
            if not _enabled(row.get("状态")):
                continue
            category_id = _safe_name(row.get("分类ID"), f"大陆分页第{row_number}行分类ID", maximum=24)
            category_name = _safe_name(row.get("大陆名称"), f"大陆分页第{row_number}行大陆名称", maximum=24)
            category_order = _integer(row.get("分类顺序"), f"大陆分页第{row_number}行分类顺序", minimum=1)
            if category_id in category_contract:
                raise EquipmentCollectionError(f"大陆分页分类ID重复：{category_id}")
            if category_name.casefold() in seen_category_names:
                raise EquipmentCollectionError(f"大陆分页名称重复：{category_name}")
            if category_order in seen_category_orders:
                raise EquipmentCollectionError(f"大陆分页顺序重复：{category_order}")
            category_contract[category_id] = (category_name, category_order)
            seen_category_names.add(category_name.casefold())
            seen_category_orders.add(category_order)
            categories.append(CollectionCategory(
                category_id=category_id,
                category_name=category_name,
                category_order=category_order,
                note=_text(row.get("备注")),
            ))
        if not categories:
            raise EquipmentCollectionError("大陆分页没有启用任何大陆")
        if len(categories) > MAX_CATEGORY_COUNT:
            raise EquipmentCollectionError(f"大陆分页最多支持{MAX_CATEGORY_COUNT}个大陆")
        categories.sort(key=lambda category: (category.category_order, category.category_id))

    detail_rows = _rows(sheets["收集明细"], "收集明细")
    items: list[CollectionItem] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    detail_category_contract: dict[str, tuple[str, int]] = {}
    for row_number, row in enumerate(detail_rows, start=2):
        if not _enabled(row.get("状态")):
            continue
        collection_id = _integer(row.get("收集ID"), f"收集明细第{row_number}行收集ID", minimum=1, maximum=max_id)
        if collection_id in seen_ids:
            raise EquipmentCollectionError(f"收集ID重复：{collection_id}")
        seen_ids.add(collection_id)
        category_id = _safe_name(row.get("分类ID"), f"收集明细第{row_number}行分类ID", maximum=24)
        category_name = _safe_name(row.get("分类名称"), f"收集明细第{row_number}行分类名称", maximum=24)
        category_order = _integer(row.get("分类顺序"), f"收集明细第{row_number}行分类顺序", minimum=1)
        item_order = _integer(row.get("条目顺序"), f"收集明细第{row_number}行条目顺序", minimum=1)
        item_name = _safe_name(row.get("装备名称"), f"收集明细第{row_number}行装备名称")
        if item_name.casefold() in seen_names:
            raise EquipmentCollectionError(f"启用的装备名称重复：{item_name}")
        seen_names.add(item_name.casefold())
        previous = detail_category_contract.get(category_id)
        if previous and previous != (category_name, category_order):
            raise EquipmentCollectionError(f"分类{category_id}的名称或顺序不一致")
        detail_category_contract[category_id] = (category_name, category_order)
        if category_contract:
            expected = category_contract.get(category_id)
            if expected is None:
                raise EquipmentCollectionError(f"收集明细分类{category_id}未在大陆分页启用")
            if expected != (category_name, category_order):
                raise EquipmentCollectionError(f"收集明细分类{category_id}与大陆分页中的名称或顺序不一致")
        consume_text = _text(row.get("激活是否消耗")).casefold()
        if consume_text not in {"是", "否", "1", "0", "true", "false", "yes", "no"}:
            raise EquipmentCollectionError(f"收集明细第{row_number}行激活是否消耗只能填写是或否")
        consume = consume_text in {"是", "1", "true", "yes"}
        items.append(CollectionItem(
            collection_id=collection_id,
            category_id=category_id,
            category_name=category_name,
            category_order=category_order,
            item_order=item_order,
            item_name=item_name,
            required_count=_integer(row.get("需要数量", 1), f"收集明细第{row_number}行需要数量", minimum=1),
            consume=consume,
            reward=_reward(row, row_number, "收集明细"),
            note=_text(row.get("备注")),
        ))
    items.sort(key=lambda item: (item.category_order, item.item_order, item.collection_id))
    if not categories:
        category_contract = dict(detail_category_contract)
        categories = [
            CollectionCategory(category_id, category_name, category_order)
            for category_id, (category_name, category_order) in category_contract.items()
        ]
        categories.sort(key=lambda category: (category.category_order, category.category_id))

    group_rows = _rows(sheets["分类奖励"], "分类奖励")
    groups: list[CollectionGroupReward] = []
    seen_groups: set[str] = set()
    active_category_ids = {item.category_id for item in items}
    for row_number, row in enumerate(group_rows, start=2):
        if not _enabled(row.get("状态")):
            continue
        category_id = _safe_name(row.get("分类ID"), f"分类奖励第{row_number}行分类ID", maximum=24)
        if category_id in seen_groups:
            raise EquipmentCollectionError(f"分类奖励重复：{category_id}")
        seen_groups.add(category_id)
        if category_id not in active_category_ids:
            raise EquipmentCollectionError(f"分类奖励{category_id}没有对应的启用收集条目")
        category_name, category_order = category_contract[category_id]
        written_name = _safe_name(row.get("分类名称"), f"分类奖励第{row_number}行分类名称", maximum=24)
        written_order = _integer(row.get("分类顺序"), f"分类奖励第{row_number}行分类顺序", minimum=1)
        if (written_name, written_order) != (category_name, category_order):
            raise EquipmentCollectionError(f"分类奖励{category_id}与收集明细中的名称或顺序不一致")
        groups.append(CollectionGroupReward(
            category_id=category_id,
            category_name=category_name,
            category_order=category_order,
            reward=_reward(row, row_number, "分类奖励"),
            message=_text(row.get("完成提示")) or f"[{category_name}] 已全部收集。",
            note=_text(row.get("备注")),
        ))
    groups.sort(key=lambda group: (group.category_order, group.category_id))
    return CollectionWorkbook(
        str(path), digest, title, page_size, player_command, usercmd_number,
        tuple(items), tuple(groups), tuple(categories),
    )


def _database(server: Path) -> Path:
    for candidate in (server / "Mud2" / "DB" / "ApexM2.DB", server / "Mud2" / "DB" / "StdItems.DB"):
        if candidate.is_file():
            return candidate
    raise EquipmentCollectionError("目标服缺少 Mud2/DB/ApexM2.DB（或兼容StdItems.DB）")


def _resolve_items(server: Path, workbook: CollectionWorkbook) -> tuple[ResolvedCollectionItem, ...]:
    names = [item.item_name for item in workbook.items]
    if not names:
        raise EquipmentCollectionError("收集明细没有启用任何条目；请至少把一行“状态”改为“是”")
    marks = ",".join("?" for _ in names)
    db = _database(server)
    try:
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                f"SELECT Idx, Name, StdMode, Shape, Looks FROM StdItems WHERE Name IN ({marks}) ORDER BY Idx",
                names,
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise EquipmentCollectionError(f"无法只读检查目标服StdItems：{exc}") from exc
    by_name: dict[str, list[tuple[int, str, int, int, int]]] = {}
    for row in rows:
        by_name.setdefault(str(row[1]), []).append(tuple(row))
    errors: list[str] = []
    resolved: list[ResolvedCollectionItem] = []
    for item in workbook.items:
        matches = by_name.get(item.item_name, [])
        if not matches:
            errors.append(f"目标服装备不存在：{item.item_name}")
            continue
        if len(matches) > 1:
            errors.append(f"目标服装备名称不唯一：{item.item_name}")
            continue
        idx, _name, stdmode, shape, looks = matches[0]
        resolved.append(ResolvedCollectionItem(item, int(idx), int(stdmode or 0), int(shape or 0), int(looks or 0)))
    if errors:
        raise EquipmentCollectionError("\n".join(errors))
    return tuple(resolved)


def _reward_summary(reward: CollectionReward) -> str:
    parts = [f"{name}+{value}" for name, value in reward.nonzero.items()]
    return "、".join(parts) if parts else "仅登记图鉴，无属性奖励"


def _tooltip_escape(value: str) -> str:
    """Keep workbook text from terminating the hover-text markup."""
    return value.replace("|", "｜").replace("^", "＾").replace("#", "＃")


def _tooltip_reward_value(field_name: str, value: int) -> str:
    if field_name.endswith("%"):
        return f"{field_name[:-1]}{value}%"
    if field_name == "处决时间秒":
        return f"处决时间{value}秒"
    return f"{field_name}{value}"


def _reward_hover_text(category_name: str, page_item_count: int) -> str:
    parts = [f"^250#{_tooltip_escape(category_name)}点亮属性"]
    colors = (251, 254, 250, 146)
    visible_count = page_item_count or 1
    for index in range(visible_count):
        parts.append(f"^{colors[index % len(colors)]}#<$STR(S$XY_COL_HOVER{index + 1:02d})>")
    parts.append("^253#<$STR(S$XY_COL_GROUP_HOVER)>")
    return "".join(parts)


def _item_hover_line(item: CollectionItem, status: str) -> str:
    reward_values = "、".join(
        _tooltip_reward_value(field_name, value)
        for field_name, value in item.reward.nonzero.items()
    )
    if reward_values:
        return f"{_tooltip_escape(item.item_name)}[{status}]增加{reward_values}"
    return f"{_tooltip_escape(item.item_name)}[{status}]点亮后无属性奖励"


def _group_hover_line(group: CollectionGroupReward | None, status: str) -> str:
    if group is None:
        return "全部点亮[未配置]无额外属性奖励"
    reward_values = "、".join(
        _tooltip_reward_value(field_name, value)
        for field_name, value in group.reward.nonzero.items()
    )
    if reward_values:
        return f"全部点亮[{status}]增加{reward_values}"
    return f"全部点亮[{status}]无额外属性奖励"


def _base_reward_lines(reward: CollectionReward) -> list[str]:
    lines: list[str] = []
    for field_name in BASE_FIELDS:
        value = reward.values.get(field_name, 0)
        if value:
            lines.append(f"ChangeHumAbilityEX {ABILITY_IDS[field_name]} + {value}")
    return lines


def _state_variable(kind: str, identity: int | str) -> str:
    """Return a stable HUMAN variable for collections beyond flag [999].

    The target engine has already rejected four-digit ``SET [n]`` operands.
    Small, previously accepted workbooks therefore retain their historic
    bracket flags, while a large catalogue uses persisted HUMAN variables.
    """

    normalized_kind = kind.strip().casefold()
    if normalized_kind == "item":
        try:
            number = int(identity)
        except (TypeError, ValueError) as exc:
            raise EquipmentCollectionError(f"收集状态ID无效：{identity}") from exc
        if number < 1:
            raise EquipmentCollectionError(f"收集状态ID无效：{identity}")
        return f"XY_COL_ITEM_{number:04d}"
    if normalized_kind == "group":
        token = re.sub(r"[^A-Za-z0-9_]", "_", str(identity).upper()).strip("_")
        if not token:
            raise EquipmentCollectionError(f"分类状态ID无效：{identity}")
        return f"XY_COL_GROUP_{token}"
    raise EquipmentCollectionError(f"未知收集状态类型：{kind}")


def _state_check(state: int | str, value: int) -> str:
    if isinstance(state, int):
        return f"CHECK [{state}] {value}"
    return f"CHECKVAR HUMAN {state} = {value}"


def _state_set_lines(state: int | str) -> list[str]:
    if isinstance(state, int):
        return [f"SET [{state}] 1"]
    return [
        f"CALCVAR HUMAN {state} = 1",
        f"SAVEVAR HUMAN {state} {COLLECTION_VAR_FILE}",
    ]


def _compile_persistent_state_login(
    item_variables: list[str] | tuple[str, ...],
    group_variables: list[str] | tuple[str, ...],
) -> str:
    variables = list(dict.fromkeys([*item_variables, *group_variables]))
    lines: list[str] = [
        "; 大型装备图鉴持久状态；由同一XLSX自动生成。",
        "#IF",
        "#ACT",
    ]
    for variable in variables:
        if not re.fullmatch(r"XY_COL_(?:ITEM|GROUP)_[A-Z0-9_]+", variable):
            raise EquipmentCollectionError(f"装备图鉴持久变量名无效：{variable}")
        lines.extend((
            f"VAR Integer HUMAN {variable}",
            f"LOADVAR HUMAN {variable} {COLLECTION_VAR_FILE}",
        ))
    return "\n".join(lines)


def _uses_persistent_states(
    workbook: CollectionWorkbook,
    group_flags: dict[str, int],
) -> bool:
    states = [item.flag for item in workbook.items] + list(group_flags.values())
    return any(state > 999 for state in states)


def _item_state(
    workbook: CollectionWorkbook,
    group_flags: dict[str, int],
    item: CollectionItem,
) -> int | str:
    if _uses_persistent_states(workbook, group_flags):
        return _state_variable("item", item.collection_id)
    return item.flag


def _group_state(
    workbook: CollectionWorkbook,
    group_flags: dict[str, int],
    category_id: str,
) -> int | str:
    if _uses_persistent_states(workbook, group_flags):
        return _state_variable("group", category_id)
    return group_flags[category_id]


def _group_flag_map(workbook: CollectionWorkbook) -> dict[str, int]:
    if len(workbook.groups) > MAX_CATEGORY_COUNT:
        raise EquipmentCollectionError(f"分类完成奖励不能超过{MAX_CATEGORY_COUNT}项")
    highest_item_flag = max((item.flag for item in workbook.items), default=ITEM_FLAG_START - 1)
    # Keep the accepted small-workbook mapping ([600]...) stable.  Larger
    # collections move group completion flags to the next hundred boundary so
    # item and group state can never overlap (622 -> items end at 1021, groups
    # begin at 1100).
    next_hundred = ((highest_item_flag + 100) // 100) * 100
    start = max(GROUP_FLAG_START, next_hundred)
    return {group.category_id: start + index for index, group in enumerate(workbook.groups)}


def _graphic_assets(platform_root: Path) -> tuple[Path, Path]:
    root = platform_root / "labs" / "equipment_collection" / "graphical_candidate" / "build"
    wzl = root / GRAPHIC_WZL
    wzx = root / GRAPHIC_WZX
    if not wzl.is_file() or not wzx.is_file():
        raise EquipmentCollectionError(
            f"图形图鉴资源不完整：必须同时存在 {wzl} 和 {wzx}"
        )
    actual = (
        hashlib.sha256(wzl.read_bytes()).hexdigest(),
        hashlib.sha256(wzx.read_bytes()).hexdigest(),
    )
    expected = (GRAPHIC_WZL_SHA256, GRAPHIC_WZX_SHA256)
    if actual != expected:
        raise EquipmentCollectionError("图形图鉴WZL/WZX哈希不符合已验证候选资源，已阻止安装")
    return wzl, wzx


def _resource_stem(value: str) -> str:
    name = Path(value.strip().replace("\\", "/")).name
    return Path(name).stem.casefold()


def _register_graphic_resource(document: TextDocument) -> tuple[str, int]:
    entries = [line.strip() for line in document.text.splitlines() if line.strip()]
    wanted = GRAPHIC_RESOURCE_ENTRY.casefold()
    exact = [index for index, line in enumerate(entries) if line.casefold() == wanted]
    if len(exact) > 1:
        raise EquipmentCollectionError(
            f"EffectImageList重复登记图鉴资源：{GRAPHIC_RESOURCE_ENTRY}"
        )
    same_stem = [
        line for line in entries
        if _resource_stem(line) == _resource_stem(GRAPHIC_RESOURCE_ENTRY)
        and line.casefold() != wanted
    ]
    if same_stem:
        raise EquipmentCollectionError(
            "EffectImageList存在同名但不同写法的图鉴资源，已阻止覆盖：" + "、".join(same_stem)
        )
    if exact:
        return document.text, exact[0]
    merged = add_unique_line(
        document.text,
        GRAPHIC_RESOURCE_ENTRY,
        [0],
        document.newline,
    ).text
    return merged, len(entries)


def _existing_item_mapping(text: str) -> dict[int, str]:
    mapping: dict[int, str] = {}
    pattern = re.compile(
        r"^; XY-COLLECTION-ITEM ID=(\d+) (?:FLAG=(\d+)|HUMAN=(XY_COL_ITEM_\d+)) NAME=(.+)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        collection_id = int(match.group(1))
        if match.group(2):
            flag = int(match.group(2))
            if flag != ITEM_FLAG_START + collection_id - 1:
                raise EquipmentCollectionError(f"现有装备收集映射异常：ID {collection_id} 对应状态[{flag}]")
        elif match.group(3) != _state_variable("item", collection_id):
            raise EquipmentCollectionError(
                f"现有装备收集映射异常：ID {collection_id} 对应变量{match.group(3)}"
            )
        if collection_id in mapping:
            raise EquipmentCollectionError(f"现有装备收集映射重复：ID {collection_id}")
        mapping[collection_id] = match.group(4).strip()
    return mapping


def _strip_own_regions(text: str) -> str:
    patterns = (
        rf"^; XYDP-BEGIN {re.escape(PACKAGE_ID)} SHA256=[0-9a-f]{{64}}\r?$.*?^; XYDP-END {re.escape(PACKAGE_ID)}\r?\n?",
        rf"^; XYDP-BEGIN {re.escape(PACKAGE_ID + '.test-reset')} SHA256=[0-9a-f]{{64}}\r?$.*?^; XYDP-END {re.escape(PACKAGE_ID + '.test-reset')}\r?\n?",
        rf"^; XYDP-ANCHOR-HOOK-BEGIN {re.escape(PACKAGE_ID)} .+?\r?$.*?^; XYDP-ANCHOR-HOOK-END {re.escape(PACKAGE_ID)} .+?\r?\n?",
    )
    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.MULTILINE | re.DOTALL)
    return result


def _scan_flag_conflicts(envir: Path, qfunction_path: Path, wanted: set[int]) -> list[str]:
    conflicts: list[str] = []
    for path in sorted(envir.rglob("*.txt")):
        try:
            text = read_text_document(path).text
        except (OSError, UnicodeError, ValueError):
            continue
        # The collection core lives in QFunction, while the optional display
        # mirror lives in the attribute-overview script.  Both are our own
        # managed regions and must be ignored on repeated preflight; every
        # unowned CHECK/SET occurrence remains a real conflict.
        text = _strip_own_regions(text)
        used = {int(value) for value in re.findall(r"(?:CHECK|SET)\s+\[(\d{1,5})\]", text, flags=re.IGNORECASE)}
        overlap = sorted(used & wanted)
        if overlap:
            conflicts.append(f"{path.relative_to(envir).as_posix()} 占用状态：{','.join(map(str, overlap))}")
    return conflicts


def _compile_core(
    workbook: CollectionWorkbook,
    resolved: tuple[ResolvedCollectionItem, ...],
    group_flags: dict[str, int],
    graphic_resource_id: int,
    refresh_labels: tuple[str, ...] = (),
) -> str:
    items_by_category: dict[str, list[ResolvedCollectionItem]] = {
        category.category_id: [] for category in workbook.categories
    }
    category_contract: dict[str, tuple[str, int]] = {
        category.category_id: (category.category_name, category.category_order)
        for category in workbook.categories
    }
    for resolved_item in resolved:
        item = resolved_item.item
        items_by_category.setdefault(item.category_id, []).append(resolved_item)
        category_contract[item.category_id] = (item.category_name, item.category_order)
    if not category_contract:
        raise EquipmentCollectionError("装备收集没有可显示的大陆分类")
    category_ids = sorted(
        items_by_category,
        key=lambda category_id: (category_contract[category_id][1], category_id),
    )
    category_index = {category_id: index for index, category_id in enumerate(category_ids)}
    group_by_id = {group.category_id: group for group in workbook.groups}
    item_states = {
        item.item.collection_id: _item_state(workbook, group_flags, item.item)
        for item in resolved
    }
    group_states = {
        category_id: _group_state(workbook, group_flags, category_id)
        for category_id in group_flags
    }

    def page_label(category_id: str, page_number: int) -> str:
        return f"@XY_COLLECTION_CAT_{category_index[category_id] + 1:03d}_PAGE_{page_number:02d}"

    def batch_label(category_id: str, page_number: int) -> str:
        return f"@XY_COLLECTION_BATCH_{category_index[category_id] + 1:03d}_PAGE_{page_number:02d}"

    def text_link(text: str, x: int, y: int, color: int, label: str | None = None) -> str:
        suffix = f"/{label}" if label else ""
        return f"<&Text:{text}:{x}:{y}{{FCOLOR={color}}}{suffix}>"

    slot_x = (225, 300, 375, 450, 525, 601, 676)
    slot_y = (118, 212, 305)
    first_page = page_label(category_ids[0], 1)
    lines = [
        "; 表格驱动图形装备收集；装备形态只认目标服StdItems唯一Idx。",
        f"; 大对话框资源：EffectImageList[{graphic_resource_id}] {GRAPHIC_RESOURCE_ENTRY}",
        "; 已启用后禁止把同一收集ID改给另一件装备。",
        f"; 候选版本：{PACKAGE_VERSION}",
    ]
    for resolved_item in resolved:
        item = resolved_item.item
        state = item_states[item.collection_id]
        state_text = f"FLAG={state}" if isinstance(state, int) else f"HUMAN={state}"
        lines.append(f"; XY-COLLECTION-ITEM ID={item.collection_id} {state_text} NAME={item.item_name}")
    for category_id, state in group_states.items():
        state_text = f"FLAG={state}" if isinstance(state, int) else f"HUMAN={state}"
        lines.append(f"; XY-COLLECTION-GROUP ID={category_id} {state_text}")
    first_entry = first_page
    lines.extend([
        "",
        f"[@UserCmd{workbook.usercmd_number}]", "#IF", "#ACT", "GOTO @XY_COLLECTION_COMMAND", "BREAK", "",
        "[@XY_COLLECTION_COMMAND]", "#IF", "#ACT", f"GOTO {first_entry}", "BREAK", "",
    ])
    lines.extend([
        "[@XY_COLLECTION_MAIN]", "#IF", "#ACT", f"GOTO {first_entry}", "BREAK", "",
    ])

    page_for_item: dict[int, str] = {}
    for current_category_id in category_ids:
        category_items = items_by_category[current_category_id]
        category_name = category_contract[current_category_id][0]
        category_pages = [
            category_items[index:index + GRAPHIC_PAGE_SIZE]
            for index in range(0, len(category_items), GRAPHIC_PAGE_SIZE)
        ] or [[]]
        tab_page = category_index[current_category_id] // GRAPHIC_CATEGORY_PAGE_SIZE
        tab_start = tab_page * GRAPHIC_CATEGORY_PAGE_SIZE
        visible_categories = category_ids[tab_start:tab_start + GRAPHIC_CATEGORY_PAGE_SIZE]
        group = group_by_id.get(current_category_id)

        for page_number, page_items in enumerate(category_pages, start=1):
            current_page_label = page_label(current_category_id, page_number)
            for resolved_item in page_items:
                page_for_item[resolved_item.item.collection_id] = current_page_label
            lines.extend([
                f"[{current_page_label}]", "#IF", "#ACT",
                "MOV N$XY_COL_DONE 0",
            ])
            for slot_number in range(1, GRAPHIC_PAGE_SIZE + 1):
                lines.append(f"MOV S$XY_COL_SLOT{slot_number:02d}")
                lines.append(f"MOV S$XY_COL_HOVER{slot_number:02d}")
            lines.append("MOV S$XY_COL_GROUP_HOVER 全部点亮[未配置]无额外属性奖励")
            for member in category_items:
                lines.extend([
                    "#IF", _state_check(item_states[member.item.collection_id], 1), "#ACT",
                    "INC N$XY_COL_DONE 1",
                ])
            for slot_number, resolved_item in enumerate(page_items, start=1):
                item = resolved_item.item
                row, column = divmod(slot_number - 1, 7)
                x, y = slot_x[column], slot_y[row]
                lines.extend([
                    f"MOV S$XY_COL_HOVER{slot_number:02d} {_item_hover_line(item, '未点亮')}",
                    "#IF", _state_check(item_states[item.collection_id], 1), "#ACT",
                    f"MOV S$XY_COL_SLOT{slot_number:02d} <&ItemShow:{resolved_item.idx}:0:{x}:{y}:1:0:0>",
                    f"MOV S$XY_COL_HOVER{slot_number:02d} {_item_hover_line(item, '已点亮')}",
                    "#ELSEACT",
                    f"MOV S$XY_COL_SLOT{slot_number:02d} <&ItemShow:{resolved_item.idx}:0:{x}:{y}:1:0:1/@XY_COLLECTION_APPLY_{item.collection_id:03d}>",
                ])
            if not page_items:
                lines.append("MOV S$XY_COL_HOVER01 本大陆暂无可点亮装备")
            if group is not None:
                group_state = group_states[current_category_id]
                lines.extend([
                    f"MOV S$XY_COL_GROUP_HOVER {_group_hover_line(group, '未激活')}",
                    "#IF", _state_check(group_state, 1), "#ACT",
                    f"MOV S$XY_COL_GROUP_HOVER {_group_hover_line(group, '已激活')}",
                ])
            reward_hover = _reward_hover_text(category_name, len(page_items))
            lines.extend([
                "#IF", "#ACT",
                f"OPENMERCHANTBIGDLG {graphic_resource_id} 0 0 4 0 0 1 746 6 1",
                "#SAY",
                text_link(
                    f"第{page_number}页 共{len(category_pages)}页",
                    PAGE_INFO_X, PAGE_INFO_Y, 146,
                ),
                text_link(
                    f"已点亮<$STR(N$XY_COL_DONE)>/{len(category_items)}",
                    DONE_COUNT_X, DONE_COUNT_Y, 250,
                ),
                text_link(workbook.title, 226, 27, 253),
                text_link(category_name, 226, 49, 251),
            ])
            for tab_offset, tab_category_id in enumerate(visible_categories):
                tab_name = category_contract[tab_category_id][0]
                tab_color = 253 if tab_category_id == current_category_id else 146
                lines.append(text_link(
                    tab_name, 53, 98 + tab_offset * 56, tab_color,
                    page_label(tab_category_id, 1),
                ))
            if tab_page > 0:
                previous_category = category_ids[(tab_page - 1) * GRAPHIC_CATEGORY_PAGE_SIZE]
                lines.append(text_link("分类上页", 39, 409, 218, page_label(previous_category, 1)))
            if tab_start + GRAPHIC_CATEGORY_PAGE_SIZE < len(category_ids):
                next_category = category_ids[(tab_page + 1) * GRAPHIC_CATEGORY_PAGE_SIZE]
                lines.append(text_link("分类下页", 109, 409, 218, page_label(next_category, 1)))
            for slot_number in range(1, GRAPHIC_PAGE_SIZE + 1):
                lines.append(f"<$STR(S$XY_COL_SLOT{slot_number:02d})>\\")
            lines.append(
                f"<&Text:{REWARD_HOVER_LABEL}|{reward_hover}:"
                f"{REWARD_HOVER_X}:{REWARD_HOVER_Y}{{FCOLOR=250}}>\\"
            )
            if page_items:
                lines.append(text_link(
                    "一键收集本页", BATCH_COLLECT_X, BATCH_COLLECT_Y, 251,
                    batch_label(current_category_id, page_number),
                ))
            if page_number > 1:
                lines.append(text_link("上一页", 449, 462, 251, page_label(current_category_id, page_number - 1)))
            if page_number < len(category_pages):
                lines.append(text_link("下一页", 527, 462, 251, page_label(current_category_id, page_number + 1)))
            lines.append(text_link("关闭", 663, 462, 161, "@exit"))
            lines.append("")

            if page_items:
                lines.extend([
                    f"[{batch_label(current_category_id, page_number)}]",
                    "#IF", "#ACT", "MOV N$XY_COL_BATCH_COUNT 0",
                ])
                for resolved_item in page_items:
                    item = resolved_item.item
                    item_state = item_states[item.collection_id]
                    lines.extend([
                        "#IF", _state_check(item_state, 0),
                        f"CHECKITEM {item.item_name} {item.required_count}",
                        "#ACT",
                    ])
                    if item.consume:
                        lines.append(f"TAKE {item.item_name} {item.required_count}")
                    lines.extend([
                        *_state_set_lines(item_state),
                        *_base_reward_lines(item.reward),
                        "INC N$XY_COL_BATCH_COUNT 1",
                    ])
                if current_category_id in group_by_id:
                    current_group = group_by_id[current_category_id]
                    group_state = group_states[current_category_id]
                    group_checks = [
                        _state_check(item_states[member.item.collection_id], 1)
                        for member in items_by_category[current_category_id]
                    ]
                    lines.extend([
                        "#IF", _state_check(group_state, 0), *group_checks,
                        "#ACT", *_state_set_lines(group_state),
                        *_base_reward_lines(current_group.reward),
                        f"SENDMSG 6 [装备收集] {current_group.message}",
                    ])
                lines.extend([
                    "#IF", "EQUAL N$XY_COL_BATCH_COUNT 0",
                    "#ACT", "SENDMSG 6 [装备收集] 本页没有可以点亮的装备。",
                    f"GOTO {current_page_label}", "BREAK", "",
                    "#IF", "#ACT",
                    "SENDMSG 6 [装备收集] 本页一键收集完成，共点亮<$STR(N$XY_COL_BATCH_COUNT)>件装备。",
                ])
                lines.extend(f"DELAYGOTO 1 @{label}" for label in refresh_labels)
                lines.extend([f"GOTO {current_page_label}", "BREAK", ""])

    for resolved_item in resolved:
        item = resolved_item.item
        item_state = item_states[item.collection_id]
        return_label = page_for_item[item.collection_id]
        reward_summary = _reward_summary(item.reward)
        lines.extend([
            f"[@XY_COLLECTION_APPLY_{item.collection_id:03d}]",
            "#IF", _state_check(item_state, 1), "#ACT", "MESSAGEBOX 这件装备已经点亮。",
            f"GOTO {return_label}", "BREAK", "",
            "#IF", f"NOT CHECKITEM {item.item_name} {item.required_count}", "#ACT",
            f"MESSAGEBOX 背包中缺少{item.item_name}×{item.required_count}。",
            f"GOTO {return_label}", "BREAK", "",
            "#IF", "#ACT",
        ])
        if item.consume:
            lines.append(f"TAKE {item.item_name} {item.required_count}")
        lines.extend([*_state_set_lines(item_state), *_base_reward_lines(item.reward)])
        if item.category_id in group_by_id:
            group = group_by_id[item.category_id]
            group_state = group_states[item.category_id]
            checks = [
                _state_check(item_states[member.item.collection_id], 1)
                for member in items_by_category[item.category_id]
            ]
            lines.extend([
                "#IF", _state_check(group_state, 0), *checks, "#ACT",
                *_state_set_lines(group_state), *_base_reward_lines(group.reward),
                f"SENDMSG 6 [装备收集] {group.message}",
            ])
        lines.append(f"SENDMSG 6 [装备收集] {item.item_name}点亮成功，获得：{reward_summary}。")
        lines.extend(f"DELAYGOTO 1 @{label}" for label in refresh_labels)
        lines.extend([
            f"GOTO {return_label}", "BREAK",
            "",
        ])
    lines.extend(["[@XY_COLLECTION_REFRESH]", "#IF", "#ACT"])
    lines.extend(f"DELAYGOTO 1 @{label}" for label in refresh_labels)
    lines.extend([f"GOTO {first_page}", "BREAK", ""])
    return "\n".join(lines).rstrip()


def _special_sources(
    workbook: CollectionWorkbook,
    group_flags: dict[str, int],
) -> list[tuple[int | str, str, CollectionReward]]:
    sources = [
        (_item_state(workbook, group_flags, item), item.item_name, item.reward)
        for item in workbook.items
    ]
    sources.extend(
        (
            _group_state(workbook, group_flags, group.category_id),
            group.category_name + "分类完成",
            group.reward,
        )
        for group in workbook.groups
    )
    return sources


def _compile_anchor_hooks(
    workbook: CollectionWorkbook,
    group_flags: dict[str, int],
) -> dict[tuple[str, str], str]:
    hooks: dict[tuple[str, str], list[str]] = {}
    for state, source_name, reward in _special_sources(workbook, group_flags):
        for field_name, value in reward.nonzero.items():
            if field_name not in SPECIAL_OUTLETS:
                continue
            for target, anchor, action in SPECIAL_OUTLETS[field_name]:
                hooks.setdefault((target, anchor), []).extend([
                    f"; 装备收集 {source_name}: {field_name}+{value}",
                    "#IF", _state_check(state, 1), "#ACT", action.format(value=value),
                ])
    return {key: "\n".join(lines) for key, lines in hooks.items()}


def _compile_damage_coefficient_display_hook(
    workbook: CollectionWorkbook,
    group_flags: dict[str, int],
) -> str:
    """Mirror every collection damage-coefficient reward in the optional UI panel.

    The combat outlet uses ``N$XY_RT_DamageCoeff`` inside ``@AttackDamage``.
    The accepted left-top panel intentionally computes its own display mirror,
    so it must read the same collection flags or the effect and tooltip diverge.
    """
    lines: list[str] = []
    for state, source_name, reward in _special_sources(workbook, group_flags):
        value = reward.values.get("伤害系数%", 0)
        if not value:
            continue
        lines.extend((
            f"; 装备收集 {source_name}: 伤害系数%+{value}",
            "#IF",
            _state_check(state, 1),
            "#ACT",
            f"INC N$XY_UI_A_Value02 {value}",
        ))
    return "\n".join(lines)


def _ensure_damage_coefficient_display_anchor(text: str, newline: str) -> str:
    marker = f"; {ATTR_OVERVIEW_DAMAGE_COEFFICIENT_ANCHOR}"
    marker_count = sum(1 for line in text.splitlines() if line.strip() == marker)
    if marker_count == 1:
        return text
    if marker_count > 1:
        raise EquipmentCollectionError(
            f"属性总览伤害系数显示锚点不唯一：{ATTR_OVERVIEW_DAMAGE_COEFFICIENT_ANCHOR}"
        )

    # Insert immediately before the accepted damage-coefficient clamp.  The
    # four-line sequence is deliberately strict: an unknown/manual UI layout
    # must block instead of receiving a guessed patch.
    clamp_re = re.compile(
        r"^#IF\r?\nSMALL N\$XY_UI_A_Value02 0\r?\n#ACT\r?\nMOV N\$XY_UI_A_Value02 0\r?$",
        re.MULTILINE,
    )
    matches = list(clamp_re.finditer(text))
    if len(matches) != 1:
        raise EquipmentCollectionError(
            "属性总览无法唯一识别伤害系数显示位置，已阻止写入"
        )
    return text[:matches[0].start()] + marker + newline + text[matches[0].start():]


def _usercmd_number_conflict(text: str, command: str, number: int) -> str | None:
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        try:
            existing_number = int(fields[1].strip())
        except ValueError:
            continue
        if existing_number == number and fields[0].strip() != command:
            return fields[0].strip()
    return None


def _change(
    root: Path,
    relative: str,
    after: bytes,
    operation: str,
    *,
    scope: str = "server",
) -> PlannedChange:
    path = root / Path(relative.replace("/", "\\"))
    before = path.read_bytes() if path.exists() else None
    return PlannedChange(relative, before, after, operation, PACKAGE_ID, scope)


class EquipmentCollectionService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        self.default_workbook = documents_root(self.root) / DEFAULT_WORKBOOK
        self.repository = PackageRepository(self.root / "packages")
        self.repository.refresh()
        self.installer = Installer(self.repository, self.root / "backups")

    def inspect_workbook(self, workbook: Path) -> CollectionWorkbook:
        return read_collection_workbook(workbook)

    def preflight(
        self,
        workbook_path: Path,
        server: Path,
        client: Path | None = None,
    ) -> EquipmentCollectionPlan:
        plan = EquipmentCollectionPlan(str(Path(server).absolute()), str(Path(workbook_path).absolute()), "")
        try:
            workbook = read_collection_workbook(workbook_path)
            plan.workbook = workbook.path
            plan.workbook_hash = workbook.sha256
            target = TargetInspector.inspect(Path(server))
            if client is None:
                raise EquipmentCollectionError("图形装备收集必须选择目标客户端目录")
            client_root = Path(client).resolve()
            client_data = client_root / "data"
            if not client_root.is_dir() or not client_data.is_dir():
                raise EquipmentCollectionError(f"目标客户端缺少data目录：{client_root}")
            plan.client = str(client_root)
            source_wzl, source_wzx = _graphic_assets(self.root)
            resolved = _resolve_items(target.root, workbook)
            group_flags = _group_flag_map(workbook)
            plan.group_flags = group_flags

            qfunction_path = target.root / Path(QFUNCTION.replace("/", "\\"))
            qmanage_path = target.root / Path(QMANAGE.replace("/", "\\"))
            usercmd_path = target.root / Path(USERCMD.replace("/", "\\"))
            effect_list_path = target.root / Path(EFFECT_IMAGE_LIST.replace("/", "\\"))
            for path in (qfunction_path, qmanage_path, usercmd_path, effect_list_path):
                if not path.is_file():
                    raise EquipmentCollectionError(f"目标脚本不存在：{path}")
            qfunction_doc = read_text_document(qfunction_path)
            qmanage_doc = read_text_document(qmanage_path)
            usercmd_doc = read_text_document(usercmd_path)
            effect_list_doc = read_text_document(effect_list_path)
            effect_list_text, graphic_resource_id = _register_graphic_resource(effect_list_doc)
            plan.resource_id = graphic_resource_id

            for relative, source in (
                (GRAPHIC_CLIENT_WZL, source_wzl),
                (GRAPHIC_CLIENT_WZX, source_wzx),
            ):
                existing = client_root / Path(relative.replace("/", "\\"))
                if existing.is_file() and existing.read_bytes() != source.read_bytes():
                    raise EquipmentCollectionError(
                        f"客户端存在同名但内容不同的图鉴资源，已阻止覆盖：{existing}"
                    )

            previous_mapping = _existing_item_mapping(qfunction_doc.text)
            for item in workbook.items:
                old_name = previous_mapping.get(item.collection_id)
                if old_name is not None and old_name != item.item_name:
                    raise EquipmentCollectionError(
                        f"收集ID {item.collection_id} 已经绑定“{old_name}”，禁止改给“{item.item_name}”；请使用新的收集ID"
                    )
            wanted_flags = (
                set()
                if _uses_persistent_states(workbook, group_flags)
                else {item.flag for item in workbook.items} | set(group_flags.values())
            )
            conflicts = _scan_flag_conflicts(target.envir, qfunction_path, wanted_flags)
            if conflicts:
                raise EquipmentCollectionError("装备收集状态与其他脚本冲突：\n" + "\n".join(conflicts[:20]))

            command_conflict = _usercmd_number_conflict(usercmd_doc.text, workbook.player_command, workbook.usercmd_number)
            if command_conflict:
                raise EquipmentCollectionError(
                    f"UserCmd编号{workbook.usercmd_number}已被“{command_conflict}”占用"
                )

            available_refresh_labels = tuple(
                label for label in (
                    "XYDP_RecalcPower", "XYDP_RecalcBlast", "XYDP_RecalcDrop",
                    "XYDP_RecalcMonsterAbsorb", "XYDP_RecalcSustain", "XYDP_ShowAttrBuff",
                )
                if len(scan_labels(qfunction_doc.text).labels.get(label.casefold(), [])) == 1
            )
            qf_text = install_managed_block(
                qfunction_doc.text, PACKAGE_ID,
                _compile_core(
                    workbook,
                    resolved,
                    group_flags,
                    graphic_resource_id,
                    available_refresh_labels,
                ),
                qfunction_doc.newline,
            ).text
            qm_text = qmanage_doc.text
            if _uses_persistent_states(workbook, group_flags):
                login_content = _compile_persistent_state_login(
                    [_state_variable("item", item.collection_id) for item in workbook.items],
                    [_state_variable("group", group.category_id) for group in workbook.groups],
                )
                qm_text = install_event_hook(
                    qm_text,
                    PACKAGE_ID,
                    "Login",
                    login_content,
                    qmanage_doc.newline,
                ).text
            hook_contents = _compile_anchor_hooks(workbook, group_flags)
            all_anchors = {
                (target_name, anchor)
                for outlets in SPECIAL_OUTLETS.values()
                for target_name, anchor, _action in outlets
            }
            for target_name, anchor in sorted(all_anchors):
                content = hook_contents.get((target_name, anchor), "")
                if target_name == "qfunction":
                    qf_text = (
                        install_managed_anchor_hook(
                            qf_text, PACKAGE_ID, anchor, content, qfunction_doc.newline,
                            canonical_before_existing_hooks=True,
                        ).text
                        if content else remove_managed_anchor_hook(qf_text, PACKAGE_ID, anchor).text
                    )
                else:
                    qm_text = (
                        install_managed_anchor_hook(
                            qm_text, PACKAGE_ID, anchor, content, qmanage_doc.newline,
                            canonical_before_existing_hooks=True,
                        ).text
                        if content else remove_managed_anchor_hook(qm_text, PACKAGE_ID, anchor).text
                    )

            attr_overview_change: PlannedChange | None = None
            attr_overview_path = target.root / Path(ATTR_OVERVIEW.replace("/", "\\"))
            display_hook = _compile_damage_coefficient_display_hook(workbook, group_flags)
            if attr_overview_path.is_file():
                attr_overview_doc = read_text_document(attr_overview_path)
                attr_overview_text = attr_overview_doc.text
                if display_hook:
                    attr_overview_text = _ensure_damage_coefficient_display_anchor(
                        attr_overview_text, attr_overview_doc.newline
                    )
                    attr_overview_text = install_managed_anchor_hook(
                        attr_overview_text,
                        PACKAGE_ID,
                        ATTR_OVERVIEW_DAMAGE_COEFFICIENT_ANCHOR,
                        display_hook,
                        attr_overview_doc.newline,
                    ).text
                else:
                    attr_overview_text = remove_managed_anchor_hook(
                        attr_overview_text,
                        PACKAGE_ID,
                        ATTR_OVERVIEW_DAMAGE_COEFFICIENT_ANCHOR,
                    ).text
                attr_overview_change = _change(
                    target.root,
                    ATTR_OVERVIEW,
                    encode_text_document(TextDocument(
                        attr_overview_text,
                        attr_overview_doc.encoding,
                        attr_overview_doc.newline,
                        attr_overview_doc.bom,
                    )),
                    "collection-attribute-overview-mirror",
                )
            elif display_hook:
                plan.warnings.append(
                    "目标服未安装玄渊左上属性总览：伤害系数实效仍会生效，但没有左上图标显示镜像。"
                )
            usercmd_text = add_unique_line(
                usercmd_doc.text,
                f"{workbook.player_command}\t{workbook.usercmd_number}",
                [0], usercmd_doc.newline,
            ).text

            qf_labels = scan_labels(qf_text)
            qm_labels = scan_labels(qm_text)
            if qf_labels.duplicates:
                raise EquipmentCollectionError(f"生成后的QFunction存在重复标签：{qf_labels.duplicates}")
            if qm_labels.duplicates:
                raise EquipmentCollectionError(f"生成后的QManage存在重复标签：{qm_labels.duplicates}")
            if "\x00" in qf_text or "\x00" in qm_text:
                raise EquipmentCollectionError("生成脚本包含空字符")

            changes = [
                _change(target.root, QFUNCTION, encode_text_document(TextDocument(qf_text, qfunction_doc.encoding, qfunction_doc.newline, qfunction_doc.bom)), "collection-qfunction"),
                _change(target.root, QMANAGE, encode_text_document(TextDocument(qm_text, qmanage_doc.encoding, qmanage_doc.newline, qmanage_doc.bom)), "collection-qmanage"),
                _change(target.root, USERCMD, encode_text_document(TextDocument(usercmd_text, usercmd_doc.encoding, usercmd_doc.newline, usercmd_doc.bom)), "collection-user-command"),
                _change(
                    target.root,
                    EFFECT_IMAGE_LIST,
                    encode_text_document(TextDocument(
                        effect_list_text,
                        effect_list_doc.encoding,
                        effect_list_doc.newline,
                        effect_list_doc.bom,
                    )),
                    "collection-effect-resource-register",
                ),
                _change(
                    client_root,
                    GRAPHIC_CLIENT_WZL,
                    source_wzl.read_bytes(),
                    "collection-client-wzl",
                    scope="client",
                ),
                _change(
                    client_root,
                    GRAPHIC_CLIENT_WZX,
                    source_wzx.read_bytes(),
                    "collection-client-wzx",
                    scope="client",
                ),
            ]
            if _uses_persistent_states(workbook, group_flags):
                state_path = target.root / Path(COLLECTION_STATE_RELATIVE.replace("/", "\\"))
                if not state_path.is_file():
                    changes.append(_change(
                        target.root,
                        COLLECTION_STATE_RELATIVE,
                        b"\xef\xbb\xbf",
                        "initialize-collection-state",
                    ))
            if attr_overview_change is not None:
                changes.append(attr_overview_change)
            plan.changes = [change for change in changes if change.before != change.after]
            plan.items = [
                {
                    "collection_id": item.item.collection_id,
                    "name": item.item.item_name,
                    "flag": item.item.flag,
                    "state": _item_state(workbook, group_flags, item.item),
                    "idx": item.idx,
                    "stdmode": item.stdmode,
                    "shape": item.shape,
                    "looks": item.looks,
                    "itemshow": f"ItemShow:{item.idx}",
                }
                for item in resolved
            ]
            plan.warnings.extend([
                "装备图标与悬浮属性只读取目标服StdItems唯一Idx；不会复制星辰版Idx、Shape或Looks。",
                "本事务只复制通用图鉴面板XY_EquipmentCollection.wzl/.wzx；不会复制或修改Items/StateItem/DnItems。",
                "攻击、防御、魔御、HP、MP属于领取时一次性写入的人物基础属性；正式开放后不要直接改小这些历史奖励。",
                "伤害系数分类奖励同时写入AttackDamage实效链与已安装的左上属性总览显示链。",
                "M2运行时允许写入；新脚本需要由你重载或重启M2后才会生效。",
            ])
            if is_executable_running(target.mir200 / "M2Server.exe"):
                plan.warnings.append("检测到M2Server.exe正在运行：本次只提示，不阻止预检或确认更新。")
            plan.install_plan = InstallPlan(
                target_root=str(target.root), client_root=str(client_root),
                package_ids=[PACKAGE_ID], package_versions={PACKAGE_ID: PACKAGE_VERSION},
                parameters={
                    "workbook": workbook.path,
                    "workbook_hash": workbook.sha256,
                    "item_count": len(workbook.items),
                    "group_reward_count": len(workbook.groups),
                    "player_command": workbook.player_command,
                    "usercmd_number": workbook.usercmd_number,
                    "appearance_source": "target-StdItems-Idx",
                    "graphic_resource_entry": GRAPHIC_RESOURCE_ENTRY,
                    "graphic_resource_id": graphic_resource_id,
                    "graphic_layout": "7x3-21",
                    "reward_overview": "main-page-text-hover-item-details",
                    "reward_hover_label": REWARD_HOVER_LABEL,
                    "reward_hover_position": f"{REWARD_HOVER_X},{REWARD_HOVER_Y}",
                    "page_info_position": f"{PAGE_INFO_X},{PAGE_INFO_Y}",
                    "done_count_position": f"{DONE_COUNT_X},{DONE_COUNT_Y}",
                },
                changes=plan.changes,
                warnings=list(plan.warnings),
                operation_type=plan.operation,
                candidate_packages=[PACKAGE_ID],
            )
        except (OSError, ValueError, RuntimeError, sqlite3.Error, TextPatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: EquipmentCollectionPlan) -> InstallReceipt:
        if plan.blockers or plan.install_plan is None:
            raise EquipmentCollectionError("装备收集配置被阻止：\n" + "\n".join(plan.blockers))
        workbook = Path(plan.workbook)
        if not workbook.is_file() or hashlib.sha256(workbook.read_bytes()).hexdigest() != plan.workbook_hash:
            raise EquipmentCollectionError("预检后装备收集配置表已变化，请重新预检")
        if not plan.changes:
            raise EquipmentCollectionError("没有需要应用的变更，目标已处于当前装备收集配置")
        return self.installer.install(plan.install_plan)

    def rollback(self, server: Path, transaction_id: str) -> str:
        self.installer.rollback(server, transaction_id)
        return transaction_id
