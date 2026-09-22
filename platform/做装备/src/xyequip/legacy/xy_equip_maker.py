#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
玄渊做装备工具。

目标：
- 输入一个装备 TXT。
- 同名装备存在时直接报错。
- 不做备份。
- 写 StdItems、ItemDescList、QFunction 统一出口。
- 通过 script_properties.json 暴露脚本属性扩展接口。
"""

from __future__ import annotations

import argparse
import configparser
import csv
import datetime as dt
import json
import re
import shutil
import sqlite3
import struct
import traceback
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..paths import EquipmentPaths
from ..resources import clone_wzl_frame_raw


TOOL_DIR = Path(__file__).resolve().parent
_PATHS = EquipmentPaths.default(TOOL_DIR.parents[3])


def configure_paths(paths: EquipmentPaths) -> None:
    """Point the verified legacy algorithm at an explicit target context."""
    global _PATHS, SERVER_ROOT, DB_PATH, ENVIR, ITEM_DESC, ITEM_RULE, GROUP_ITEM
    global QFUNCTION, QMANAGE, ATTRIBUTE_PANEL, FENGHAO_DATA, SCRIPT_PROPS, RESOURCE_MAP, STATIC_ICON_IMPORTER
    global RAW_CLONE_IMPORTER, CLIENT_DATA, BACKUP_ROOT, OUTPUT_DIR
    _PATHS = paths
    SERVER_ROOT = paths.server_root
    DB_PATH = paths.db_path
    ENVIR = paths.envir
    ITEM_DESC = paths.item_desc
    ITEM_RULE = paths.item_rule
    GROUP_ITEM = paths.group_item
    QFUNCTION = paths.qfunction
    QMANAGE = paths.qmanage
    ATTRIBUTE_PANEL = paths.attribute_panel
    FENGHAO_DATA = paths.fenghao_data
    SCRIPT_PROPS = paths.script_properties
    RESOURCE_MAP = paths.resource_map
    STATIC_ICON_IMPORTER = paths.static_icon_importer
    RAW_CLONE_IMPORTER = paths.raw_clone_importer
    CLIENT_DATA = paths.client_data
    BACKUP_ROOT = paths.backup_root
    OUTPUT_DIR = paths.output_root


configure_paths(_PATHS)

TEXT_ENCODING = "gb18030"

WEAPON_SLOTS = {"武器", "时装武器"}
NECKLACE_SLOTS = {"项链", "时装项链"}
LUCK_SLOTS = WEAPON_SLOTS | NECKLACE_SLOTS
BACKPACK_ARTIFACT_SLOT = "背包神器"
TITLE_SCROLL_SLOT = "称号卷"
SPECIAL_SCRIPT_SLOTS = {BACKPACK_ARTIFACT_SLOT, TITLE_SCROLL_SLOT}

# StdItems 的 Ac/Ac2/Mac/Mac2/Source/Reserved 会随 StdMode 改变含义。
# 这些门槛只拦截平台当前确定无法正确表达、会覆盖另一项原生属性的组合；
# 空白或显式 0 仍允许通过，便于母表保留占位列和修改表清理旧值。
SLOT_ATTRIBUTE_RESTRICTIONS = {
    "防御": "武器、项链的 Ac/Ac2 另有含义，不能作为防御",
    "魔御": "武器、项链的 Mac/Mac2 另有含义，不能作为魔御",
    "幸运": "幸运只允许武器、项链",
    "攻击速度": "当前平台只验证了武器攻击速度字段",
    "强度": "Source 强度只适用于武器，其他部位的 Source 另有含义",
}

ACTION_SLOTS = {
    "武器", "衣服", "男衣服", "女衣服", "盔甲",
    "时装武器", "时装衣服", "时装男衣服", "时装女衣服", "时装盔甲",
}

INHERIT_FIELDS = {
    "StdMode",
    "Shape",
    "Weight",
    "Anicount",
    "Looks",
    "DuraMax",
    "Need",
    "NeedLevel",
    "Price",
    "Stock",
    "Color",
    "OverLap",
    "Light",
    "Horse",
    "Job",
    "CustomItem",
}

CLEAR_FIELDS = {
    "Source",
    "Reserved",
    "Ac",
    "Ac2",
    "Mac",
    "Mac2",
    "Dc",
    "Dc2",
    "Mc",
    "Mc2",
    "Sc",
    "Sc2",
    "HP",
    "MP",
    "Element",
    "Expand1",
    "Expand2",
    "InsuranceCurrency",
    "InsuranceGold",
    "Expand3",
    "Expand4",
    "Expand5",
    "Asc",
    "Asc2",
    "Arc",
    "Arc2",
    "Mpc",
    "Mpc2",
}
for _idx in range(1, 27):
    CLEAR_FIELDS.add(f"Element{_idx}")

STD_MODE_BY_SLOT = {
    "材料": 46,
    BACKPACK_ARTIFACT_SLOT: 41,
    TITLE_SCROLL_SLOT: 31,
    "武器": 5,
    "衣服": 10,
    "男衣服": 10,
    "女衣服": 11,
    "盔甲": 10,
    "项链": 19,
    "戒指": 22,
    "手镯": 26,
    "头盔": 15,
    "勋章": 30,
    "斗笠": 16,
    "面巾": 16,
    "腰带": 64,
    "鞋子": 62,
    "靴子": 62,
    "照明物": 30,
    "左手镯": 26,
    "右手镯": 26,
    "左戒指": 22,
    "右戒指": 22,
    "护身符": 25,
    "护符": 25,
    "宝石": 63,
    "军鼓": 65,
    "马牌": 28,
    "盾牌": 12,
    "灵玉": 90,
    "时装衣服": 66,
    "时装男衣服": 66,
    "时装女衣服": 67,
    "时装盔甲": 66,
    "时装武器": 68,
    "时装项链": 75,
    "时装头盔": 78,
    "时装手镯": 79,
    "时装左手镯": 79,
    "时装右手镯": 79,
    "时装戒指": 81,
    "时装左戒指": 81,
    "时装右戒指": 81,
    "时装勋章": 83,
    "时装腰带": 84,
    "时装鞋子": 86,
    "时装靴子": 86,
    "时装宝石": 88,
}

# 首饰盒与神佑袋没有独立 StdMode。沿用官方示例的戒指结构
# （StdMode=22），只通过原生 OverLap/Expand1 字段限定容器位置。
SLOT_DEFAULT_FIELDS: Dict[str, Dict[str, int]] = {
    "材料": {"DuraMax": 99999, "OverLap": 2},
    BACKPACK_ARTIFACT_SLOT: {"Shape": 0, "DuraMax": 0, "OverLap": 0},
    TITLE_SCROLL_SLOT: {"Shape": 0, "DuraMax": 1, "OverLap": 0},
    "首饰盒": {"OverLap": 2, "Expand1": 0},
    "普通首饰盒": {"OverLap": 2, "Expand1": 0},
    "生肖": {"OverLap": 4, "Expand1": 13},
    "生肖盒": {"OverLap": 4, "Expand1": 13},
    "普通生肖": {"OverLap": 4, "Expand1": 13},
    "普通生肖盒": {"OverLap": 4, "Expand1": 13},
    "时装首饰盒": {"OverLap": 8, "Expand1": 0},
    "时装生肖": {"OverLap": 16, "Expand1": 13},
    "时装生肖盒": {"OverLap": 16, "Expand1": 13},
}
for _position in range(1, 7):
    for _prefix in ("首饰盒", "普通首饰盒"):
        SLOT_DEFAULT_FIELDS[f"{_prefix}{_position}"] = {"OverLap": 2, "Expand1": _position}
    SLOT_DEFAULT_FIELDS[f"时装首饰盒{_position}"] = {"OverLap": 8, "Expand1": _position}
for _position in range(1, 13):
    for _prefix in ("生肖", "生肖盒", "普通生肖", "普通生肖盒"):
        SLOT_DEFAULT_FIELDS[f"{_prefix}{_position}"] = {"OverLap": 4, "Expand1": _position}
    for _prefix in ("时装生肖", "时装生肖盒"):
        SLOT_DEFAULT_FIELDS[f"{_prefix}{_position}"] = {"OverLap": 16, "Expand1": _position}
# 首饰盒/生肖扩展位沿用戒指结构；“材料”是独立的 StdMode=46，不能被这里覆盖。
STD_MODE_BY_SLOT.update({
    slot: 22
    for slot in SLOT_DEFAULT_FIELDS
    if slot not in {"材料", BACKPACK_ARTIFACT_SLOT, TITLE_SCROLL_SLOT}
})

# 修改装备时必须反查到原有规范部位，不能被上面的别名覆盖。
CANONICAL_SLOT_BY_STDMODE = {
    5: "武器", 6: "武器",
    10: "男衣服", 11: "女衣服",
    12: "盾牌", 15: "头盔", 16: "斗笠",
    19: "项链", 20: "项链", 21: "项链",
    22: "戒指", 23: "戒指",
    24: "手镯", 25: "护身符", 26: "手镯",
    28: "马牌", 30: "勋章",
    52: "鞋子", 53: "宝石", 54: "腰带",
    62: "鞋子", 63: "宝石", 64: "腰带", 65: "军鼓",
    66: "时装男衣服", 67: "时装女衣服",
    68: "时装武器", 69: "时装武器",
    75: "时装项链", 76: "时装项链", 77: "时装项链",
    78: "时装头盔",
    79: "时装手镯", 80: "时装手镯",
    81: "时装戒指", 82: "时装戒指",
    83: "时装勋章",
    84: "时装腰带", 85: "时装腰带",
    86: "时装靴子", 87: "时装靴子",
    88: "时装宝石", 89: "时装宝石",
    90: "灵玉",
}

BASE_FIELD_MAP = {
    "StdMode": "StdMode",
    "Shape": "Shape",
    "Weight": "Weight",
    "重量": "Weight",
    "Looks": "Looks",
    "持久": "DuraMax",
    "DuraMax": "DuraMax",
    "等级": "NeedLevel",
    "NeedLevel": "NeedLevel",
    "Need": "Need",
    "Color": "Color",
    "价格": "Price",
    "Price": "Price",
    "库存": "Stock",
    "Stock": "Stock",
    "Anicount": "Anicount",
    "Source": "Source",
    "Reserved": "Reserved",
    "OverLap": "OverLap",
    "防御下限": "Ac",
    "防御上限": "Ac2",
    "魔御下限": "Mac",
    "魔御上限": "Mac2",
    "HP": "HP",
    "MP": "MP",
    "强度": "Source",
}

NATIVE_ELEMENT_FIELD_MAP = {
    "暴击几率": "Element",
    "暴击机率": "Element",
    "暴击": "Element",
    "攻击伤害": "Element1",
    "伤害吸收": "Element2",
    "魔法防御": "Element3",
    "忽视防御": "Element4",
    "幻影防御": "Element4",
    "伤害反弹": "Element5",
    "人物爆率": "Element6",
    "人物暴率": "Element6",
    "杀人爆率": "Element6",
    "体力增加": "Element7",
    "魔力增加": "Element8",
    "怒气恢复": "Element9",
    "合击攻击": "Element10",
    "怪物爆率": "Element11",
    "怪物暴率": "Element11",
    "杀怪爆率": "Element11",
    "防爆几率": "Element12",
    "防止掉宝": "Element12",
    "防止麻痹": "Element13",
    "防止护身": "Element14",
    "防止复活": "Element15",
    "防止全毒": "Element16",
    "防止诱惑": "Element17",
    "防止火墙": "Element18",
    "防止冰冻": "Element19",
    "防止蛛网": "Element20",
    "致命几率": "Element21",
    "致命机率": "Element21",
    "致命一击": "Element21",
    "致命一击几率": "Element21",
    "致命伤害": "Element22",
    "致命一击伤害": "Element22",
    "致命防御": "Element23",
    "暴击抗性": "Element24",
    "攻击伤害抗性": "Element25",
    "杀怪经验倍数": "Element26",
    "杀怪经验倍率": "Element26",
}

NATIVE_ELEMENT_SECTIONS = ("原生属性", "引擎属性", "天生元素", "新增属性")

FIXED_TABLE_ATTRS = {
    "攻击加成": {"rule_index": 27, "group_index": 16},
    "魔法加成": {"rule_index": 21, "group_index": 17},
    "道术加成": {"rule_index": 26, "group_index": 18},
}


@dataclass
class EquipmentSpec:
    name: str
    slot: str = ""
    template: str = ""
    remark: str = ""
    fields: Dict[str, int] = field(default_factory=dict)
    fixed_attrs: Dict[str, int] = field(default_factory=dict)
    desc_attrs: Dict[str, int] = field(default_factory=dict)
    script_attrs: Dict[str, int] = field(default_factory=dict)
    icon_source: Dict[str, str] = field(default_factory=dict)
    icon_import_log: Dict[str, object] = field(default_factory=dict)
    base_template_kind: str = ""
    base_template_label: str = ""


class EquipMakerError(RuntimeError):
    pass


def read_text_auto(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode(TEXT_ENCODING, errors="replace")


def write_mir_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode(TEXT_ENCODING))


def parse_range(value: str) -> Tuple[int, int]:
    value = value.strip()
    if "-" not in value:
        n = int(value)
        return n, n
    left, right = value.split("-", 1)
    return int(left.strip()), int(right.strip())


def parse_int(value: str) -> int:
    value = value.strip().replace("%", "")
    if not value:
        return 0
    return int(value)


def encode_weapon_attack_speed(value: str) -> int:
    """Encode the player-facing weapon speed bonus into LFM2 Mac2."""
    speed = parse_int(value)
    if speed < 0:
        raise EquipMakerError("攻击速度只允许填写0或正整数。")
    # LFM2 StdMode 5/6: Mac2 1..10 means a penalty; 11+ means
    # a bonus of Mac2-10.  The workbook always stores the final bonus.
    return 0 if speed == 0 else speed + 10


def _slot_attribute_has_effect(property_name: str, value: str) -> bool:
    """Return whether a source value actually requests a non-zero attribute."""
    value = value.strip()
    if not value:
        return False
    if property_name in {"防御", "魔御"}:
        low, high = parse_range(value)
        return low != 0 or high != 0
    return parse_int(value) != 0


def validate_slot_attribute_contract(
    slot: str,
    values: Iterable[Tuple[str, str]],
    stdmode: Optional[int] = None,
) -> None:
    """Reject base attributes whose storage fields conflict with the item slot."""
    canonical_names = {
        "防御下限": "防御",
        "防御上限": "防御",
        "魔御下限": "魔御",
        "魔御上限": "魔御",
    }
    requested: Dict[str, bool] = {}
    for raw_name, raw_value in values:
        property_name = canonical_names.get(raw_name.strip(), raw_name.strip())
        if property_name not in SLOT_ATTRIBUTE_RESTRICTIONS:
            continue
        if _slot_attribute_has_effect(property_name, raw_value):
            requested[property_name] = True

    conflicts: List[str] = []
    if slot in LUCK_SLOTS:
        for property_name in ("防御", "魔御"):
            if requested.get(property_name):
                conflicts.append(f"{property_name}（{SLOT_ATTRIBUTE_RESTRICTIONS[property_name]}）")
    if slot not in LUCK_SLOTS and requested.get("幸运"):
        conflicts.append(f"幸运（{SLOT_ATTRIBUTE_RESTRICTIONS['幸运']}）")
    # 项链只有标准幸运型 StdMode=19（时装为75）使用 Mac2 表示幸运。
    if requested.get("幸运") and slot in NECKLACE_SLOTS and stdmode not in (None, 19, 75):
        conflicts.append(f"幸运（当前项链 StdMode={stdmode} 不是幸运型 19/75）")
    if slot not in WEAPON_SLOTS:
        for property_name in ("攻击速度", "强度"):
            if requested.get(property_name):
                conflicts.append(f"{property_name}（{SLOT_ATTRIBUTE_RESTRICTIONS[property_name]}）")
    if conflicts:
        raise EquipMakerError(f"部位={slot} 不允许填写：" + "；".join(conflicts))


TITLE_ATTRIBUTE_FIELDS = {
    "Ac", "Ac2", "Mac", "Mac2", "Dc", "Dc2", "Mc", "Mc2", "Sc", "Sc2",
    "HP", "MP", "Element", "Asc", "Asc2", "Arc", "Arc2", "Mpc", "Mpc2",
    *(f"Element{index}" for index in range(1, 27)),
}


def title_name_from_scroll(scroll_name: str) -> str:
    prefix = "[称号]"
    if not scroll_name.startswith(prefix) or not scroll_name[len(prefix):].strip():
        raise EquipMakerError("称号卷名称必须按 [称号]称号名 填写，例如：[称号]小偷葛托克。")
    return scroll_name[len(prefix):].strip()


def validate_special_slot_contract(spec: EquipmentSpec) -> None:
    """Protect special inventory/title items from silently ineffective fields."""
    if spec.slot not in SPECIAL_SCRIPT_SLOTS:
        return
    if spec.fixed_attrs:
        raise EquipMakerError(f"{spec.slot} 不支持攻击/魔法/道术固定表加成，请改填脚本属性。")
    if spec.slot == BACKPACK_ARTIFACT_SLOT:
        invalid = sorted(
            field_name
            for field_name in TITLE_ATTRIBUTE_FIELDS
            if int(spec.fields.get(field_name, 0) or 0) != 0
        )
        if invalid:
            raise EquipMakerError(
                "背包神器的基础攻魔道/元素字段不会由引擎自动生效；"
                "请只填写脚本属性。无效字段：" + "、".join(invalid)
            )
    else:
        spec.title_name = title_name_from_scroll(spec.name)


def effect_subject_name(spec: EquipmentSpec) -> str:
    if spec.slot == TITLE_SCROLL_SLOT:
        return spec.title_name or title_name_from_scroll(spec.name)
    return spec.name


def effect_condition_line(spec: EquipmentSpec) -> str:
    subject = effect_subject_name(spec)
    if spec.slot == BACKPACK_ARTIFACT_SLOT:
        return f"CHECKITEM {subject} 1"
    if spec.slot == TITLE_SCROLL_SLOT:
        return f"CHECKFENGHAO {subject}"
    return f"CHECKITEMW {subject} 1"


def apply_native_element(spec: EquipmentSpec, key: str, value: str) -> bool:
    field = NATIVE_ELEMENT_FIELD_MAP.get(key.strip())
    if not field:
        return False
    v = parse_int(value)
    if value.strip():
        spec.fields[field] = v
    return True


def first_nonempty(section: configparser.SectionProxy, keys: Iterable[str]) -> str:
    for key in keys:
        value = section.get(key, "").strip()
        if value:
            return value
    return ""


def load_resource_profiles() -> List[dict]:
    if not RESOURCE_MAP.exists():
        return []
    with RESOURCE_MAP.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def find_resource_profile(code: int, slot: str) -> Optional[dict]:
    rows = [
        row for row in load_resource_profiles()
        if row.get("资源编号", "").strip() == str(code)
    ]
    if not rows:
        return None
    for row in rows:
        row_slot = row.get("部位", "").strip()
        if row_slot == slot:
            return row
    for row in rows:
        row_slot = row.get("部位", "").strip()
        if row_slot in ("", "通用"):
            return row
    return rows[0]


def int_from_row(row: Optional[dict], key: str) -> int:
    if not row:
        return 0
    value = row.get(key, "").strip()
    if not value:
        return 0
    return parse_int(value)


def validate_static_resource_profile(code: int, profile: Optional[dict]) -> None:
    if not profile:
        raise EquipMakerError(
            f"资源编号 {code} 未登记到 {RESOURCE_MAP}。"
            "必须先确认 Items/DnItems/StateItem 三套资源同编号配套后再生成装备。"
        )
    looks = int_from_row(profile, "Looks") or code
    items = int_from_row(profile, "Items")
    dnitems = int_from_row(profile, "DnItems")
    stateitem = int_from_row(profile, "StateItem")
    missing = [
        name for name, value in (
            ("Items", items),
            ("DnItems", dnitems),
            ("StateItem", stateitem),
        )
        if not value
    ]
    if missing:
        raise EquipMakerError(
            f"资源编号 {code} 的映射表缺少 {','.join(missing)}。"
            "背包、地面、装备栏必须同步登记。"
        )
    if len({looks, items, dnitems, stateitem}) != 1:
        raise EquipMakerError(
            f"资源编号 {code} 的 Looks/Items/DnItems/StateItem 不一致："
            f"Looks={looks}, Items={items}, DnItems={dnitems}, StateItem={stateitem}。"
            "当前引擎 DB 只写一个 Looks 字段，因此三套静态图标必须同编号配套。"
        )


def apply_resource_section(spec: EquipmentSpec, parser: configparser.ConfigParser) -> None:
    if not parser.has_section("资源"):
        return

    section = parser["资源"]
    code_text = first_nonempty(section, ("资源编号", "图标编号", "Looks编号", "Items编号", "Items", "Looks"))
    profile = None
    code = 0
    if code_text:
        code = parse_int(code_text)
        profile = find_resource_profile(code, spec.slot)
        validate_static_resource_profile(code, profile)

    looks_text = first_nonempty(section, ("Looks", "图标编号", "Items编号", "Items"))
    if looks_text:
        spec.fields["Looks"] = parse_int(looks_text)
    elif profile and int_from_row(profile, "Looks"):
        spec.fields["Looks"] = int_from_row(profile, "Looks")
    elif code:
        spec.fields["Looks"] = code

    shape_text = first_nonempty(section, ("Shape", "动作编号", "WeaponShape", "HumShape"))
    if shape_text:
        spec.fields["Shape"] = parse_int(shape_text)
    elif profile and int_from_row(profile, "Shape"):
        spec.fields["Shape"] = int_from_row(profile, "Shape")

    if profile and int_from_row(profile, "StdMode"):
        spec.fields["StdMode"] = int_from_row(profile, "StdMode")

    if spec.slot in ACTION_SLOTS and code and "Shape" not in spec.fields:
        raise EquipMakerError(
            f"{spec.slot} 使用资源编号 {code} 时必须能确定 Shape。"
            f"请在 {RESOURCE_MAP} 登记该编号的 Shape，或在 TXT [资源] 里填写 Shape=动作编号。"
        )


def apply_icon_source_section(spec: EquipmentSpec, parser: configparser.ConfigParser) -> None:
    for section_name in ("图标来源", "资源来源", "自动图标"):
        if not parser.has_section(section_name):
            continue
        section = parser[section_name]
        source_wzl = first_nonempty(section, ("来源WZL", "源WZL", "WZL", "来源文件", "SourceWzl", "Source"))
        source_id = first_nonempty(section, ("来源编号", "图片编号", "图标编号", "编号", "SourceId", "Id"))
        if not source_id:
            raise EquipMakerError(f"[{section_name}] 必须填写 来源编号。")
        if not source_wzl:
            source_wzl = str(CLIENT_DATA / "Items.wzl")
        spec.icon_source = {
            "source_wzl": source_wzl,
            "source_id": str(parse_int(source_id)),
        }
        return


def validate_slot_field_consistency(spec: EquipmentSpec) -> None:
    expected_stdmode = STD_MODE_BY_SLOT.get(spec.slot)
    actual_stdmode = spec.fields.get("StdMode")
    if expected_stdmode is not None and actual_stdmode is not None and actual_stdmode != expected_stdmode:
        raise EquipMakerError(
            f"部位与StdMode冲突：部位={spec.slot} 需要 StdMode={expected_stdmode}，"
            f"但TXT写了 StdMode={actual_stdmode}。请删除错误StdMode或改成正确编号。"
        )


def parse_spec(path: Path) -> EquipmentSpec:
    text = read_text_auto(path)
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read_string(text)

    if not parser.has_section("装备"):
        raise EquipMakerError("TXT 缺少 [装备] 段。")

    equip = parser["装备"]
    name = equip.get("名称", "").strip()
    if not name:
        raise EquipMakerError("[装备] 段缺少 名称。")

    slot = equip.get("部位", "").strip()
    validate_slot_attribute_contract(slot, equip.items())

    spec = EquipmentSpec(
        name=name,
        slot=slot,
        template=equip.get("模板", "").strip(),
    )

    for key, value in equip.items():
        key = key.strip()
        value = value.strip()
        if key in ("名称", "部位", "模板"):
            continue
        if key == "攻击":
            spec.fields["Dc"], spec.fields["Dc2"] = parse_range(value)
        elif key == "魔法":
            spec.fields["Mc"], spec.fields["Mc2"] = parse_range(value)
        elif key == "道术":
            spec.fields["Sc"], spec.fields["Sc2"] = parse_range(value)
        elif key == "防御":
            spec.fields["Ac"], spec.fields["Ac2"] = parse_range(value)
        elif key == "魔御":
            spec.fields["Mac"], spec.fields["Mac2"] = parse_range(value)
        elif key == "幸运":
            if spec.slot in WEAPON_SLOTS:
                spec.fields["Ac"] = parse_int(value)
            elif spec.slot in NECKLACE_SLOTS:
                spec.fields["Mac2"] = parse_int(value)
            else:
                spec.fields["Source"] = parse_int(value)
        elif key == "准确":
            if spec.slot in WEAPON_SLOTS:
                spec.fields["Ac2"] = parse_int(value)
            else:
                spec.fields["Ac"] = parse_int(value)
        elif key == "攻击速度":
            if spec.slot in WEAPON_SLOTS:
                spec.fields["Mac2"] = encode_weapon_attack_speed(value)
            else:
                spec.fields["Reserved"] = parse_int(value)
        elif key in BASE_FIELD_MAP:
            spec.fields[BASE_FIELD_MAP[key]] = parse_int(value)
        else:
            apply_native_element(spec, key, value)

    if spec.slot and "StdMode" not in spec.fields and spec.slot in STD_MODE_BY_SLOT:
        spec.fields["StdMode"] = STD_MODE_BY_SLOT[spec.slot]

    for field_name, value in SLOT_DEFAULT_FIELDS.get(spec.slot, {}).items():
        spec.fields.setdefault(field_name, value)

    if spec.slot and spec.slot not in STD_MODE_BY_SLOT and not spec.template and "StdMode" not in spec.fields:
        raise EquipMakerError(
            f"未知部位：{spec.slot}。请在 TXT 里填写 模板=已有同部位装备，或直接填写 StdMode=编号。"
        )

    apply_resource_section(spec, parser)
    apply_icon_source_section(spec, parser)

    for section in NATIVE_ELEMENT_SECTIONS:
        if parser.has_section(section):
            for key, value in parser[section].items():
                if not apply_native_element(spec, key, value):
                    raise EquipMakerError(f"未识别原生属性：{key}。请先登记 Element 字段映射。")

    for section in ("绿字属性", "脚本属性", "特殊属性", "玄渊属性"):
        if parser.has_section(section):
            for key, value in parser[section].items():
                v = parse_int(value)
                if v:
                    spec.script_attrs[key.strip()] = v
                    spec.desc_attrs[key.strip()] = v

    for section in ("固定表属性", "固定属性", "明月属性"):
        if parser.has_section(section):
            for key, value in parser[section].items():
                key = key.strip()
                v = parse_int(value)
                if v:
                    if key not in FIXED_TABLE_ATTRS:
                        raise EquipMakerError(f"未识别固定表属性：{key}")
                    spec.fixed_attrs[key] = v
                    spec.desc_attrs[key] = v

    for section in ("显示属性", "说明属性"):
        if parser.has_section(section):
            for key, value in parser[section].items():
                v = parse_int(value)
                if v:
                    spec.desc_attrs[key.strip()] = v

    if parser.has_section("备注"):
        remark = parser.get("备注", "说明", fallback="").strip()
        remark = " ".join(remark.splitlines())
        if "\\" in remark:
            raise EquipMakerError("备注禁止包含反斜杠控制符")
        spec.remark = remark

    validate_slot_field_consistency(spec)
    validate_special_slot_contract(spec)

    return spec


def load_script_props() -> dict:
    return json.loads(SCRIPT_PROPS.read_text(encoding="utf-8"))


def connect_db() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def read_wzx_count_and_offset(wzx_path: Path, image_id: int) -> int:
    import struct

    data = wzx_path.read_bytes()
    if len(data) < 48:
        raise EquipMakerError(f"WZX 文件过小：{wzx_path}")
    if (len(data) - 48) % 4:
        raise EquipMakerError(f"WZX 偏移表长度不是4字节整数倍：{wzx_path}")
    count = (len(data) - 48) // 4
    if image_id < 0 or image_id >= count:
        raise EquipMakerError(f"来源编号 {image_id} 超出范围 0-{count - 1}：{wzx_path}")
    return struct.unpack_from("<I", data, 48 + image_id * 4)[0]


STATIC_ICON_LIBRARIES = ("Items", "StateItem", "DnItems")
MATERIAL_ICON_LIBRARIES = ("Items",)


def preflight_icon_source(
    spec: EquipmentSpec,
    libraries: tuple[str, ...] = STATIC_ICON_LIBRARIES,
) -> None:
    if not spec.icon_source:
        return
    source_id = int(spec.icon_source["source_id"])
    for lib in libraries:
        source_wzl = CLIENT_DATA / f"{lib}.wzl"
        source_wzx = CLIENT_DATA / f"{lib}.wzx"
        if not source_wzl.exists():
            raise EquipMakerError(f"图标来源 WZL 不存在：{source_wzl}")
        if not source_wzx.exists():
            raise EquipMakerError(f"图标来源 WZX 不存在：{source_wzx}")
        offset = read_wzx_count_and_offset(source_wzx, source_id)
        if offset <= 0:
            raise EquipMakerError(f"图标来源编号为空：{source_wzx} #{source_id}")


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_filename(name: str) -> str:
    return "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in name)


def read_wzx_offsets(wzx_path: Path) -> List[int]:
    data = wzx_path.read_bytes()
    if len(data) < 48:
        raise EquipMakerError(f"WZX 文件过小：{wzx_path}")
    if (len(data) - 48) % 4:
        raise EquipMakerError(f"WZX 偏移表长度不是4字节整数倍：{wzx_path}")
    count = (len(data) - 48) // 4
    return [struct.unpack_from("<I", data, 48 + i * 4)[0] for i in range(count)]


def read_wzl_header_count(wzl_path: Path) -> int:
    data = wzl_path.read_bytes()
    if len(data) < 48:
        raise EquipMakerError(f"WZL 文件过小：{wzl_path}")
    return struct.unpack_from("<I", data, 44)[0]


def read_wzl_frame_header(lib: str, image_id: int) -> Dict[str, int]:
    wzx_path = CLIENT_DATA / f"{lib}.wzx"
    wzl_path = CLIENT_DATA / f"{lib}.wzl"
    if not wzx_path.exists() or not wzl_path.exists():
        raise EquipMakerError(f"客户端静态图库缺失：{wzl_path} / {wzx_path}")
    wzx_data = wzx_path.read_bytes()
    if len(wzx_data) < 48:
        raise EquipMakerError(f"WZX 文件过小：{wzx_path}")
    wzx_declared = struct.unpack_from("<I", wzx_data, 44)[0]
    wzx_offset_count = (len(wzx_data) - 48) // 4
    if wzx_declared != wzx_offset_count:
        raise EquipMakerError(f"{lib} WZX 声明数量 {wzx_declared} 与偏移数量 {wzx_offset_count} 不一致")
    if len(wzx_data) != 48 + wzx_declared * 4:
        raise EquipMakerError(f"{lib} WZX 文件长度异常：{len(wzx_data)} != 48 + {wzx_declared} * 4")
    offsets = [struct.unpack_from("<I", wzx_data, 48 + i * 4)[0] for i in range(wzx_offset_count)]
    wzl_header_count = read_wzl_header_count(wzl_path)
    if image_id < 0 or image_id >= len(offsets):
        raise EquipMakerError(f"{lib} 新编号 {image_id} 超出范围 0-{len(offsets) - 1}")
    if wzl_header_count < image_id + 1:
        raise EquipMakerError(
            f"{lib} WZL头部count未更新，客户端可能不显示新图标。"
            f" WZL header count={wzl_header_count}, Looks={image_id}"
        )
    offset = offsets[image_id]
    if offset <= 0:
        raise EquipMakerError(f"{lib} 新编号 {image_id} 偏移为空")
    data = wzl_path.read_bytes()
    if offset + 16 > len(data):
        raise EquipMakerError(f"{lib} 新编号 {image_id} 偏移越界：offset={offset}, size={len(data)}")
    frame_type, _zero, width, height, x, y, payload_len, unk = struct.unpack_from("<HHHHhhhh", data, offset)
    return {
        "count": len(offsets),
        "wzx_declared_count": wzx_declared,
        "wzx_offset_count": wzx_offset_count,
        "wzx_file_length": len(wzx_data),
        "wzx_expected_length": 48 + wzx_declared * 4,
        "wzl_header_count": wzl_header_count,
        "offset": offset,
        "type": frame_type,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "payload_len": payload_len,
        "unk": unk,
    }


def verify_static_icon_import(
    looks: int,
    output_dir: str,
    backup_dir: str,
    libraries: tuple[str, ...] = STATIC_ICON_LIBRARIES,
) -> Dict[str, object]:
    if not output_dir:
        raise EquipMakerError("自动图标导入未返回 OUTPUT_DIR，无法读回校验。")
    result_path = Path(output_dir) / "result.json"
    if not result_path.exists():
        raise EquipMakerError(f"自动图标导入结果文件不存在：{result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    target_id = int(result.get("target_id", -1))
    if target_id != looks:
        raise EquipMakerError(f"LOOKS={looks} 与 result.json target_id={target_id} 不一致。")

    counts_before = result.get("counts_before", {})
    if not isinstance(counts_before, dict) or set(counts_before) != set(libraries):
        raise EquipMakerError(f"result.json counts_before 缺失或不完整：{result_path}")
    result_libraries = tuple(result.get("libraries", libraries))
    if result_libraries != libraries:
        raise EquipMakerError(
            f"result.json 图库范围不一致：实际={result_libraries}，期望={libraries}"
        )
    before_values = [int(counts_before[lib]) for lib in libraries]
    if target_id != max(before_values):
        raise EquipMakerError(f"新编号 {target_id} 应等于导入前图库最大物理槽数 {max(before_values)}，实际不一致。")

    frames: Dict[str, Dict[str, int]] = {}
    counts_after: Dict[str, int] = {}
    wzl_header_counts_after: Dict[str, int] = {}
    mode = str(result.get("mode", "decode_type6"))
    for lib in libraries:
        frame = read_wzl_frame_header(lib, target_id)
        frames[lib] = frame
        counts_after[lib] = int(frame["count"])
        wzl_header_counts_after[lib] = int(frame["wzl_header_count"])
        if frame["count"] != target_id + 1:
            raise EquipMakerError(f"{lib} 导入后 count={frame['count']}，期望 {target_id + 1}。")
        if frame["wzx_declared_count"] != target_id + 1:
            raise EquipMakerError(f"{lib} WZX declared count={frame['wzx_declared_count']}，期望 {target_id + 1}。")
        if frame["wzl_header_count"] != target_id + 1:
            raise EquipMakerError(
                f"{lib} WZL头部count未更新，客户端可能不显示新图标。"
                f" WZL header count={frame['wzl_header_count']}，期望 {target_id + 1}。"
            )
        if frame["wzx_file_length"] != frame["wzx_expected_length"]:
            raise EquipMakerError(
                f"{lib} WZX 文件长度异常：{frame['wzx_file_length']} != {frame['wzx_expected_length']}"
            )
        if mode != "raw_clone" and frame["type"] != 6:
            raise EquipMakerError(f"{lib}#{target_id} 帧类型={frame['type']}，期望 type=6。")
        if frame["width"] <= 0 or frame["height"] <= 0:
            raise EquipMakerError(f"{lib}#{target_id} 尺寸异常：{frame['width']}x{frame['height']}")
        if mode == "raw_clone":
            verify = result.get("verify", {}).get(lib, {}) if isinstance(result.get("verify"), dict) else {}
            if isinstance(verify, dict) and not bool(verify.get("byte_identical", False)):
                raise EquipMakerError(f"{lib}#{target_id} raw clone 字节一致性校验失败。")
        else:
            extract = result.get("extract", {})
            source_info = extract.get(lib, {}) if isinstance(extract, dict) else {}
            if isinstance(source_info, dict):
                source_x = int(source_info.get("x", 0))
                source_y = int(source_info.get("y", 0))
                if int(frame["x"]) != source_x or int(frame["y"]) != source_y:
                    raise EquipMakerError(
                        f"{lib}#{target_id} 坐标偏移丢失：实际 x={frame['x']},y={frame['y']}；"
                        f"来源 x={source_x},y={source_y}"
                    )

    log = {
        "looks": target_id,
        "mode": mode,
        "output_dir": output_dir,
        "client_resource_backup_dir": backup_dir,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "wzl_header_counts_after": wzl_header_counts_after,
        "frames": frames,
        "result_json": str(result_path),
    }
    return log


def make_generation_backup(spec: EquipmentSpec) -> Path:
    backup_dir = BACKUP_ROOT / f"XuanYuan_EquipMaker_Generate_{now_stamp()}_{safe_filename(spec.name)}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for src in (DB_PATH, ITEM_DESC, ITEM_RULE, GROUP_ITEM, QFUNCTION, QMANAGE, ATTRIBUTE_PANEL):
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)
    if spec.slot == TITLE_SCROLL_SLOT and FENGHAO_DATA is not None and FENGHAO_DATA.exists():
        shutil.copy2(FENGHAO_DATA, backup_dir / FENGHAO_DATA.name)
    return backup_dir


def verify_db_item(idx: int, name: str) -> Dict[str, object]:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT Idx, Name, hex(Name), StdMode, Shape, Looks FROM StdItems WHERE Idx=? AND Name=?",
            (idx, name),
        ).fetchone()
        if row is None:
            raise EquipMakerError(f"DB 写入后复核失败：找不到 Idx={idx}, Name={name}")
        return {
            "Idx": row[0],
            "Name": row[1],
            "NameHex": row[2],
            "StdMode": row[3],
            "Shape": row[4],
            "Looks": row[5],
        }
    finally:
        conn.close()


def write_generation_log(spec: EquipmentSpec, idx: int, server_backup_dir: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_item = verify_db_item(idx, spec.name)
    log = {
        "time": now_stamp(),
        "name": spec.name,
        "idx": idx,
        "slot": spec.slot,
        "template": spec.template,
        "remark": spec.remark,
        "base_template_kind": spec.base_template_kind,
        "base_template_label": spec.base_template_label,
        "stdmode": spec.fields.get("StdMode"),
        "shape": spec.fields.get("Shape"),
        "looks": spec.fields.get("Looks"),
        "fields": spec.fields,
        "script_attrs": spec.script_attrs,
        "desc_attrs": spec.desc_attrs,
        "title": ({
            "name": spec.title_name,
            "idx": spec.title_idx,
            "shape": spec.title_shape,
            "looks": spec.title_looks,
            "trigger": spec.fields.get("Anicount"),
        } if spec.slot == TITLE_SCROLL_SLOT else None),
        "icon_import": spec.icon_import_log,
        "server_backup_dir": server_backup_dir,
        "db_item": db_item,
        "make_command": f"@make {spec.name} 1",
        "restart_warning": "生成后需要完整重启 M2，并关闭重开客户端/登录器再验证图标。",
    }
    path = OUTPUT_DIR / f"generation_{now_stamp()}_{safe_filename(spec.name)}.json"
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_raw_clone_args(
    spec: EquipmentSpec,
    register_resource: bool = True,
    libraries: tuple[str, ...] = STATIC_ICON_LIBRARIES,
) -> argparse.Namespace:
    if CLIENT_DATA is None:
        raise EquipMakerError("图标资源装备必须显式选择客户端 data 目录。")
    stdmode = str(spec.fields.get("StdMode", STD_MODE_BY_SLOT.get(spec.slot, "")))
    shape = str(spec.fields.get("Shape", ""))
    return argparse.Namespace(
        source_id=int(spec.icon_source["source_id"]),
        name=spec.name,
        slot=spec.slot,
        stdmode=stdmode,
        shape=shape,
        register_resource=register_resource,
        libraries=libraries,
        client_data=CLIENT_DATA,
        output_dir=OUTPUT_DIR,
        backup_root=BACKUP_ROOT,
        resource_map=RESOURCE_MAP,
        dry_run=False,
    )


def apply_static_icon_source(
    spec: EquipmentSpec,
    register_resource: bool = True,
    libraries: tuple[str, ...] = STATIC_ICON_LIBRARIES,
) -> str:
    if not spec.icon_source:
        return ""
    if not RAW_CLONE_IMPORTER.exists():
        raise EquipMakerError(f"raw clone 图标导入器不存在：{RAW_CLONE_IMPORTER}")

    try:
        result = clone_wzl_frame_raw.run(
            build_raw_clone_args(spec, register_resource=register_resource, libraries=libraries)
        )
    except Exception as exc:
        raise EquipMakerError(f"raw clone 自动图标导入失败：\n{exc}") from exc

    looks = int(result.get("target_id", 0))
    output_dir = str(result.get("output_dir", ""))
    backup_dir = str(result.get("backup_dir", ""))
    if not looks:
        raise EquipMakerError("raw clone 自动图标导入未返回 LOOKS 编号。")
    spec.icon_import_log = verify_static_icon_import(looks, output_dir, backup_dir, libraries)
    spec.fields["Looks"] = looks
    parts = [f"raw clone 自动图标已导入：Looks={looks}"]
    if output_dir:
        parts.append(f"输出目录={output_dir}")
    if backup_dir:
        parts.append(f"客户端资源备份={backup_dir}")
    frames = spec.icon_import_log.get("frames", {})
    counts_before = spec.icon_import_log.get("counts_before", {})
    counts_after = spec.icon_import_log.get("counts_after", {})
    wzl_header_counts_after = spec.icon_import_log.get("wzl_header_counts_after", {})
    parts.append(f"三套WZX count：{counts_before} -> {counts_after}")
    parts.append(f"三套WZL header count：{wzl_header_counts_after}")
    parts.append("已同步更新 WZX count 和 WZL header count")
    parts.append("三套帧为原始字节克隆，不解码 type259/type2309")
    parts.append(f"帧头={frames}")
    return "；".join(parts)


def reuse_static_icon_source(
    spec: EquipmentSpec,
    libraries: tuple[str, ...] = STATIC_ICON_LIBRARIES,
) -> str:
    """Use an existing icon id from the selected client without cloning it.

    The workbook source id already belongs to the selected target client, so a
    newly created equipment row can reference it directly through StdItems.Looks.
    Every required library is still read back before any database write.
    """
    if not spec.icon_source:
        return ""
    if CLIENT_DATA is None:
        raise EquipMakerError("图标资源装备必须显式选择客户端 data 目录。")

    preflight_icon_source(spec, libraries)
    source_id = int(spec.icon_source["source_id"])
    frames = {library: read_wzl_frame_header(library, source_id) for library in libraries}
    spec.fields["Looks"] = source_id
    spec.icon_import_log = {
        "looks": source_id,
        "source_id": source_id,
        "mode": "reuse_source_id",
        "action": "reuse_source_id",
        "libraries": list(libraries),
        "client_data": str(CLIENT_DATA),
        "client_files_changed": False,
        "frames": frames,
    }
    return (
        f"直接复用客户端现有图标：Looks={source_id}；"
        f"已校验图库={','.join(libraries)}；未修改 WZL/WZX"
    )


def table_columns(conn: sqlite3.Connection) -> List[str]:
    return [row[1] for row in conn.execute("PRAGMA table_info(StdItems)").fetchall()]


def get_item(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    cur = conn.execute("SELECT * FROM StdItems WHERE Name=?", (name,))
    row = cur.fetchone()
    if row is None:
        return None
    cols = table_columns(conn)
    return dict(zip(cols, row))


def first_item_by_stdmode(conn: sqlite3.Connection, stdmode: int) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM StdItems WHERE StdMode=? AND Name IS NOT NULL AND Name<>'' ORDER BY Idx ASC LIMIT 1",
        (stdmode,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    cols = table_columns(conn)
    return dict(zip(cols, row))


def platform_base_profile(stdmode: int) -> Optional[dict]:
    profile_path = SCRIPT_PROPS.parent / "slot_base_profiles.json"
    if not profile_path.exists():
        return None
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    profile = data.get("profiles", {}).get(str(stdmode))
    if not isinstance(profile, dict):
        return None
    fields = profile.get("fields")
    if not isinstance(fields, dict) or int(fields.get("StdMode", -1)) != stdmode:
        raise EquipMakerError(f"平台基础母版配置无效：{profile_path} StdMode={stdmode}")
    result = dict(fields)
    result["Name"] = ""
    result["_platform_base_label"] = f"平台基础母版（{profile.get('label', '未知部位')}，StdMode={stdmode}）"
    return result


def resolve_template_in_connection(spec: EquipmentSpec, conn: sqlite3.Connection) -> dict:
    expected_stdmode = STD_MODE_BY_SLOT.get(spec.slot)
    if spec.base_template_kind == "platform":
        if expected_stdmode is None:
            raise EquipMakerError(f"未知部位缺少基础母版规则：{spec.slot}")
        profile = platform_base_profile(expected_stdmode)
        if profile is None:
            raise EquipMakerError(f"目标服缺少同部位基础结构：部位={spec.slot}，StdMode={expected_stdmode}")
        return profile
    if spec.template:
        template = get_item(conn, spec.template)
        if template is None:
            raise EquipMakerError(f"模板装备不存在，已停止：{spec.template}")
        actual_stdmode = int(template.get("StdMode") or 0)
        if expected_stdmode is not None and actual_stdmode != expected_stdmode:
            raise EquipMakerError(
                f"模板装备部位不匹配：{spec.template} StdMode={actual_stdmode}，"
                f"部位={spec.slot} 需要 StdMode={expected_stdmode}"
            )
        spec.base_template_kind = "target"
        spec.base_template_label = spec.template
        return template
    if expected_stdmode is None:
        raise EquipMakerError(f"未知部位缺少基础母版规则：{spec.slot}")
    template = first_item_by_stdmode(conn, expected_stdmode)
    if template is not None:
        spec.template = str(template["Name"])
        spec.base_template_kind = "target"
        spec.base_template_label = spec.template
        return template
    profile = platform_base_profile(expected_stdmode)
    if profile is None:
        raise EquipMakerError(f"目标服缺少同部位基础结构：部位={spec.slot}，StdMode={expected_stdmode}")
    spec.base_template_kind = "platform"
    spec.base_template_label = str(profile["_platform_base_label"])
    return profile


def validate_template_exists(spec: EquipmentSpec) -> None:
    conn = connect_db()
    try:
        resolve_template_in_connection(spec, conn)
    finally:
        conn.close()


def _first_free(values: Iterable[int], start: int, stop: int, label: str) -> int:
    used = {int(value) for value in values if value is not None}
    for candidate in range(start, stop + 1):
        if candidate not in used:
            return candidate
    raise EquipMakerError(f"没有可用的{label}编号（{start}-{stop}）。")


def prepare_special_allocations(
    spec: EquipmentSpec,
    conn: sqlite3.Connection,
    qfunction_text: str,
) -> None:
    if spec.slot == BACKPACK_ARTIFACT_SLOT:
        spec.fields.update({"StdMode": 41, "Shape": 0, "DuraMax": 0, "OverLap": 0})
        return
    if spec.slot != TITLE_SCROLL_SLOT:
        return
    spec.title_name = getattr(spec, "title_name", "") or title_name_from_scroll(spec.name)
    if get_item(conn, spec.title_name):
        raise EquipMakerError(f"称号名已存在，已停止：{spec.title_name}")
    used_triggers = {
        int(row[0])
        for row in conn.execute(
            "SELECT Anicount FROM StdItems WHERE StdMode=31 AND Anicount BETWEEN 1 AND 255"
        ).fetchall()
        if row[0] is not None
    }
    for match in re.finditer(r"\[@StdModeFunc(\d+)\]", qfunction_text, flags=re.I):
        used_triggers.add(int(match.group(1)))
    trigger = _first_free(used_triggers, 80, 255, "称号卷触发")
    used_shapes = [
        int(row[0])
        for row in conn.execute("SELECT Shape FROM StdItems WHERE StdMode=70").fetchall()
        if row[0] is not None
    ]
    spec.title_shape = _first_free(used_shapes, 0, 255, "称号Shape")
    spec.title_looks = spec.title_shape * 5
    spec.fields.update({
        "StdMode": 31,
        "Shape": 0,
        "Anicount": trigger,
        "DuraMax": 1,
        "OverLap": 0,
    })


def _build_insert_row(
    cols: List[str],
    template: dict,
    idx: int,
    name: str,
    overrides: Dict[str, int],
) -> dict:
    row: dict = {}
    for column in cols:
        row[column] = template.get(column, 0) if column in INHERIT_FIELDS else 0
    row["Idx"] = idx
    row["Name"] = name
    for column in CLEAR_FIELDS:
        if column in row:
            row[column] = 0
    for key, value in overrides.items():
        if key in row:
            row[key] = value
    return row


def insert_title_scroll_bundle(spec: EquipmentSpec) -> int:
    conn = connect_db()
    try:
        if get_item(conn, spec.name) or get_item(conn, spec.title_name):
            raise EquipMakerError(f"称号卷或称号名称已存在，已停止：{spec.name} / {spec.title_name}")
        cols = table_columns(conn)
        scroll_template = resolve_template_in_connection(spec, conn)
        title_template = first_item_by_stdmode(conn, 70) or platform_base_profile(70)
        if title_template is None:
            raise EquipMakerError("目标服缺少 StdMode=70 称号基础结构。")
        first_idx = int(conn.execute("SELECT COALESCE(MAX(Idx),0)+1 FROM StdItems").fetchone()[0])
        control_fields = set(INHERIT_FIELDS) | {"Source", "Reserved"}
        scroll_overrides = {
            key: value for key, value in spec.fields.items() if key in control_fields
        }
        scroll_overrides.update({
            "StdMode": 31, "Shape": 0, "DuraMax": 1, "OverLap": 0,
        })
        title_overrides = {
            key: value for key, value in spec.fields.items() if key in TITLE_ATTRIBUTE_FIELDS
        }
        title_overrides.update({
            "StdMode": 70,
            "Shape": spec.title_shape,
            "Anicount": 1,
            "Looks": spec.title_looks,
            "DuraMax": 0,
            "OverLap": 0,
            "Need": 0,
            "NeedLevel": 0,
        })
        scroll_row = _build_insert_row(cols, scroll_template, first_idx, spec.name, scroll_overrides)
        title_row = _build_insert_row(cols, title_template, first_idx + 1, spec.title_name, title_overrides)
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT INTO StdItems ({','.join(cols)}) VALUES ({placeholders})"
        conn.execute(sql, [scroll_row.get(column) for column in cols])
        conn.execute(sql, [title_row.get(column) for column in cols])
        conn.commit()
        spec.title_idx = first_idx + 1
        return first_idx
    finally:
        conn.close()


def insert_stditem(spec: EquipmentSpec) -> int:
    conn = connect_db()
    try:
        if get_item(conn, spec.name):
            raise EquipMakerError(f"装备名已存在，已停止：{spec.name}")

        cols = table_columns(conn)
        template = resolve_template_in_connection(spec, conn)

        new_idx = int(conn.execute("SELECT COALESCE(MAX(Idx),0)+1 FROM StdItems").fetchone()[0])
        row = _build_insert_row(cols, template, new_idx, spec.name, spec.fields)

        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT INTO StdItems ({','.join(cols)}) VALUES ({placeholders})"
        conn.execute(sql, [row.get(c) for c in cols])
        conn.commit()
        return new_idx
    finally:
        conn.close()


ITEM_REMARK_WRAP_COLUMNS = 40
ITEM_REMARK_BREAK_AFTER = frozenset("，。；！？、：,.!?;: ")
ITEM_REMARK_FORBIDDEN_LINE_START = frozenset("，。；！？、：,.!?;:）】》」』”’")
ITEM_REMARK_FORBIDDEN_LINE_END = frozenset("（【《「『“‘")


def item_remark_display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def wrap_item_remark(text: str, max_columns: int = ITEM_REMARK_WRAP_COLUMNS) -> List[str]:
    if max_columns < 4:
        raise ValueError("装备说明断行宽度不能小于4列")

    remaining = " ".join(str(text or "").splitlines()).strip()
    lines: List[str] = []
    while remaining:
        if item_remark_display_width(remaining) <= max_columns:
            lines.append(remaining)
            break

        width = 0
        hard_cut = 0
        preferred_cut = 0
        for index, char in enumerate(remaining):
            char_width = item_remark_display_width(char)
            if width + char_width > max_columns:
                break
            width += char_width
            hard_cut = index + 1
            if char in ITEM_REMARK_BREAK_AFTER:
                preferred_cut = hard_cut

        if hard_cut == 0:
            hard_cut = 1
        cut = preferred_cut if preferred_cut >= max(1, hard_cut // 2) else hard_cut

        while cut < len(remaining) and remaining[cut] in ITEM_REMARK_FORBIDDEN_LINE_START:
            cut += 1

        line = remaining[:cut].rstrip()
        tail = remaining[cut:].lstrip()
        while len(line) > 1 and line[-1] in ITEM_REMARK_FORBIDDEN_LINE_END:
            tail = line[-1] + tail
            line = line[:-1].rstrip()

        if not line:
            line = remaining[:hard_cut]
            tail = remaining[hard_cut:].lstrip()
        lines.append(line)
        remaining = tail

    return lines


def desc_line(spec: EquipmentSpec, prop_registry: dict) -> str:
    def c(code: int, text: str) -> str:
        return f"\\{code}/　{text}"

    remark_lines = wrap_item_remark(spec.remark or "玄渊固定装备")
    parts = [c(242, line) for line in remark_lines]
    fixed_keys = [key for key in spec.fixed_attrs if key in spec.desc_attrs]
    script_keys = [key for key in spec.script_attrs if key in spec.desc_attrs]
    other_keys = [key for key in spec.desc_attrs if key not in spec.fixed_attrs and key not in spec.script_attrs]

    if fixed_keys:
        parts.append("\\-")
        parts.append(c(146, "[单件触发]："))
        for key in fixed_keys:
            value = spec.desc_attrs[key]
            parts.append(c(254, f"{key}+{value}%"))

    if script_keys:
        parts.append("\\-")
        parts.append(c(146, "[隐藏触发]："))
        for key in script_keys:
            value = spec.desc_attrs[key]
            meta = prop_registry.get("properties", {}).get(key, {})
            label = meta.get("label", key)
            unit = meta.get("unit", "%")
            parts.append(c(251, f"{label}+{value}{unit}"))

    for key in other_keys:
        value = spec.desc_attrs[key]
        meta = prop_registry.get("properties", {}).get(key, {})
        label = meta.get("label", key)
        unit = meta.get("unit", "%")
        parts.append(c(250, f"{label}+{value}{unit}"))
    return spec.name + "=" + "".join(parts)


def append_item_desc(spec: EquipmentSpec, prop_registry: dict) -> None:
    line = desc_line(spec, prop_registry)
    text = read_text_auto(ITEM_DESC)
    existing = [ln for ln in text.splitlines() if ln.startswith(spec.name + "=")]
    if existing:
        raise EquipMakerError(f"ItemDescList 已存在同名显示行，已停止：{spec.name}")
    if text and not text.endswith(("\n", "\r")):
        text += "\r\n"
    text += line + "\r\n"
    write_mir_text(ITEM_DESC, text)


def _nonzero_range(fields: Dict[str, int], low: str, high: str) -> Optional[str]:
    left = int(fields.get(low, 0) or 0)
    right = int(fields.get(high, 0) or 0)
    if left == 0 and right == 0:
        return None
    return f"{left}-{right}"


def title_description_parts(spec: EquipmentSpec, prop_registry: dict) -> List[str]:
    parts: List[str] = []
    for label, low, high in (
        ("防御", "Ac", "Ac2"), ("魔御", "Mac", "Mac2"),
        ("攻击", "Dc", "Dc2"), ("魔法", "Mc", "Mc2"), ("道术", "Sc", "Sc2"),
    ):
        value = _nonzero_range(spec.fields, low, high)
        if value is not None:
            parts.append(f"{label}+{value}")
    for label, field_name in (("HP", "HP"), ("MP", "MP")):
        value = int(spec.fields.get(field_name, 0) or 0)
        if value:
            parts.append(f"{label}+{value}")
    props = prop_registry.get("properties", {})
    for key, value in spec.desc_attrs.items():
        meta = props.get(key, {})
        label = str(meta.get("label", key))
        unit = str(meta.get("unit", "%"))
        parts.append(f"{label}+{value}{unit}")
    return parts or ["无额外属性"]


def append_title_metadata(spec: EquipmentSpec, prop_registry: dict) -> None:
    if spec.slot != TITLE_SCROLL_SLOT:
        return
    if FENGHAO_DATA is None:
        raise EquipMakerError("称号卷必须选择客户端 data 目录，才能同步 fenghao.dat。")
    description = "；".join(title_description_parts(spec, prop_registry))

    item_text = read_text_auto(ITEM_DESC) if ITEM_DESC.exists() else ""
    if any(line.startswith(spec.title_name + "=") for line in item_text.splitlines()):
        raise EquipMakerError(f"ItemDescList 已存在同名称号显示行，已停止：{spec.title_name}")
    if item_text and not item_text.endswith(("\n", "\r")):
        item_text += "\r\n"
    item_text += f"{spec.title_name}=\\242/　[称号属性]\\-\\251/　{description}\r\n"
    write_mir_text(ITEM_DESC, item_text)

    title_text = read_text_auto(FENGHAO_DATA) if FENGHAO_DATA.exists() else ""
    if any(line.startswith(spec.title_name + "=") for line in title_text.splitlines()):
        raise EquipMakerError(f"fenghao.dat 已存在同名称号说明，已停止：{spec.title_name}")
    if title_text and not title_text.endswith(("\n", "\r")):
        title_text += "\r\n"
    title_text += f"{spec.title_name}={description}\r\n"
    write_mir_text(FENGHAO_DATA, title_text)


def replace_item_desc(spec: EquipmentSpec, prop_registry: dict, trailing_suffix: str = "") -> None:
    line = desc_line(spec, prop_registry) + trailing_suffix
    text = read_text_auto(ITEM_DESC) if ITEM_DESC.exists() else ""
    prefix = spec.name + "="
    lines = text.splitlines()
    out: list[str] = []
    replaced = False
    for existing in lines:
        if existing.startswith(prefix):
            out.append(line)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(line)
    write_mir_text(ITEM_DESC, "\r\n".join(out) + "\r\n")


def replace_or_append_named_line(path: Path, name: str, line: str, separator: str = "\t") -> None:
    text = read_text_auto(path) if path.exists() else ""
    lines = text.splitlines()
    prefix = name + separator
    replaced = False
    out: list[str] = []
    for existing in lines:
        if existing.startswith(prefix):
            out.append(line)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(line)
    write_mir_text(path, "\r\n".join(out) + "\r\n")


def next_group_item_id() -> int:
    if not GROUP_ITEM.exists():
        return 1
    max_id = 0
    text = read_text_auto(GROUP_ITEM)
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            max_id = max(max_id, int(line.split("\t", 1)[0]))
        except (ValueError, IndexError):
            continue
    return max_id + 1


def existing_group_item_id(name: str) -> int:
    if not GROUP_ITEM.exists():
        return 0
    text = read_text_auto(GROUP_ITEM)
    marker = "\t" + name + "\t"
    for line in text.splitlines():
        if marker in line:
            try:
                return int(line.split("\t", 1)[0])
            except (ValueError, IndexError):
                return 0
    return 0


def fixed_rule_line(spec: EquipmentSpec) -> str:
    flags = ["0"] * 40
    if spec.fixed_attrs:
        flags[12] = "1"
    for key in spec.fixed_attrs:
        flags[FIXED_TABLE_ATTRS[key]["rule_index"]] = "1"
    return f"{spec.name}\t{' '.join(flags)} |0 0 0 0 0 0 0 0 0 0"


def fixed_group_line(spec: EquipmentSpec, group_id: int) -> str:
    groups = [["0"] * 40, ["0"] * 40, ["0"] * 40, ["0"] * 27]
    for key, value in spec.fixed_attrs.items():
        groups[1][FIXED_TABLE_ATTRS[key]["group_index"]] = str(value)
    if spec.fixed_attrs:
        groups[2][19] = "100"
    return (
        f"{group_id}\t1\t装备触发\t{spec.name}\t"
        + "\t".join("|".join(group) for group in groups)
        + "\t"
    )


def patch_fixed_tables(spec: EquipmentSpec) -> None:
    if not spec.fixed_attrs:
        return
    replace_or_append_named_line(ITEM_RULE, spec.name, fixed_rule_line(spec))
    group_id = existing_group_item_id(spec.name) or next_group_item_id()
    line = fixed_group_line(spec, group_id)
    text = read_text_auto(GROUP_ITEM) if GROUP_ITEM.exists() else ""
    lines = text.splitlines()
    marker = "\t" + spec.name + "\t"
    replaced = False
    out: list[str] = []
    for existing in lines:
        if marker in existing:
            out.append(line)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(line)
    write_mir_text(GROUP_ITEM, "\r\n".join(out) + "\r\n")


def ensure_anchor(text: str, anchor: str, fallback_after: str) -> str:
    if anchor in text:
        return text
    if anchor in STRICT_EXISTING_ANCHORS:
        raise EquipMakerError(f"目标 QFunction 未植入对应正式功能，缺少严格锚点：{anchor}")
    if anchor in RUNTIME_REFRESH_ANCHORS:
        return ensure_runtime_refresh_framework(text)
    if anchor == "; XY_EQUIP_MAKER_CORPSE_ANCHOR":
        return ensure_corpse_anchor(text)
    pos = text.find(fallback_after)
    if pos < 0:
        raise EquipMakerError(f"找不到 QFunction 插入锚点，也找不到回退位置：{anchor}")
    insert_at = pos + len(fallback_after)
    return text[:insert_at] + "\r\n" + anchor + "\r\n" + text[insert_at:]


def corpse_event_insert_offset(text: str) -> Optional[int]:
    """Return the safe insertion point inside the standard @KillMon event.

    A newly unpacked same-engine server may not yet include the historical
    BindType13 corpse system.  The platform's combat-core package creates an
    explicit @KillMon stub for that case.  Putting the managed aggregation
    block immediately after its #ACT keeps generated equipment self-contained
    without borrowing a map, monster, reward item, or any old-server script.
    """
    event = "[@KillMon]"
    event_start = text.find(event)
    if event_start < 0:
        return None
    next_event = text.find("[@", event_start + len(event))
    event_end = len(text) if next_event < 0 else next_event
    action = text.find("#ACT", event_start, event_end)
    if action < 0:
        return None
    line_end = text.find("\n", action, event_end)
    return event_end if line_end < 0 else line_end + 1


def ensure_corpse_anchor(text: str) -> str:
    anchor = "; XY_EQUIP_MAKER_CORPSE_ANCHOR"
    if anchor in text:
        return text
    offset = corpse_event_insert_offset(text)
    if offset is None:
        fallback = ANCHOR_FALLBACKS[anchor]
        pos = text.find(fallback)
        if pos < 0:
            raise EquipMakerError(f"找不到 QFunction 插入锚点，也找不到回退位置：{anchor}")
        insert_at = pos + len(fallback)
        return text[:insert_at] + "\r\n" + anchor + "\r\n" + text[insert_at:]
    bootstrap = (
        "; XY_EQUIP_MAKER_CORPSE_INIT\r\n"
        "MOV N$XY_CorpseRate 0\r\n"
        "; XY_EQUIP_MAKER_CORPSE_ANCHOR\r\n"
    )
    return text[:offset] + bootstrap + text[offset:]


def can_insert_anchor(text: str, anchor: str) -> bool:
    if anchor in text:
        return True
    if anchor in STRICT_EXISTING_ANCHORS:
        return False
    if anchor == "; XY_EQUIP_MAKER_CORPSE_ANCHOR" and corpse_event_insert_offset(text) is not None:
        return True
    if anchor in RUNTIME_REFRESH_ANCHORS and attack_damage_insert_offset(text) is not None:
        return True
    fallback = ANCHOR_FALLBACKS.get(anchor, "")
    return bool(fallback and fallback.strip() in text)


def insert_before_once(text: str, marker: str, fallback_before: str, block: str) -> str:
    if marker in text:
        return text
    pos = text.find(fallback_before)
    if pos < 0:
        raise EquipMakerError(f"找不到 QFunction 插入位置：{marker}")
    return text[:pos] + block.rstrip("\r\n") + "\r\n" + text[pos:]


def insert_after_once(text: str, marker: str, fallback_after: str, block: str) -> str:
    if marker in text:
        return text
    pos = text.find(fallback_after)
    if pos < 0:
        raise EquipMakerError(f"找不到 QFunction 插入位置：{marker}")
    insert_at = pos + len(fallback_after)
    return text[:insert_at] + "\r\n" + block.rstrip("\r\n") + "\r\n" + text[insert_at:]


def ensure_first_tail_kill_framework(text: str) -> str:
    reset_block = (
        "; XY_EQUIP_MAKER_KILL_RESET\r\n"
        "MOV N$XY_FirstKillRate 0\r\n"
        "MOV N$XY_TailKillRate 0\r\n"
    )
    text = insert_after_once(
        text,
        "; XY_EQUIP_MAKER_KILL_RESET",
        "MOV N$XY_PVE_Damage 0\r\n",
        reset_block,
    )

    final_block = (
        "; XY_EQUIP_MAKER_KILL_FINAL\r\n"
        "#IF\r\n"
        "LARGE N$XY_TailKillRate 0\r\n"
        "M.CheckHpPer < <$STR(N$XY_TailKillRate)>\r\n"
        "NOT CHECKTEXTLIST ..\\QuestDiary\\玄渊临时\\XY_尾刀斩杀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX>\r\n"
        "#ACT\r\n"
        "M.AddhpPer -100\r\n"
        "AddTextListEx ..\\QuestDiary\\玄渊临时\\XY_尾刀斩杀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX> 0\r\n"
        "BREAK\r\n"
        "\r\n"
        "#IF\r\n"
        "LARGE N$XY_FirstKillRate 0\r\n"
        "NOT CHECKTEXTLIST ..\\QuestDiary\\玄渊临时\\XY_首刀斩杀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX>\r\n"
        "#ACT\r\n"
        "M.AddhpPer - <$STR(N$XY_FirstKillRate)>\r\n"
        "AddTextListEx ..\\QuestDiary\\玄渊临时\\XY_首刀斩杀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX> 0\r\n"
        "BREAK\r\n"
        "\r\n"
    )
    return insert_before_once(
        text,
        "; XY_EQUIP_MAKER_KILL_FINAL",
        "#IF\r\nLARGE N$XY_PVE_Extra 0\r\n",
        final_block,
    )


ANCHOR_FALLBACKS = {
    "; XY_EQUIP_MAKER_POWER_ANCHOR": "; XY-TEST-RING-001 测试戒：神力+80%、打怪+100%\r\n#IF\r\nCHECKITEMW 测试戒 1\r\n#ACT\r\nINC N$倍攻 80\r\nINC N$XY_PVE 100\r\n",
    "; XY_EQUIP_MAKER_ATTACK_ANCHOR": "; XY-BRACELET-ABC-001 手镯B：打怪伤害+200%，明月式额外伤害出口\r\n#IF\r\nCHECKITEMW 手镯B 1\r\n#ACT\r\nINC N$XY_PVE_Extra 200\r\n",
    "; XY_EQUIP_MAKER_BLAST_ANCHOR": "; XY-BRACELET-ABC-001 手镯C：暴击伤害+200%\r\n#IF\r\nCHECKITEMW 手镯C 1\r\n#ACT\r\nINC N$XY_最终爆伤 200\r\n",
    "; XY_EQUIP_MAKER_DROP_ANCHOR": "INC N$XY_最大爆率 <$STR(N$XY_Bind20Rate)>\r\n",
    "; XY_EQUIP_MAKER_CORPSE_ANCHOR": "GetAllCustomItemValue 13 N$XY_CorpsePoint N$XY_CorpseRate\r\n",
    "; XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR": "[@AttackDamage]\r\n",
    "; XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR": "[@AttackDamage]\r\n",
    "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR": "[@AttackDamage]\r\n",
    "; XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR": "[@AttackDamage]\r\n",
}

RUNTIME_REFRESH_ANCHORS = {
    "; XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR",
    "; XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR",
    "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR",
    "; XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR",
}

STRICT_EXISTING_ANCHORS = {
    "; XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR",
    "; XY_EXECUTION_LAB_CHANCE_ANCHOR",
    "; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR",
    "; XY_EXECUTION_LAB_PVE_BONUS_ANCHOR",
    "; XY_EXECUTION_LAB_PVE_DURATION_ANCHOR",
    "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR",
    "; XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR",
    "; XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR",
}


def attack_damage_insert_offset(text: str) -> Optional[int]:
    event_start = text.lower().find("[@attackdamage]")
    if event_start < 0:
        anchor = "; XY_EQUIP_MAKER_ATTACK_ANCHOR"
        anchor_start = text.find(anchor)
        if anchor_start < 0:
            return None
        line_end = text.find("\n", anchor_start)
        return len(text) if line_end < 0 else line_end + 1
    next_event = text.find("[@", event_start + len("[@AttackDamage]"))
    event_end = len(text) if next_event < 0 else next_event
    action = text.find("#ACT", event_start, event_end)
    if action < 0:
        return None
    line_end = text.find("\n", action, event_end)
    return event_end if line_end < 0 else line_end + 1


def ensure_runtime_refresh_framework(text: str) -> str:
    present = {anchor for anchor in RUNTIME_REFRESH_ANCHORS if anchor in text}
    if present == RUNTIME_REFRESH_ANCHORS:
        return text
    if present:
        raise EquipMakerError("QFunction 的运行时刷新锚点不完整，禁止猜测修补")
    offset = attack_damage_insert_offset(text)
    if offset is None:
        raise EquipMakerError("QFunction 缺少可安全接入的 [@AttackDamage] #ACT")
    block = (
        "; XY_EQUIP_MAKER_RUNTIME_REFRESH_BEGIN\r\n"
        "MOV N$XY_RT_Power 100\r\n"
        "MOV N$XY_RT_Blast 100\r\n"
        "MOV N$XY_RT_Drop 100\r\n"
        "MOV N$XY_RT_DropMax 100\r\n"
        "; XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR\r\n"
        "; XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR\r\n"
        "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\r\n"
        "; XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR\r\n"
        "#IF\r\n"
        "#ACT\r\n"
        "MOV N$XY_RT_DropFinal 100\r\n"
        "CalcPercent <$STR(N$XY_RT_Drop)> <$STR(N$XY_RT_DropMax)> N$XY_RT_DropFinal\r\n"
        "#IF\r\n"
        "#ACT\r\n"
        "POWERRATE <$STR(N$XY_RT_Power)> 0 0 1 0\r\n"
        "SetBlastHitRate <$STR(N$XY_RT_Blast)> 0\r\n"
        "KILLMONBURSTRATE <$STR(N$XY_RT_DropFinal)>\r\n"
        "; XY_EQUIP_MAKER_RUNTIME_REFRESH_END\r\n"
    )
    return text[:offset] + block + text[offset:]

DISPLAY_ANCHOR = "; XY_EQUIP_MAKER_DISPLAY_ANCHOR"
DISPLAY_EFFECT_BIND_TYPES = {13, 14, 20, 21, 22, 24, 25, 27, 31}

EXECUTION_PANEL_SPECS = {
    "处决概率": (
        "; XY_EQUIP_MAKER_PANEL_EXEC_CHANCE_ANCHOR",
        "; XY-EQUIPMENT-WASH-UI-END TEXT47_EXEC_CHANCE",
        "处决概率",
        "N$XY_UI_C_Value02",
        "%",
    ),
    "处决倍率": (
        "; XY_EQUIP_MAKER_PANEL_EXEC_BONUS_ANCHOR",
        "; XY-EQUIPMENT-WASH-UI-END TEXT49_EXEC_DAMAGE",
        "PVE处决额外伤害",
        "N$XY_UI_C_Value04",
        "%",
    ),
    "处决时间": (
        "; XY_EQUIP_MAKER_PANEL_EXEC_DURATION_ANCHOR",
        "; XY-EQUIPMENT-WASH-UI-END TEXT48_EXEC_TIME",
        "PVE处决持续时间",
        "N$XY_UI_C_Value03",
        "秒",
    ),
}


def execution_panel_block_marker(spec: EquipmentSpec, key: str) -> str:
    _anchor, _fallback, label, _variable, suffix = EXECUTION_PANEL_SPECS[key]
    return f"; XY-ATTR-PANEL {effect_subject_name(spec)}: {label}+{spec.script_attrs[key]}{suffix}"


def ensure_execution_panel_anchor(text: str, key: str) -> str:
    anchor, fallback, _label, _variable, _suffix = EXECUTION_PANEL_SPECS[key]
    if text.count(anchor) == 1:
        return text
    if text.count(anchor) > 1:
        raise EquipMakerError(f"属性图标处决锚点重复：{anchor}")
    if text.count(fallback) != 1:
        raise EquipMakerError(f"属性图标缺少唯一洗练汇总锚点：{fallback}")
    line_end = text.find("\n", text.find(fallback))
    insert_at = len(text) if line_end < 0 else line_end + 1
    return text[:insert_at] + anchor + "\r\n" + text[insert_at:]


def build_execution_panel_block(spec: EquipmentSpec, key: str) -> str:
    _anchor, _fallback, _label, variable, _suffix = EXECUTION_PANEL_SPECS[key]
    condition = effect_condition_line(spec)
    return "\r\n".join([
        "",
        execution_panel_block_marker(spec, key),
        "#IF",
        condition,
        "#ACT",
        f"INC {variable} {spec.script_attrs[key]}",
    ])


def script_display_entries(spec: EquipmentSpec, prop_registry: dict) -> List[Tuple[str, int, dict]]:
    """Return validated, display-only M2 custom-property bindings for a spec."""
    entries: List[Tuple[str, int, dict]] = []
    properties = prop_registry.get("properties", {})
    for key, value in spec.script_attrs.items():
        meta = properties.get(key)
        if meta is None:
            raise EquipMakerError(f"未注册脚本属性：{key}。请先在 script_properties.json 添加接口。")
        if "minimum" in meta and value < int(meta["minimum"]):
            raise EquipMakerError(f"脚本属性 {key} 不能小于 {int(meta['minimum'])}：{value}")
        if "maximum" in meta and value > int(meta["maximum"]):
            raise EquipMakerError(f"脚本属性 {key} 不能大于 {int(meta['maximum'])}：{value}")
        display = meta.get("display")
        if not isinstance(display, dict):
            raise EquipMakerError(f"脚本属性缺少 M2 显示映射：{key}")
        if display.get("mode") == "item_desc_only":
            # Properties explicitly registered as ItemDesc-only do not consume
            # a custom equipment display slot.
            continue
        try:
            bind_type = int(display["bind_type"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EquipMakerError(f"脚本属性 M2 显示映射无效：{key}") from exc
        if not 40 <= bind_type <= 60:
            raise EquipMakerError(f"脚本属性 M2 显示 BindType 必须在 40-60：{key}={bind_type}")
        if bind_type in DISPLAY_EFFECT_BIND_TYPES:
            raise EquipMakerError(f"脚本属性 M2 显示 BindType 与实效链冲突：{key}={bind_type}")
        entries.append((key, value, display))
    if len(entries) > 9:
        raise EquipMakerError(f"单件装备脚本属性超过 M2 可显示上限 9 条：{spec.name}")
    return entries


def addbag_event_insert_offset(text: str) -> Optional[int]:
    event = "[@AddBag]"
    event_start = text.find(event)
    if event_start < 0:
        return None
    next_event = text.find("[@", event_start + len(event))
    event_end = len(text) if next_event < 0 else next_event
    action = text.find("#ACT", event_start, event_end)
    if action < 0:
        raise EquipMakerError("QFunction 的 [@AddBag] 缺少唯一 #ACT，无法安全接入装备显示")
    line_end = text.find("\n", action, event_end)
    return event_end if line_end < 0 else line_end + 1


def ensure_addbag_display_anchor(text: str) -> str:
    if DISPLAY_ANCHOR in text:
        return text
    offset = addbag_event_insert_offset(text)
    if offset is None:
        suffix = "" if text.endswith(("\n", "\r")) else "\r\n"
        return (
            text + suffix
            + "; XY_EQUIP_MAKER_DISPLAY_EVENT\r\n"
            + "[@AddBag]\r\n#IF\r\n#ACT\r\n"
            + DISPLAY_ANCHOR + "\r\n"
            + "BREAK\r\n"
        )
    return text[:offset] + DISPLAY_ANCHOR + "\r\n" + text[offset:]


def display_block_marker(spec: EquipmentSpec) -> str:
    return f"; XY-EQUIP-MAKER-DISPLAY {spec.name}"


def build_addbag_display_block(spec: EquipmentSpec, prop_registry: dict) -> str:
    if spec.slot == TITLE_SCROLL_SLOT:
        # 称号属性由 fenghao.dat 与称号本体显示，卷轴不写装备实例自定义属性。
        return ""
    entries = script_display_entries(spec, prop_registry)
    if not entries:
        return ""
    lines = [
        "",
        display_block_marker(spec),
        "#IF",
        f"EQUAL <$CURITEMNAME> {spec.name}",
        "#ACT",
        "LINKPICKUPITEM",
    ]
    for index in range(10):
        lines.append(f"GetCustomItemAbil -1 {index} 1 N$XY_EQUIP_MAKER_DisplayBind{index}")
    lines.append("#IF")
    lines.extend(f"EQUAL N$XY_EQUIP_MAKER_DisplayBind{index} 0" for index in range(10))
    lines.append("#ACT")
    for index, (_key, value, display) in enumerate(entries):
        color = int(display.get("color", 251))
        bind_type = int(display["bind_type"])
        percent = 1 if bool(display.get("percent", False)) else 0
        lines.extend([
            f"SetCustomItemAbil -1 {index} 0 {color}",
            f"SetCustomItemAbil -1 {index} 1 {bind_type}",
            f"SetCustomItemAbil -1 {index} 2 {int(display.get('textvar_line', index))}",
            f"SetCustomItemAbil -1 {index} 3 {percent}",
        ])
        if display.get("mode") == "textvar_value_ex":
            textvar_line = int(display.get("textvar_line", 0))
            if textvar_line <= 0:
                raise EquipMakerError(f"脚本属性TextVar显示行无效：{_key}")
            lines.extend([
                f"SetCustomItemAbil -1 {index} 4 9",
                f"SetCustomItemValueEx -1 {index} = {textvar_line} {value} 0",
            ])
        else:
            lines.append(f"SetCustomItemValue -1 {index} = {value}")
    lines.extend(["UpdateItem -1", "ClearLinkItem", "BREAK", "#IF", "#ACT", "ClearLinkItem", "BREAK"])
    return "\r\n".join(lines)


def outlet_target(outlet: dict) -> str:
    target = str(outlet.get("target", "qfunction")).strip().lower()
    if target not in {"qfunction", "qmanage"}:
        raise EquipMakerError(f"脚本属性出口目标无效：{target}")
    return target


def required_script_anchors_by_target(
    spec: EquipmentSpec,
    prop_registry: dict,
) -> Dict[str, List[str]]:
    required: Dict[str, List[str]] = {}
    properties = prop_registry.get("properties", {})
    for key in spec.script_attrs:
        if key not in properties:
            raise EquipMakerError(f"未注册脚本属性：{key}。请先在 script_properties.json 添加接口。")
        for outlet in properties[key].get("outlets", []):
            anchor = str(outlet["anchor"])
            target = outlet_target(outlet)
            required.setdefault(target, [])
            if anchor not in required[target]:
                required[target].append(anchor)
    return required


def required_script_anchors(spec: EquipmentSpec, prop_registry: dict) -> List[str]:
    """Backward-compatible flattened view used by older contract checks."""
    required: List[str] = []
    for anchors in required_script_anchors_by_target(spec, prop_registry).values():
        for anchor in anchors:
            if anchor not in required:
                required.append(anchor)
    return required


def _script_path(target: str) -> Path:
    if target == "qfunction":
        return QFUNCTION
    if target == "qmanage":
        return QMANAGE
    if target == "attribute_panel":
        return ATTRIBUTE_PANEL
    raise EquipMakerError(f"未知脚本目标：{target}")


def _script_label(target: str) -> str:
    return {
        "qfunction": "QFunction",
        "qmanage": "QManage",
        "attribute_panel": "属性图标",
    }.get(target, target)


def title_scroll_block_marker(spec: EquipmentSpec) -> str:
    return f"; XY-EQUIP-MAKER-TITLE-SCROLL {spec.name}"


def build_title_scroll_trigger_block(spec: EquipmentSpec) -> str:
    if spec.slot != TITLE_SCROLL_SLOT:
        return ""
    trigger = int(spec.fields.get("Anicount", 0) or 0)
    if not 1 <= trigger <= 255:
        raise EquipMakerError(f"称号卷触发编号无效：{trigger}")
    return "\r\n".join([
        "",
        title_scroll_block_marker(spec),
        f"[@StdModeFunc{trigger}]",
        "#IF",
        f"NOT CHECKFENGHAO {spec.title_name}",
        "#ACT",
        f"GIVEFENGHAO {spec.title_name}",
        f"MESSAGEBOX 恭喜你获得称号“{spec.title_name}”。",
        "BREAK",
        "",
        "#IF",
        "#ACT",
        f"GIVE {spec.name} 1",
        f"MESSAGEBOX 你已经拥有称号“{spec.title_name}”，称号卷已放回背包。",
        "BREAK",
    ])


def build_script_texts(
    spec: EquipmentSpec,
    prop_registry: dict,
    allow_existing_effect_branch: bool = False,
) -> Dict[str, str]:
    if not spec.script_attrs and spec.slot != TITLE_SCROLL_SLOT:
        return {}
    required_by_target = required_script_anchors_by_target(spec, prop_registry)
    panel_keys = [key for key in EXECUTION_PANEL_SPECS if key in spec.script_attrs]
    targets = {"qfunction", *required_by_target}
    if panel_keys:
        targets.add("attribute_panel")
    texts = {target: read_text_auto(_script_path(target)) for target in targets}
    properties = prop_registry.get("properties", {})
    for key in spec.script_attrs:
        meta = properties.get(key, {})
        for requirement in meta.get("requires", []):
            target = str(requirement.get("target", "qfunction")).strip().lower()
            package = str(requirement.get("package", "")).strip()
            marker = str(requirement.get("marker", "")).strip()
            if target not in texts:
                raise EquipMakerError(f"脚本属性 {key} 缺少依赖目标：{target}")
            if not marker or texts[target].count(marker) != 1:
                raise EquipMakerError(
                    f"脚本属性 {key} 依赖成果包 {package or '未命名包'}；"
                    f"目标服尚未安装或受管标记冲突：{marker or '未配置标记'}；"
                    "请继续使用09_装备批量生成.xlsx，无需改用依赖配置表，先部署上述成果包后再预检。"
                )
            if marker.endswith("-BEGIN"):
                end_marker = marker[:-6] + "-END"
                if texts[target].count(end_marker) != 1:
                    raise EquipMakerError(
                        f"脚本属性 {key} 依赖成果包 {package or '未命名包'}的受管块残缺：{end_marker}"
                    )
    if f"EQUAL <$CurItemName> {spec.name}" in texts["qfunction"]:
        raise EquipMakerError(f"QFunction 已存在禁止路线 CurItemName 分支，已停止：{spec.name}")
    condition_line = effect_condition_line(spec)
    has_existing_effect_branch = any(condition_line in text for text in texts.values())
    if has_existing_effect_branch and not allow_existing_effect_branch:
        raise EquipMakerError(f"脚本文件已存在同名 {condition_line} 分支，已停止：{effect_subject_name(spec)}")

    props = prop_registry.get("properties", {})
    display_block = build_addbag_display_block(spec, prop_registry)
    if not has_existing_effect_branch:
        for target, anchors in required_by_target.items():
            for anchor in anchors:
                texts[target] = ensure_anchor(
                    texts[target], anchor, ANCHOR_FALLBACKS.get(anchor, "")
                )
        if any(key in spec.script_attrs for key in ("首刀斩杀", "尾刀斩杀")):
            texts["qfunction"] = ensure_first_tail_kill_framework(texts["qfunction"])

        additions_by_target: Dict[str, Dict[str, List[str]]] = {}
        generated_blocks: List[str] = []
        subject = effect_subject_name(spec)
        for key, value in spec.script_attrs.items():
            if key not in props:
                raise EquipMakerError(f"未注册脚本属性：{key}。请先在 script_properties.json 添加接口。")
            for outlet in props[key].get("outlets", []):
                target = outlet_target(outlet)
                anchor = outlet["anchor"]
                lines = []
                for source_line in outlet.get("block", []):
                    line = source_line.format(item=subject, value=value)
                    if line == f"CHECKITEMW {subject} 1":
                        line = condition_line
                    lines.append(line)
                block_text = "\r\n".join(lines)
                generated_blocks.append(block_text)
                additions_by_target.setdefault(target, {}).setdefault(anchor, []).append(block_text)

        for block in generated_blocks:
            for bad in ("N$??", "N$XY_????", f"EQUAL <$CurItemName> {spec.name}", "DELAYGOTO @XY_ShowAttrIcon"):
                if bad in block:
                    raise EquipMakerError(f"新生成分支命中禁止项 {bad}，已停止写入。")

        for target, additions_by_anchor in additions_by_target.items():
            for anchor, blocks in additions_by_anchor.items():
                marker = anchor + "\r\n"
                pos = texts[target].find(marker)
                if pos < 0:
                    raise EquipMakerError(f"{_script_label(target)} 锚点不存在：{anchor}")
                insert_at = pos + len(marker)
                texts[target] = (
                    texts[target][:insert_at]
                    + "\r\n".join(blocks)
                    + "\r\n"
                    + texts[target][insert_at:]
                )

    if panel_keys:
        for key in panel_keys:
            texts["attribute_panel"] = ensure_execution_panel_anchor(texts["attribute_panel"], key)
            anchor = EXECUTION_PANEL_SPECS[key][0]
            block = build_execution_panel_block(spec, key)
            marker = execution_panel_block_marker(spec, key)
            if marker in texts["attribute_panel"]:
                continue
            anchor_line = anchor + "\r\n"
            pos = texts["attribute_panel"].find(anchor_line)
            if pos < 0:
                raise EquipMakerError(f"属性图标锚点不存在：{anchor}")
            insert_at = pos + len(anchor_line)
            texts["attribute_panel"] = (
                texts["attribute_panel"][:insert_at]
                + block
                + "\r\n"
                + texts["attribute_panel"][insert_at:]
            )

    if display_block and display_block_marker(spec) not in texts["qfunction"]:
        texts["qfunction"] = ensure_addbag_display_anchor(texts["qfunction"])
        marker = DISPLAY_ANCHOR + "\r\n"
        pos = texts["qfunction"].find(marker)
        if pos < 0:
            raise EquipMakerError("M2 装备显示锚点不存在")
        insert_at = pos + len(marker)
        texts["qfunction"] = (
            texts["qfunction"][:insert_at]
            + display_block
            + "\r\n"
            + texts["qfunction"][insert_at:]
        )

    title_block = build_title_scroll_trigger_block(spec)
    if title_block and title_scroll_block_marker(spec) not in texts["qfunction"]:
        suffix = "" if texts["qfunction"].endswith(("\n", "\r")) else "\r\n"
        texts["qfunction"] += suffix + title_block + "\r\n"

    return texts


def build_qfunction_text(
    spec: EquipmentSpec,
    prop_registry: dict,
    allow_existing_effect_branch: bool = False,
) -> Optional[str]:
    texts = build_script_texts(spec, prop_registry, allow_existing_effect_branch)
    return texts.get("qfunction")


def write_script_texts(texts: Dict[str, str]) -> None:
    for target, text in texts.items():
        write_mir_text(_script_path(target), text)



def patch_qfunction(spec: EquipmentSpec, prop_registry: dict) -> None:
    write_script_texts(build_script_texts(spec, prop_registry))


def update_stditem(spec: EquipmentSpec) -> int:
    conn = connect_db()
    try:
        row = get_item(conn, spec.name)
        if row is None:
            raise EquipMakerError(f"装备名不存在，无法修改：{spec.name}")
        idx = int(row["Idx"])
        if not spec.fields:
            return idx
        cols = table_columns(conn)
        assignments = []
        values = []
        for key, value in spec.fields.items():
            if key in cols:
                assignments.append(f"{key}=?")
                values.append(value)
        if assignments:
            values.append(idx)
            conn.execute(f"UPDATE StdItems SET {', '.join(assignments)} WHERE Idx=?", values)
            conn.commit()
        return idx
    finally:
        conn.close()


def preflight(spec: EquipmentSpec, prop_registry: dict) -> None:
    qf_text = read_text_auto(QFUNCTION)
    if spec.slot not in SPECIAL_SCRIPT_SLOTS:
        spec.fields["DuraMax"] = 60000
    conn = connect_db()
    try:
        if get_item(conn, spec.name):
            raise EquipMakerError(f"装备名已存在，已停止：{spec.name}")
        prepare_special_allocations(spec, conn, qf_text)
        resolve_template_in_connection(spec, conn)
    finally:
        conn.close()

    desc_text = read_text_auto(ITEM_DESC)
    if any(ln.startswith(spec.name + "=") for ln in desc_text.splitlines()):
        raise EquipMakerError(f"ItemDescList 已存在同名显示行，已停止：{spec.name}")

    if spec.slot == TITLE_SCROLL_SLOT:
        if any(line.startswith(spec.title_name + "=") for line in desc_text.splitlines()):
            raise EquipMakerError(f"ItemDescList 已存在同名称号显示行，已停止：{spec.title_name}")
        if FENGHAO_DATA is None:
            raise EquipMakerError("称号卷必须选择客户端 data 目录。")
        if not FENGHAO_DATA.is_file():
            raise EquipMakerError(f"客户端称号说明文件不存在：{FENGHAO_DATA}")
        title_text = read_text_auto(FENGHAO_DATA)
        if any(line.startswith(spec.title_name + "=") for line in title_text.splitlines()):
            raise EquipMakerError(f"fenghao.dat 已存在同名称号说明，已停止：{spec.title_name}")
        label = f"[@StdModeFunc{int(spec.fields.get('Anicount', 0))}]"
        if label.lower() in qf_text.lower():
            raise EquipMakerError(f"称号卷触发标签已被占用：{label}")
    condition_line = effect_condition_line(spec)
    if condition_line in qf_text:
        raise EquipMakerError(f"QFunction 已存在同名 {condition_line} 分支，已停止：{effect_subject_name(spec)}")
    if f"EQUAL <$CurItemName> {spec.name}" in qf_text:
        raise EquipMakerError(f"QFunction 已存在禁止路线 CurItemName 分支，已停止：{spec.name}")

    props = prop_registry.get("properties", {})
    required_by_target = required_script_anchors_by_target(spec, prop_registry)
    script_display_entries(spec, prop_registry)

    preflight_icon_source(spec)

    texts = {"qfunction": qf_text}
    for target in required_by_target:
        if target != "qfunction":
            path = _script_path(target)
            if not path.exists():
                raise EquipMakerError(f"{_script_label(target)} 脚本文件不存在：{path}")
            texts[target] = read_text_auto(path)
        if condition_line in texts[target]:
            raise EquipMakerError(
                f"{_script_label(target)} 已存在同名 {condition_line} 分支，已停止：{effect_subject_name(spec)}"
            )
    for target, anchors in required_by_target.items():
        for anchor in anchors:
            if not can_insert_anchor(texts[target], anchor):
                raise EquipMakerError(
                    f"{_script_label(target)} 缺少锚点和回退位置：{anchor}"
                )


def make_equipment(txt_path: Path) -> str:
    registry = load_script_props()
    spec = parse_spec(txt_path)
    preflight(spec, registry)
    script_texts = build_script_texts(spec, registry)
    icon_message = reuse_static_icon_source(spec)
    server_backup_dir = make_generation_backup(spec)
    idx = insert_title_scroll_bundle(spec) if spec.slot == TITLE_SCROLL_SLOT else insert_stditem(spec)
    try:
        append_item_desc(spec, registry)
        append_title_metadata(spec, registry)
        patch_fixed_tables(spec)
        write_script_texts(script_texts)
    except Exception:
        # 已创建备份，但 V1 不自动回滚，防止隐藏半成品状态。
        raise
    log_path = write_generation_log(spec, idx, str(server_backup_dir))
    suffix = f"\n{icon_message}" if icon_message else ""
    title_note = (
        f"\n称号本体={spec.title_name}，Idx={spec.title_idx}，Shape={spec.title_shape}，"
        f"触发=@StdModeFunc{spec.fields.get('Anicount')}"
        if spec.slot == TITLE_SCROLL_SLOT else ""
    )
    effect_note = "背包持有即生效（CHECKITEM）" if spec.slot == BACKPACK_ARTIFACT_SLOT else ""
    return "".join([
        f"生成成功：{spec.name}，Idx={idx}，Looks={spec.fields.get('Looks', '')}",
        title_note,
        f"\n{effect_note}" if effect_note else "",
        f"\n服务端备份={server_backup_dir}",
        f"\n生成日志={log_path}",
        f"\nGM测试命令：@make {spec.name} 1",
        "\n提示：完整重启 M2，并关闭重开客户端/登录器后再验证图标。",
        suffix,
    ])


def validate_material_spec(spec: EquipmentSpec) -> None:
    expected = {
        "StdMode": 46,
        "Shape": 1,
        "DuraMax": 99999,
        "OverLap": 2,
    }
    if spec.slot != "材料":
        raise EquipMakerError(f"材料源表部位必须固定为材料：{spec.name}")
    for field_name, value in expected.items():
        if int(spec.fields.get(field_name, -1)) != value:
            raise EquipMakerError(
                f"{spec.name} 材料固定字段错误：{field_name}="
                f"{spec.fields.get(field_name)}，期望 {value}"
            )
    if spec.script_attrs or spec.fixed_attrs or spec.desc_attrs:
        raise EquipMakerError(f"材料不得进入装备脚本属性或固定属性链：{spec.name}")
    if not spec.icon_source:
        raise EquipMakerError(f"材料必须填写来源编号：{spec.name}")


def preflight_material(spec: EquipmentSpec) -> None:
    validate_material_spec(spec)
    conn = connect_db()
    try:
        if get_item(conn, spec.name):
            raise EquipMakerError(f"材料名已存在，已停止：{spec.name}")
        resolve_template_in_connection(spec, conn)
    finally:
        conn.close()
    preflight_icon_source(spec, MATERIAL_ICON_LIBRARIES)


def check_material(txt_path: Path) -> str:
    spec = parse_spec(txt_path)
    preflight_material(spec)
    validate_template_exists(spec)
    base = spec.base_template_label or spec.template or "未解析"
    return (
        f"检查通过：{spec.name}，类型=材料，最大叠加=99999，"
        f"基础母版={base}，图标来源=#{spec.icon_source['source_id']}"
    )


def make_material(txt_path: Path) -> str:
    spec = parse_spec(txt_path)
    preflight_material(spec)
    icon_message = apply_static_icon_source(
        spec,
        register_resource=False,
        libraries=MATERIAL_ICON_LIBRARIES,
    )
    server_backup_dir = make_generation_backup(spec)
    idx = insert_stditem(spec)
    log_path = write_generation_log(spec, idx, str(server_backup_dir))
    return (
        f"材料生成成功：{spec.name}，Idx={idx}，Looks={spec.fields.get('Looks', '')}"
        f"\n最大叠加=99999，StdMode=46，OverLap=2"
        f"\n生成日志={log_path}"
        f"\nGM测试命令：@make {spec.name} 99999"
        f"\n{icon_message}"
    )


def update_equipment(txt_path: Path) -> str:
    registry = load_script_props()
    spec = parse_spec(txt_path)
    if spec.slot in SPECIAL_SCRIPT_SLOTS:
        raise EquipMakerError(f"修改模式暂不处理{spec.slot}；请使用生成入口创建，避免拆散其脚本契约。")
    validate_template_exists(spec)
    if spec.script_attrs:
        script_texts = build_script_texts(spec, registry, allow_existing_effect_branch=True)
    else:
        script_texts = {}
    server_backup_dir = make_generation_backup(spec)
    idx = update_stditem(spec)
    replace_item_desc(spec, registry)
    patch_fixed_tables(spec)
    write_script_texts(script_texts)
    log_path = write_generation_log(spec, idx, str(server_backup_dir))
    script_note = ""
    if spec.script_attrs and not script_texts:
        script_note = "\n提示：检测到同名 QFunction 脚本分支，修改模式未自动覆盖旧脚本分支。"
    return (
        f"修改成功：{spec.name}，Idx={idx}，Looks={spec.fields.get('Looks', '')}"
        f"\n服务端备份={server_backup_dir}"
        f"\n修改日志={log_path}"
        f"{script_note}"
        f"\n提示：修改模式不会自动重新导入图标；如需换图，请用生成/专门图标任务处理。"
    )


def check_equipment(txt_path: Path) -> str:
    registry = load_script_props()
    spec = parse_spec(txt_path)
    preflight(spec, registry)
    validate_template_exists(spec)
    attrs = ", ".join(f"{k}+{v}" for k, v in spec.script_attrs.items()) or "无"
    icon = ""
    if spec.icon_source:
        icon = f"，图标来源={spec.icon_source['source_wzl']}#{spec.icon_source['source_id']}"
    base = spec.base_template_label or spec.template or "未解析"
    special = ""
    if spec.slot == BACKPACK_ARTIFACT_SLOT:
        special = "，实效条件=背包持有(CHECKITEM)"
    elif spec.slot == TITLE_SCROLL_SLOT:
        special = (
            f"，称号={spec.title_name}，触发=@StdModeFunc{spec.fields.get('Anicount')}，"
            f"称号Shape={spec.title_shape}"
        )
    return f"检查通过：{spec.name}，部位={spec.slot or '未填'}，基础母版={base}，脚本属性={attrs}{special}{icon}"


def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title("玄渊做装备")
    root.geometry("760x520")

    path_var = tk.StringVar()

    def choose_file() -> None:
        path = filedialog.askopenfilename(
            title="选择装备TXT",
            initialdir=str(TOOL_DIR / "input"),
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            path_var.set(path)

    def generate() -> None:
        log.delete("1.0", tk.END)
        p = Path(path_var.get().strip())
        if not p.exists():
            messagebox.showerror("错误", "请选择存在的装备TXT。")
            return
        try:
            result = make_equipment(p)
            log.insert(tk.END, result + "\n")
            messagebox.showinfo("完成", result)
        except Exception as exc:
            log.insert(tk.END, "生成失败：\n")
            log.insert(tk.END, str(exc) + "\n\n")
            log.insert(tk.END, traceback.format_exc())
            messagebox.showerror("生成失败", str(exc))

    top = tk.Frame(root)
    top.pack(fill=tk.X, padx=10, pady=10)
    tk.Label(top, text="装备TXT：").pack(side=tk.LEFT)
    tk.Entry(top, textvariable=path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Button(top, text="选择", command=choose_file).pack(side=tk.LEFT, padx=4)
    tk.Button(top, text="直接生成", command=generate).pack(side=tk.LEFT, padx=4)

    hint = (
        "规则：同名装备存在会直接报错；图标导入失败会停止写DB。\n"
        "生成时会备份DB/ItemDesc/QFunction，并写入 output\\generation_*.json；"
        "自动图标会同步校验 WZX count 与 WZL header count；"
        "扩展接口：修改 script_properties.json 可增加新脚本属性。"
    )
    tk.Label(root, text=hint, justify=tk.LEFT, fg="#444").pack(fill=tk.X, padx=10)

    log = scrolledtext.ScrolledText(root, wrap=tk.WORD)
    log.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    root.mainloop()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="玄渊做装备工具")
    parser.add_argument("txt", nargs="?", help="装备TXT路径")
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    parser.add_argument("--check", action="store_true", help="只检查TXT和重复名，不写入")
    args = parser.parse_args(argv)

    if args.gui or not args.txt:
        return run_gui()
    if args.check:
        print(check_equipment(Path(args.txt)))
        return 0
    print(make_equipment(Path(args.txt)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
