"""表格驱动的翎风命格原生多色离线候选生成器。

本模块只把结构化 XLSX 编译为可审核脚本文本和证据 JSON；它没有服务端、
客户端、数据库或旧 image_gradient 资源流水线的写入入口。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFINITION_SHEET = "候选定义"
SEGMENT_SHEET = "显示片段"
DEFINITION_HEADERS = (
    "候选ID",
    "启用",
    "目标装备名称",
    "装备位置",
    "写真实属性",
    "属性行",
    "属性颜色",
    "属性绑定",
    "属性位置",
    "属性模式",
    "属性百分比类型",
    "属性值1",
    "属性值2",
    "属性值3",
    "默认文字颜色",
    "备注",
)
SEGMENT_HEADERS = (
    "候选ID",
    "顺序",
    "片段角色",
    "片段文字",
    "颜色",
    "启用",
    "备注",
)
V2_DEFINITION_HEADERS = (
    "候选ID", "启用", "目标装备名称", "中文具体部位", "命格名称", "默认文字颜色", "备注", "使用说明",
)
V2_PROPERTY_HEADERS = ("候选ID", "顺序", "中文属性", "属性值", "启用", "备注", "使用说明")
V2_SEGMENT_HEADERS = (
    "候选ID", "顺序", "片段角色", "来源属性", "片段文字", "颜色", "启用", "备注", "使用说明",
)
V2_PART_HELP_HEADERS = ("中文具体部位", "支持状态", "说明")
V2_PROPERTY_HELP_HEADERS = ("中文属性", "实效状态", "单位", "说明")
V2_SHEETS = ("候选定义", "自定义属性", "显示片段", "部位说明", "属性说明")
V3_DEFINITION_HEADERS = (
    "候选ID", "启用", "目标装备名称", "中文具体部位", "命格名称", "颜色方案ID", "备注", "使用说明",
)
V3_PROPERTY_HEADERS = V2_PROPERTY_HEADERS
V3_SEGMENT_HEADERS = (
    "候选ID", "顺序", "片段角色", "来源属性", "片段文字", "启用", "备注", "使用说明",
)
V3_COLOR_HEADERS = (
    "方案ID", "中文名称", "类型", "统一色号", "命格名称色", "属性名称色", "正负号色", "属性值色", "单位色", "固定文字色", "备注", "使用说明",
)
V3_PART_HELP_HEADERS = V2_PART_HELP_HEADERS
V3_PROPERTY_HELP_HEADERS = V2_PROPERTY_HELP_HEADERS
V3_SHEETS = ("候选定义", "自定义属性", "显示片段", "颜色方案", "部位说明", "属性说明")
SIMPLE_CONFIG_HEADERS = (
    "启用", "目标装备", "部位", "命格名称", "颜色",
    "属性1", "数值1", "属性2", "数值2", "属性3", "数值3",
)
SIMPLE_DICTIONARY_HEADERS = ("中文属性", "单位", "中文部位", "颜色")
SIMPLE_SHEETS = ("命格配置", "数据字典")
ALLOWED_ROLES = {"命格名称", "属性名称", "数值", "单位", "固定文字"}
V2_ALLOWED_ROLES = {"命格名称", "属性名称", "正负号", "属性值", "单位", "固定文字"}
V3_COLOR_ROLES = ("命格名称", "属性名称", "正负号", "属性值", "单位", "固定文字")
FORBIDDEN_TEXT = set(" {}|\\^<>\t\r\n")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
SAFE_PROPERTY_ROW_START = 17
SAFE_PROPERTY_ROW_END = 19
DEFAULT_PROPERTY_COLOR = 250
DEFAULT_PROPERTY_MODE = 0
DEFAULT_PROPERTY_PERCENT_TYPE = 9

# V2 只接受09号表已明确为单槽的中文部位；范围名和左右不明名称不在此表。
TRUSTED_EQUIP_SLOTS = {
    "衣服": 0, "武器": 1, "照明物": 2, "勋章": 2, "项链": 3, "头盔": 4,
    "左手镯": 5, "右手镯": 6, "左戒指": 7, "右戒指": 8, "护身符": 9,
    "腰带": 10, "鞋子": 11, "宝石": 12, "斗笠": 13, "军鼓": 14, "马牌": 15,
    "盾牌": 16, "灵玉": 17, "时装衣服": 18, "时装武器": 19, "时装项链": 20,
    "时装头盔": 21, "时装左手镯": 22, "时装右手镯": 23,
    "时装左戒指": 24, "时装右戒指": 25, "时装勋章": 26, "时装腰带": 27,
    "时装鞋子": 28, "时装宝石": 29,
    **{f"首饰盒{number}": 29 + number for number in range(1, 7)},
    **{f"生肖{number}": 39 + number for number in range(1, 13)},
    **{f"时装首饰盒{number}": 69 + number for number in range(1, 7)},
    **{f"时装生肖{number}": 79 + number for number in range(1, 13)},
}
TRUSTED_EQUIP_SLOTS.update({
    "男衣服": 0, "女衣服": 0, "盔甲": 0, "护符": 9, "靴子": 11, "面巾": 13,
    "时装男衣服": 18, "时装女衣服": 18, "时装盔甲": 18, "时装靴子": 28,
})
for _number in range(1, 7):
    TRUSTED_EQUIP_SLOTS[f"普通首饰盒{_number}"] = 29 + _number
for _number in range(1, 13):
    TRUSTED_EQUIP_SLOTS[f"生肖盒{_number}"] = 39 + _number
    TRUSTED_EQUIP_SLOTS[f"普通生肖{_number}"] = 39 + _number
    TRUSTED_EQUIP_SLOTS[f"普通生肖盒{_number}"] = 39 + _number
    TRUSTED_EQUIP_SLOTS[f"时装生肖盒{_number}"] = 79 + _number
AMBIGUOUS_EQUIP_PARTS = {"手镯", "戒指", "时装手镯", "时装戒指", "首饰盒", "生肖", "时装首饰盒", "时装生肖"}


@dataclass(frozen=True)
class _PropertySpec:
    canonical_key: str
    binding: int
    unit: str
    effect_status: str
    color: int
    type3: int
    type4: int | None
    value_command: str
    dependency: str | None = None
    route: str = "static_only"
    text_line: int | None = None


def _direct_property_spec(canonical_key: str, binding: int) -> _PropertySpec:
    status = "引擎直接属性（已游戏实测）" if binding == 1 else "官方扩展口径静态候选待实测"
    return _PropertySpec(
        canonical_key, binding, "", status, DEFAULT_PROPERTY_COLOR,
        DEFAULT_PROPERTY_MODE, DEFAULT_PROPERTY_PERCENT_TYPE, "value_ex",
        route="direct",
    )


DIRECT_PROPERTY_SPECS = {
    "防御": _direct_property_spec("defence", 1), "自身防御": _direct_property_spec("defence", 1),
    "自定魔防": _direct_property_spec("custom_magic_defence", 2),
    "攻击": _direct_property_spec("attack", 3), "自身攻击": _direct_property_spec("attack", 3),
    "魔法": _direct_property_spec("magic", 4), "自身魔法": _direct_property_spec("magic", 4),
    "道术": _direct_property_spec("tao", 5), "自身道术": _direct_property_spec("tao", 5),
    "HP": _direct_property_spec("hp", 6), "生命值": _direct_property_spec("hp", 6),
    "MP": _direct_property_spec("mp", 7), "魔法值": _direct_property_spec("mp", 7),
}
SCRIPT_PROPERTY_SPECS = {
    name: _PropertySpec(
        key, binding, unit, "依赖09号QFunction/QManage实效出口", 251,
        int(percent), None, "value", "09号QFunction/QManage实效出口",
        route="script_bind",
    )
    for name, key, binding, unit, percent in (
        ("神力倍攻", "power", 40, "%", True), ("打怪伤害", "pve_damage", 41, "%", True), ("暴击伤害", "critical_damage", 42, "%", True),
        ("固定切割", "fixed_cut", 43, "", False), ("爆率", "drop_rate", 44, "%", True), ("最大爆率", "max_drop_rate", 45, "%", True),
        ("首刀斩杀", "first_hit_kill", 46, "%", True), ("尾刀斩杀", "last_hit_kill", 47, "%", True), ("鞭尸", "corpse_rate", 48, "%", True),
        ("鞭尸概率", "corpse_rate", 48, "%", True), ("处决概率", "execution_chance", 49, "%", True), ("韧性", "execution_toughness", 50, "", False),
        ("处决倍率", "execution_multiplier", 51, "%", True), ("处决时间", "execution_time", 52, "秒", False), ("伤害系数", "damage_coefficient", 53, "%", True),
        ("吸血", "life_steal", 54, "%", True), ("每秒回血", "hp_regen", 55, "", False),
    )
}
TEXTLINE_RUNTIME_SPECS = {
    name: _PropertySpec(
        key, 60, unit, "命格P3实例Text行运行时出口", 251,
        DEFAULT_PROPERTY_MODE, DEFAULT_PROPERTY_PERCENT_TYPE, "value_ex",
        "命格P3 TextVar/QFunction受管出口", route="textline_runtime", text_line=text_line,
    )
    for name, key, unit, text_line in (
        ("对怪伤害吸收", "monster_absorb", "%", 33),
        ("道术加成", "tao_percent", "%", 34),
        ("致命伤害", "fatal_damage", "%", 35),
        ("处决概率", "execution_chance", "%", 36),
        ("鞭尸", "corpse_rate", "%", 37),
        ("鞭尸概率", "corpse_rate", "%", 37),
        ("暴击伤害", "critical_damage", "%", 38),
        ("尾刀斩杀", "last_hit_kill", "%", 39),
        ("攻速突破", "attack_speed_breakthrough", "", 40),
    )
}

STATIC_ONLY_PROPERTY_NAMES = (
    "攻击加成", "魔法加成", "伤害吸收上限", "回收增加", "暴击几率", "攻击伤害",
    "魔御", "幸运", "准确", "攻击速度", "伤害吸收", "魔法防御", "忽视防御",
    "伤害反弹", "人物爆率", "体力增加", "魔力增加", "怒气恢复", "合击攻击",
    "怪物爆率", "防爆几率", "防止麻痹", "防止护身", "防止复活", "防止全毒",
    "防止诱惑", "防止火墙", "防止冰冻", "防止蛛网", "致命几率", "致命防御",
    "暴击抗性", "攻击伤害抗性", "杀怪经验倍数", "HP百分比",
)
STATIC_ONLY_PROPERTY_SPECS = {
    name: _PropertySpec(
        f"native_{index:02d}", 7 + index, "%" if name.endswith(("加成", "上限", "增加", "百分比")) else "",
        "09号装备母表属性（用户已确认本服有效）", 251,
        1 if name.endswith(("加成", "上限", "增加", "百分比")) else 0, None, "value",
        "09号装备母表与引擎自定义属性绑定", route="direct",
    )
    for index, name in enumerate(STATIC_ONLY_PROPERTY_NAMES, start=1)
}
UNSUPPORTED_PROPERTY_NAMES: set[str] = set()


class NativeCandidateError(ValueError):
    """命格原生多色候选表不符合安全契约。"""


@dataclass(frozen=True)
class NativeSegment:
    order: int
    role: str
    text: str
    color: int
    note: str
    source_property: str = ""


@dataclass(frozen=True)
class NativeProperty:
    order: int
    display_name: str
    value: int
    value2: int
    value3: int
    property_row: int
    position: int
    binding: int
    unit: str
    effect_status: str
    color: int
    type3: int
    type4: int | None
    value_command: str
    canonical_key: str
    dependency: str | None = None
    route: str = "static_only"
    text_line: int | None = None


@dataclass(frozen=True)
class NativeColorScheme:
    scheme_id: str
    display_name: str
    kind: str
    uniform_color: int | None
    mingge_name_color: int
    property_name_color: int
    sign_color: int
    property_value_color: int
    unit_color: int
    fixed_text_color: int
    note: str = ""

    def color_for(self, role: str) -> int:
        if self.kind == "uniform":
            if self.uniform_color is None:  # pragma: no cover - parser invariant
                raise NativeCandidateError("uniform颜色方案缺少统一色号")
            return self.uniform_color
        mapping = {
            "命格名称": self.mingge_name_color,
            "属性名称": self.property_name_color,
            "正负号": self.sign_color,
            "属性值": self.property_value_color,
            "单位": self.unit_color,
            "固定文字": self.fixed_text_color,
        }
        try:
            return mapping[role]
        except KeyError as exc:  # pragma: no cover - segment parser invariant
            raise NativeCandidateError(f"颜色方案不支持片段角色：{role}") from exc


def _simple_color_scheme(value: object, row: int) -> NativeColorScheme:
    display_name = _text(value, "颜色", row)
    aliases = {
        "红": "整条红色", "红色": "整条红色", "整条红色": "整条红色",
        "绿": "整条绿色", "绿色": "整条绿色", "整条绿色": "整条绿色",
        "蓝": "整条蓝色", "蓝色": "整条蓝色", "整条蓝色": "整条蓝色",
        "彩色": "原生彩色", "原生彩色": "原生彩色", "原生逐段彩色": "原生彩色",
    }
    canonical = aliases.get(display_name)
    if canonical is None:
        raise NativeCandidateError("第%d行颜色必须为：整条红色、整条绿色、整条蓝色、原生彩色" % row)
    if canonical != "原生彩色":
        color = {"整条红色": 249, "整条绿色": 250, "整条蓝色": 252}[canonical]
        return NativeColorScheme(
            scheme_id={"整条红色": "red", "整条绿色": "green", "整条蓝色": "blue"}[canonical],
            display_name=canonical,
            kind="uniform",
            uniform_color=color,
            mingge_name_color=color,
            property_name_color=color,
            sign_color=color,
            property_value_color=color,
            unit_color=color,
            fixed_text_color=color,
        )
    return NativeColorScheme(
        scheme_id="rainbow",
        display_name=canonical,
        kind="native-rainbow",
        uniform_color=None,
        mingge_name_color=249,
        property_name_color=250,
        sign_color=69,
        property_value_color=69,
        unit_color=251,
        fixed_text_color=255,
    )


@dataclass(frozen=True)
class NativeCandidate:
    candidate_id: str
    target_item_name: str
    equip_slot: int
    write_real_property: bool
    property_row: int
    property_color: int
    property_binding: int
    property_position: int
    property_mode: int
    property_percent_type: int
    property_value1: int
    property_value2: int
    property_value3: int
    default_text_color: int
    note: str
    segments: tuple[NativeSegment, ...]
    properties: tuple[NativeProperty, ...] = ()
    mingge_name: str = ""
    color_scheme: NativeColorScheme | None = None


@dataclass(frozen=True)
class NativeCandidateWorkbook:
    source: Path
    candidates: tuple[NativeCandidate, ...]


@dataclass(frozen=True)
class CompiledNativeCandidate:
    candidate_id: str
    script: str
    payload: bytes
    display_text: str
    segment_literal: str


@dataclass(frozen=True)
class NativeGenerationReceipt:
    schema_version: int
    backend: str
    status: str
    source: str
    output: str
    workbook_sha256: str
    candidate_ids: tuple[str, ...]
    candidate_evidence_level: str
    dependencies: tuple[str, ...]
    writes_server: bool
    writes_client: bool
    writes_database: bool
    image_gradient_pipeline_called: bool


@dataclass(frozen=True)
class _Definition:
    candidate_id: str
    enabled: bool
    target_item_name: str
    equip_slot: int
    write_real_property: bool
    property_row: int
    property_color: int
    property_binding: int
    property_position: int
    property_mode: int
    property_percent_type: int
    property_value1: int
    property_value2: int
    property_value3: int
    default_text_color: int
    note: str


def _text(value: object, label: str, row: int, *, allow_empty: bool = False) -> str:
    if value is None:
        result = ""
    elif isinstance(value, str):
        result = value.strip()
    else:
        result = str(value).strip()
    if not result and not allow_empty:
        raise NativeCandidateError(f"第{row}行{label}不能为空")
    return result


def _bool(value: object, label: str, row: int) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"是", "启用", "true", "yes", "1"}:
            return True
        if normalized in {"否", "停用", "false", "no", "0"}:
            return False
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    raise NativeCandidateError(f"第{row}行{label}必须为是/否或TRUE/FALSE")


def _integer(
    value: object,
    label: str,
    row: int,
    *,
    minimum: int = 0,
    maximum: int = 255,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NativeCandidateError(f"第{row}行{label}必须是{minimum}～{maximum}的整数")
    if not minimum <= value <= maximum:
        raise NativeCandidateError(f"第{row}行{label}必须是{minimum}～{maximum}的整数")
    return value


def _signed_integer(value: object, label: str, row: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NativeCandidateError(f"第{row}行{label}必须是整数")
    if not -(2**31) <= value <= 2**31 - 1:
        raise NativeCandidateError(f"第{row}行{label}超出32位整数范围")
    return value


def _table_rows(sheet: object, headers: tuple[str, ...]) -> Iterable[tuple[int, tuple[object, ...]]]:
    actual = tuple(cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1)))
    if actual != headers:
        raise NativeCandidateError(
            f"工作表{sheet.title}标题必须逐字匹配：{'、'.join(headers)}"
        )
    for row_number, cells in enumerate(sheet.iter_rows(min_row=2), start=2):
        values = tuple(cell.value for cell in cells[: len(headers)])
        if not any(value is not None and str(value).strip() for value in values):
            continue
        yield row_number, values


def _definition(row: int, values: tuple[object, ...]) -> _Definition:
    candidate_id = _text(values[0], "候选ID", row)
    if not SAFE_ID.fullmatch(candidate_id):
        raise NativeCandidateError(
            f"第{row}行候选ID只能使用英文字母、数字、点、下划线或短横线，且最长64字符"
        )
    if candidate_id.endswith(".") or candidate_id.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        raise NativeCandidateError(
            f"第{row}行候选ID不能使用Windows保留文件名或以点结尾"
        )
    default_color = _integer(values[14], "默认文字颜色", row)
    if default_color != 255:
        raise NativeCandidateError(f"第{row}行默认文字颜色首版必须固定为255")
    return _Definition(
        candidate_id=candidate_id,
        enabled=_bool(values[1], "启用", row),
        target_item_name=_text(values[2], "目标装备名称", row),
        equip_slot=_integer(values[3], "装备位置", row),
        write_real_property=_bool(values[4], "写真实属性", row),
        property_row=_integer(values[5], "属性行", row, minimum=1),
        property_color=_integer(values[6], "属性颜色", row),
        property_binding=_integer(values[7], "属性绑定", row, minimum=1),
        property_position=_integer(values[8], "属性位置", row, minimum=1),
        property_mode=_integer(values[9], "属性模式", row),
        property_percent_type=_integer(values[10], "属性百分比类型", row),
        property_value1=_signed_integer(values[11], "属性值1", row),
        property_value2=_signed_integer(values[12], "属性值2", row),
        property_value3=_signed_integer(values[13], "属性值3", row),
        default_text_color=default_color,
        note=_text(values[15], "备注", row, allow_empty=True),
    )


def _segment(row: int, values: tuple[object, ...]) -> tuple[str, bool, NativeSegment]:
    candidate_id = _text(values[0], "候选ID", row)
    order = _integer(values[1], "顺序", row, minimum=1, maximum=999)
    role = _text(values[2], "片段角色", row)
    if role not in ALLOWED_ROLES:
        raise NativeCandidateError(
            f"第{row}行片段角色必须为：{'、'.join(sorted(ALLOWED_ROLES))}"
        )
    raw_text = "" if values[3] is None else str(values[3])
    text = raw_text if role != "数值" else raw_text.strip()
    if role == "数值" and text:
        raise NativeCandidateError(
            f"第{row}行数值片段的片段文字必须留空，由属性值1自动生成"
        )
    if role != "数值" and not text:
        raise NativeCandidateError(f"第{row}行片段文字不能为空")
    if "$$" in text or any(character in FORBIDDEN_TEXT for character in text):
        raise NativeCandidateError(
            f"第{row}行片段文字含空格、脚本变量或原生命令控制符"
        )
    segment = NativeSegment(
        order=order,
        role=role,
        text=text,
        color=_integer(values[4], "颜色", row),
        note=_text(values[6], "备注", row, allow_empty=True),
    )
    return candidate_id, _bool(values[5], "启用", row), segment


def _read_v1_native_candidate_workbook(path: Path) -> NativeCandidateWorkbook:
    """严格读取V1两表契约，不从旧命格表或服务端推断任何字段。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise NativeCandidateError("当前平台缺少XLSX读取组件 openpyxl") from exc
    source = Path(path).resolve()
    if not source.is_file():
        raise NativeCandidateError(f"命格原生多色候选表不存在：{source}")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        expected = [DEFINITION_SHEET, SEGMENT_SHEET]
        if workbook.sheetnames != expected:
            raise NativeCandidateError(
                f"候选表必须恰好包含并按顺序排列两张工作表：{'、'.join(expected)}"
            )
        definitions: dict[str, _Definition] = {}
        definition_keys: dict[str, str] = {}
        for row, values in _table_rows(workbook[DEFINITION_SHEET], DEFINITION_HEADERS):
            item = _definition(row, values)
            if item.candidate_id in definitions:
                raise NativeCandidateError(f"候选ID重复：{item.candidate_id}")
            folded = item.candidate_id.casefold()
            if folded in definition_keys:
                raise NativeCandidateError(
                    "候选ID在Windows大小写不敏感文件系统中重复："
                    f"{definition_keys[folded]}、{item.candidate_id}"
                )
            definition_keys[folded] = item.candidate_id
            definitions[item.candidate_id] = item
        if not definitions:
            raise NativeCandidateError("候选定义不能为空")
        grouped: dict[str, list[NativeSegment]] = {key: [] for key in definitions}
        for row, values in _table_rows(workbook[SEGMENT_SHEET], SEGMENT_HEADERS):
            candidate_id, enabled, item = _segment(row, values)
            if candidate_id not in definitions:
                raise NativeCandidateError(f"第{row}行显示片段引用未知候选ID：{candidate_id}")
            if enabled:
                grouped[candidate_id].append(item)
    finally:
        workbook.close()

    candidates = []
    for candidate_id, definition in definitions.items():
        if not definition.enabled:
            continue
        segments = sorted(grouped[candidate_id], key=lambda item: item.order)
        if not segments:
            raise NativeCandidateError(f"启用候选{candidate_id}至少需要一个启用显示片段")
        orders = [item.order for item in segments]
        if orders != list(range(1, len(segments) + 1)):
            raise NativeCandidateError(f"候选{candidate_id}的启用片段顺序必须从1连续递增")
        candidates.append(
            NativeCandidate(
                candidate_id=definition.candidate_id,
                target_item_name=definition.target_item_name,
                equip_slot=definition.equip_slot,
                write_real_property=definition.write_real_property,
                property_row=definition.property_row,
                property_color=definition.property_color,
                property_binding=definition.property_binding,
                property_position=definition.property_position,
                property_mode=definition.property_mode,
                property_percent_type=definition.property_percent_type,
                property_value1=definition.property_value1,
                property_value2=definition.property_value2,
                property_value3=definition.property_value3,
                default_text_color=definition.default_text_color,
                note=definition.note,
                segments=tuple(segments),
            )
        )
    if not candidates:
        raise NativeCandidateError("至少需要一个启用候选")
    return NativeCandidateWorkbook(source=source, candidates=tuple(candidates))


def _v2_candidate_id(value: object, row: int) -> str:
    candidate_id = _text(value, "候选ID", row)
    if not SAFE_ID.fullmatch(candidate_id):
        raise NativeCandidateError(
            f"第{row}行候选ID只能使用英文字母、数字、点、下划线或短横线，且最长64字符"
        )
    if candidate_id.endswith(".") or candidate_id.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        raise NativeCandidateError(f"第{row}行候选ID不能使用Windows保留文件名或以点结尾")
    return candidate_id


def _v2_property_spec(name: str, row: int, *, instance_routes: bool = False) -> _PropertySpec:
    if instance_routes:
        spec = (
            TEXTLINE_RUNTIME_SPECS.get(name)
            or DIRECT_PROPERTY_SPECS.get(name)
            or SCRIPT_PROPERTY_SPECS.get(name)
            or STATIC_ONLY_PROPERTY_SPECS.get(name)
        )
    else:
        spec = (
            DIRECT_PROPERTY_SPECS.get(name)
            or SCRIPT_PROPERTY_SPECS.get(name)
            or TEXTLINE_RUNTIME_SPECS.get(name)
            or STATIC_ONLY_PROPERTY_SPECS.get(name)
        )
    if spec is None:
        raise NativeCandidateError(f"第{row}行中文属性未在受信属性目录中：{name}")
    return spec


def _v2_segment(
    row: int, values: tuple[object, ...]
) -> tuple[str, bool, NativeSegment]:
    candidate_id = _v2_candidate_id(values[0], row)
    role = _text(values[2], "片段角色", row)
    if role not in V2_ALLOWED_ROLES:
        raise NativeCandidateError(f"第{row}行片段角色必须为：{'、'.join(sorted(V2_ALLOWED_ROLES))}")
    source_property = _text(values[3], "来源属性", row, allow_empty=True)
    raw_text = "" if values[4] is None else str(values[4])
    text = raw_text
    if role == "命格名称":
        if source_property or text:
            raise NativeCandidateError(f"第{row}行命格名称片段不得重复填写来源属性或片段文字")
    elif role in {"属性名称", "正负号", "属性值", "单位"}:
        if not source_property or text:
            raise NativeCandidateError(f"第{row}行{role}片段必须选择来源属性且片段文字留空")
    elif source_property or not text:
        raise NativeCandidateError(f"第{row}行固定文字片段不得选择来源属性且片段文字不能为空")
    if text and ("$$" in text or any(character in FORBIDDEN_TEXT for character in text)):
        raise NativeCandidateError(f"第{row}行片段文字含空格、脚本变量或原生命令控制符")
    return candidate_id, _bool(values[6], "启用", row), NativeSegment(
        order=_integer(values[1], "顺序", row, minimum=1, maximum=999),
        role=role,
        text=text,
        color=_integer(values[5], "颜色", row),
        note=_text(values[7], "备注", row, allow_empty=True),
        source_property=source_property,
    )


def _read_v2_native_candidate_workbook(path: Path) -> NativeCandidateWorkbook:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise NativeCandidateError("当前平台缺少XLSX读取组件 openpyxl") from exc
    source = Path(path).resolve()
    if not source.is_file():
        raise NativeCandidateError(f"命格原生多色候选表不存在：{source}")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        if tuple(workbook.sheetnames) != V2_SHEETS:
            raise NativeCandidateError(f"V2候选表必须恰好包含并按顺序排列五张工作表：{'、'.join(V2_SHEETS)}")
        for sheet_name, headers in (
            ("候选定义", V2_DEFINITION_HEADERS), ("自定义属性", V2_PROPERTY_HEADERS),
            ("显示片段", V2_SEGMENT_HEADERS), ("部位说明", V2_PART_HELP_HEADERS),
            ("属性说明", V2_PROPERTY_HELP_HEADERS),
        ):
            actual = tuple(cell.value for cell in next(workbook[sheet_name].iter_rows(min_row=1, max_row=1)))
            if actual != headers:
                raise NativeCandidateError(f"工作表{sheet_name}标题必须逐字匹配：{'、'.join(headers)}")
        definitions: dict[str, tuple[bool, str, int, str, str, int, str]] = {}
        casefold_ids: dict[str, str] = {}
        for row, values in _table_rows(workbook["候选定义"], V2_DEFINITION_HEADERS):
            candidate_id = _v2_candidate_id(values[0], row)
            folded = candidate_id.casefold()
            if candidate_id in definitions or folded in casefold_ids:
                original = casefold_ids.get(folded, candidate_id)
                raise NativeCandidateError(f"候选ID在Windows大小写不敏感文件系统中重复：{original}、{candidate_id}")
            part = _text(values[3], "中文具体部位", row)
            if part in AMBIGUOUS_EQUIP_PARTS:
                raise NativeCandidateError(f"第{row}行中文具体部位{part}存在多槽歧义，请使用明确的左右或编号部位")
            equip_slot = TRUSTED_EQUIP_SLOTS.get(part)
            if equip_slot is None:
                raise NativeCandidateError(f"第{row}行中文具体部位未在受信单槽目录中：{part}")
            default_color = _integer(values[5], "默认文字颜色", row)
            if default_color != 255:
                raise NativeCandidateError(f"第{row}行默认文字颜色首版必须固定为255")
            mingge_name = _text(values[4], "命格名称", row)
            if "$$" in mingge_name or any(character in FORBIDDEN_TEXT for character in mingge_name):
                raise NativeCandidateError(f"第{row}行命格名称含空格、脚本变量或原生命令控制符")
            definitions[candidate_id] = (
                _bool(values[1], "启用", row), _text(values[2], "目标装备名称", row), equip_slot,
                part, mingge_name, default_color, _text(values[6], "备注", row, allow_empty=True),
            )
            casefold_ids[folded] = candidate_id
        if not definitions:
            raise NativeCandidateError("候选定义不能为空")
        properties: dict[str, list[NativeProperty]] = {key: [] for key in definitions}
        property_orders: dict[str, set[int]] = {key: set() for key in definitions}
        property_names: dict[str, set[str]] = {key: set() for key in definitions}
        property_keys: dict[str, set[str]] = {key: set() for key in definitions}
        property_bindings: dict[str, set[int]] = {key: set() for key in definitions}
        for row, values in _table_rows(workbook["自定义属性"], V2_PROPERTY_HEADERS):
            candidate_id = _v2_candidate_id(values[0], row)
            if candidate_id not in definitions:
                raise NativeCandidateError(f"第{row}行自定义属性引用未知候选ID：{candidate_id}")
            if not _bool(values[4], "启用", row):
                continue
            order = _integer(values[1], "顺序", row, minimum=1, maximum=999)
            if order > SAFE_PROPERTY_ROW_END - SAFE_PROPERTY_ROW_START + 1:
                raise NativeCandidateError(f"第{row}行自定义属性最多3条，对应候选行17至19")
            name = _text(values[2], "中文属性", row)
            spec = _v2_property_spec(name, row)
            if order in property_orders[candidate_id] or name in property_names[candidate_id]:
                raise NativeCandidateError(f"第{row}行自定义属性顺序或中文属性在同一候选中重复")
            if spec.canonical_key in property_keys[candidate_id] or spec.binding in property_bindings[candidate_id]:
                raise NativeCandidateError(f"第{row}行自定义属性与同一候选既有规范属性或绑定重复")
            property_orders[candidate_id].add(order)
            property_names[candidate_id].add(name)
            property_keys[candidate_id].add(spec.canonical_key)
            property_bindings[candidate_id].add(spec.binding)
            property_row = SAFE_PROPERTY_ROW_START + order - 1
            effect_status = (
                "引擎直接属性（已游戏实测）"
                if spec.binding == 1 and property_row == SAFE_PROPERTY_ROW_START
                else "官方扩展口径静态候选待实测"
            )
            properties[candidate_id].append(NativeProperty(
                order=order, display_name=name, value=_signed_integer(values[3], "属性值", row),
                value2=0, value3=0, property_row=property_row,
                position=property_row, binding=spec.binding,
                unit=spec.unit, effect_status=effect_status, color=spec.color,
                type3=spec.type3, type4=spec.type4, value_command=spec.value_command,
                canonical_key=spec.canonical_key, dependency=spec.dependency,
                route=spec.route, text_line=spec.text_line,
            ))
        segments: dict[str, list[NativeSegment]] = {key: [] for key in definitions}
        for row, values in _table_rows(workbook["显示片段"], V2_SEGMENT_HEADERS):
            candidate_id, enabled, segment = _v2_segment(row, values)
            if candidate_id not in definitions:
                raise NativeCandidateError(f"第{row}行显示片段引用未知候选ID：{candidate_id}")
            if enabled:
                segments[candidate_id].append(segment)
    finally:
        workbook.close()
    candidates = []
    for candidate_id, definition in definitions.items():
        enabled, item_name, equip_slot, _part, mingge_name, default_color, note = definition
        if not enabled:
            continue
        candidate_properties = sorted(properties[candidate_id], key=lambda item: item.order)
        if not candidate_properties:
            raise NativeCandidateError(f"启用候选{candidate_id}至少需要一条启用自定义属性")
        if [item.order for item in candidate_properties] != list(range(1, len(candidate_properties) + 1)):
            raise NativeCandidateError(f"候选{candidate_id}的启用自定义属性顺序必须从1连续递增")
        by_name = {item.display_name: item for item in candidate_properties}
        candidate_segments = sorted(segments[candidate_id], key=lambda item: item.order)
        if not candidate_segments or [item.order for item in candidate_segments] != list(range(1, len(candidate_segments) + 1)):
            raise NativeCandidateError(f"候选{candidate_id}的启用显示片段顺序必须从1连续递增")
        for segment in candidate_segments:
            if segment.source_property and segment.source_property not in by_name:
                raise NativeCandidateError(f"候选{candidate_id}的显示片段引用未启用中文属性：{segment.source_property}")
            if segment.role == "单位" and not by_name[segment.source_property].unit:
                raise NativeCandidateError(f"候选{candidate_id}的单位片段引用的中文属性没有单位")
        index = 0
        while index < len(candidate_segments):
            segment = candidate_segments[index]
            if segment.role in {"命格名称", "固定文字"}:
                index += 1
                continue
            if segment.role != "属性名称":
                raise NativeCandidateError(f"候选{candidate_id}的显示组必须从属性名称开始")
            source_property = segment.source_property
            required_roles = ("正负号", "属性值")
            for offset, role in enumerate(required_roles, start=1):
                if index + offset >= len(candidate_segments):
                    raise NativeCandidateError(f"候选{candidate_id}的显示组缺少{role}且必须同一来源")
                next_segment = candidate_segments[index + offset]
                if next_segment.role != role or next_segment.source_property != source_property:
                    raise NativeCandidateError(f"候选{candidate_id}的显示组必须同一来源属性且顺序为名称、符号、值、单位")
            index += 3
            if index < len(candidate_segments) and candidate_segments[index].role == "单位":
                if candidate_segments[index].source_property != source_property:
                    raise NativeCandidateError(f"候选{candidate_id}的显示组必须同一来源属性且顺序为名称、符号、值、单位")
                index += 1
        first = candidate_properties[0]
        candidates.append(NativeCandidate(
            candidate_id=candidate_id, target_item_name=item_name, equip_slot=equip_slot,
            write_real_property=True, property_row=first.property_row, property_color=DEFAULT_PROPERTY_COLOR,
            property_binding=first.binding, property_position=first.property_row,
            property_mode=DEFAULT_PROPERTY_MODE, property_percent_type=DEFAULT_PROPERTY_PERCENT_TYPE,
            property_value1=first.value, property_value2=0, property_value3=0,
            default_text_color=default_color, note=note, segments=tuple(candidate_segments),
            properties=tuple(candidate_properties), mingge_name=mingge_name,
        ))
    if not candidates:
        raise NativeCandidateError("至少需要一个启用候选")
    return NativeCandidateWorkbook(source=source, candidates=tuple(candidates))


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _v3_color_scheme(row: int, values: tuple[object, ...]) -> NativeColorScheme:
    scheme_id = _v2_candidate_id(values[0], row)
    display_name = _text(values[1], "中文名称", row)
    kind = _text(values[2], "类型", row)
    if kind not in {"uniform", "native-rainbow"}:
        raise NativeCandidateError(f"第{row}行颜色方案类型只能是uniform或native-rainbow")
    if kind == "uniform":
        uniform = _integer(values[3], "统一色号", row)
        if any(not _is_blank(value) for value in values[4:10]):
            raise NativeCandidateError(f"第{row}行uniform方案的六个角色色号必须留空，统一色号是唯一颜色来源")
        role_colors = (uniform,) * 6
    else:
        if not _is_blank(values[3]):
            raise NativeCandidateError(f"第{row}行native-rainbow方案的统一色号必须留空")
        role_colors = tuple(
            _integer(value, label, row)
            for value, label in zip(values[4:10], V3_COLOR_HEADERS[4:10])
        )
        uniform = None
    return NativeColorScheme(
        scheme_id=scheme_id,
        display_name=display_name,
        kind=kind,
        uniform_color=uniform,
        mingge_name_color=role_colors[0],
        property_name_color=role_colors[1],
        sign_color=role_colors[2],
        property_value_color=role_colors[3],
        unit_color=role_colors[4],
        fixed_text_color=role_colors[5],
        note=_text(values[10], "备注", row, allow_empty=True),
    )


def _v3_segment(
    row: int,
    values: tuple[object, ...],
    scheme: NativeColorScheme,
) -> tuple[str, bool, NativeSegment]:
    candidate_id = _v2_candidate_id(values[0], row)
    role = _text(values[2], "片段角色", row)
    if role not in V2_ALLOWED_ROLES:
        raise NativeCandidateError(f"第{row}行片段角色必须为：{'、'.join(sorted(V2_ALLOWED_ROLES))}")
    source_property = _text(values[3], "来源属性", row, allow_empty=True)
    raw_text = "" if values[4] is None else str(values[4])
    text = raw_text
    if role == "命格名称":
        if source_property or text:
            raise NativeCandidateError(f"第{row}行命格名称片段不得重复填写来源属性或片段文字")
    elif role in {"属性名称", "正负号", "属性值", "单位"}:
        if not source_property or text:
            raise NativeCandidateError(f"第{row}行{role}片段必须选择来源属性且片段文字留空")
    elif source_property or not text:
        raise NativeCandidateError(f"第{row}行固定文字片段不得选择来源属性且片段文字不能为空")
    if text and ("$$" in text or any(character in FORBIDDEN_TEXT for character in text)):
        raise NativeCandidateError(f"第{row}行片段文字含空格、脚本变量或原生命令控制符")
    return candidate_id, _bool(values[5], "启用", row), NativeSegment(
        order=_integer(values[1], "顺序", row, minimum=1, maximum=999),
        role=role,
        text=text,
        color=scheme.color_for(role),
        note=_text(values[6], "备注", row, allow_empty=True),
        source_property=source_property,
    )


def _derive_segments(
    properties: list[NativeProperty],
    color_scheme: NativeColorScheme,
) -> list[NativeSegment]:
    segments: list[NativeSegment] = [
        NativeSegment(1, "命格名称", "", color_scheme.color_for("命格名称"), "平台自动生成")
    ]
    order = 2
    for property_index, property_item in enumerate(properties):
        for role in ("属性名称", "正负号", "属性值"):
            segments.append(NativeSegment(
                order, role, "", color_scheme.color_for(role), "平台自动生成", property_item.display_name,
            ))
            order += 1
        if property_item.unit:
            segments.append(NativeSegment(
                order, "单位", "", color_scheme.color_for("单位"), "平台自动生成", property_item.display_name,
            ))
            order += 1
        if property_index + 1 < len(properties):
            segments.append(NativeSegment(
                order, "固定文字", "·", color_scheme.color_for("固定文字"), "平台自动生成",
            ))
            order += 1
    return segments


def _read_v3_native_candidate_workbook(path: Path, *, derive_segments: bool = False) -> NativeCandidateWorkbook:
    """严格读取V3六表；颜色只从候选引用的颜色方案派生。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise NativeCandidateError("当前平台缺少XLSX读取组件 openpyxl") from exc
    source = Path(path).resolve()
    if not source.is_file():
        raise NativeCandidateError(f"命格原生多色候选表不存在：{source}")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        if tuple(workbook.sheetnames) != V3_SHEETS:
            raise NativeCandidateError(f"V3候选表必须恰好包含并按顺序排列六张工作表：{'、'.join(V3_SHEETS)}")
        for sheet_name, headers in (
            ("候选定义", V3_DEFINITION_HEADERS),
            ("自定义属性", V3_PROPERTY_HEADERS),
            ("显示片段", V3_SEGMENT_HEADERS),
            ("颜色方案", V3_COLOR_HEADERS),
            ("部位说明", V3_PART_HELP_HEADERS),
            ("属性说明", V3_PROPERTY_HELP_HEADERS),
        ):
            actual = tuple(cell.value for cell in next(workbook[sheet_name].iter_rows(min_row=1, max_row=1)))
            if actual != headers:
                raise NativeCandidateError(f"工作表{sheet_name}标题必须逐字匹配：{'、'.join(headers)}")

        color_schemes: dict[str, NativeColorScheme] = {}
        color_casefold_ids: dict[str, str] = {}
        for row, values in _table_rows(workbook["颜色方案"], V3_COLOR_HEADERS):
            scheme = _v3_color_scheme(row, values)
            folded = scheme.scheme_id.casefold()
            if scheme.scheme_id in color_schemes or folded in color_casefold_ids:
                original = color_casefold_ids.get(folded, scheme.scheme_id)
                raise NativeCandidateError(f"颜色方案ID在Windows大小写不敏感环境中重复：{original}、{scheme.scheme_id}")
            color_schemes[scheme.scheme_id] = scheme
            color_casefold_ids[folded] = scheme.scheme_id
        if not color_schemes:
            raise NativeCandidateError("颜色方案不能为空")

        definitions: dict[str, tuple[bool, str, int, str, str, NativeColorScheme, str]] = {}
        casefold_ids: dict[str, str] = {}
        for row, values in _table_rows(workbook["候选定义"], V3_DEFINITION_HEADERS):
            candidate_id = _v2_candidate_id(values[0], row)
            folded = candidate_id.casefold()
            if candidate_id in definitions or folded in casefold_ids:
                original = casefold_ids.get(folded, candidate_id)
                raise NativeCandidateError(f"候选ID在Windows大小写不敏感文件系统中重复：{original}、{candidate_id}")
            part = _text(values[3], "中文具体部位", row)
            if part in AMBIGUOUS_EQUIP_PARTS:
                raise NativeCandidateError(f"第{row}行中文具体部位{part}存在多槽歧义，请使用明确的左右或编号部位")
            equip_slot = TRUSTED_EQUIP_SLOTS.get(part)
            if equip_slot is None:
                raise NativeCandidateError(f"第{row}行中文具体部位未在受信单槽目录中：{part}")
            mingge_name = _text(values[4], "命格名称", row)
            if "$$" in mingge_name or any(character in FORBIDDEN_TEXT for character in mingge_name):
                raise NativeCandidateError(f"第{row}行命格名称含空格、脚本变量或原生命令控制符")
            color_scheme_id = _v2_candidate_id(values[5], row)
            color_scheme = color_schemes.get(color_scheme_id)
            if color_scheme is None:
                raise NativeCandidateError(f"第{row}行候选引用未知颜色方案ID：{color_scheme_id}")
            definitions[candidate_id] = (
                _bool(values[1], "启用", row),
                _text(values[2], "目标装备名称", row),
                equip_slot,
                part,
                mingge_name,
                color_scheme,
                _text(values[6], "备注", row, allow_empty=True),
            )
            casefold_ids[folded] = candidate_id
        if not definitions:
            raise NativeCandidateError("候选定义不能为空")

        properties: dict[str, list[NativeProperty]] = {key: [] for key in definitions}
        property_orders: dict[str, set[int]] = {key: set() for key in definitions}
        property_names: dict[str, set[str]] = {key: set() for key in definitions}
        property_keys: dict[str, set[str]] = {key: set() for key in definitions}
        for row, values in _table_rows(workbook["自定义属性"], V3_PROPERTY_HEADERS):
            candidate_id = _v2_candidate_id(values[0], row)
            if candidate_id not in definitions:
                raise NativeCandidateError(f"第{row}行自定义属性引用未知候选ID：{candidate_id}")
            if not _bool(values[4], "启用", row):
                continue
            order = _integer(values[1], "顺序", row, minimum=1, maximum=999)
            if order > SAFE_PROPERTY_ROW_END - SAFE_PROPERTY_ROW_START + 1:
                raise NativeCandidateError(f"第{row}行自定义属性最多3条，对应候选行17至19")
            name = _text(values[2], "中文属性", row)
            spec = _v2_property_spec(name, row, instance_routes=True)
            if order in property_orders[candidate_id] or name in property_names[candidate_id]:
                raise NativeCandidateError(f"第{row}行自定义属性顺序或中文属性在同一候选中重复")
            if spec.canonical_key in property_keys[candidate_id]:
                raise NativeCandidateError(f"第{row}行自定义属性与同一候选既有规范属性重复")
            property_orders[candidate_id].add(order)
            property_names[candidate_id].add(name)
            property_keys[candidate_id].add(spec.canonical_key)
            property_row = SAFE_PROPERTY_ROW_START + order - 1
            effect_status = spec.effect_status
            properties[candidate_id].append(NativeProperty(
                order=order,
                display_name=name,
                value=_signed_integer(values[3], "属性值", row),
                value2=0,
                value3=0,
                property_row=property_row,
                position=spec.text_line if spec.text_line is not None else property_row,
                binding=spec.binding,
                unit=spec.unit,
                effect_status=effect_status,
                color=spec.color,
                type3=spec.type3,
                type4=spec.type4,
                value_command=spec.value_command,
                canonical_key=spec.canonical_key,
                dependency=spec.dependency,
                route=spec.route,
                text_line=spec.text_line,
            ))

        segments: dict[str, list[NativeSegment]] = {key: [] for key in definitions}
        for row, values in _table_rows(workbook["显示片段"], V3_SEGMENT_HEADERS):
            candidate_id = _v2_candidate_id(values[0], row)
            if candidate_id not in definitions:
                raise NativeCandidateError(f"第{row}行显示片段引用未知候选ID：{candidate_id}")
            _, _, _, _, _, scheme, _ = definitions[candidate_id]
            _, enabled, segment = _v3_segment(row, values, scheme)
            if enabled:
                segments[candidate_id].append(segment)
    finally:
        workbook.close()

    candidates: list[NativeCandidate] = []
    for candidate_id, definition in definitions.items():
        enabled, item_name, equip_slot, _part, mingge_name, color_scheme, note = definition
        if not enabled:
            continue
        candidate_properties = sorted(properties[candidate_id], key=lambda item: item.order)
        if not candidate_properties:
            raise NativeCandidateError(f"启用候选{candidate_id}至少需要一条启用自定义属性")
        if [item.order for item in candidate_properties] != list(range(1, len(candidate_properties) + 1)):
            raise NativeCandidateError(f"候选{candidate_id}的启用自定义属性顺序必须从1连续递增")
        by_name = {item.display_name: item for item in candidate_properties}
        if derive_segments:
            candidate_segments = _derive_segments(candidate_properties, color_scheme)
        else:
            candidate_segments = sorted(segments[candidate_id], key=lambda item: item.order)
        if not candidate_segments or [item.order for item in candidate_segments] != list(range(1, len(candidate_segments) + 1)):
            raise NativeCandidateError(f"候选{candidate_id}的启用显示片段顺序必须从1连续递增")
        for segment in candidate_segments:
            if segment.source_property and segment.source_property not in by_name:
                raise NativeCandidateError(f"候选{candidate_id}的显示片段引用未启用中文属性：{segment.source_property}")
            if segment.role == "单位" and not by_name[segment.source_property].unit:
                raise NativeCandidateError(f"候选{candidate_id}的单位片段引用的中文属性没有单位")
        index = 0
        while index < len(candidate_segments):
            segment = candidate_segments[index]
            if segment.role in {"命格名称", "固定文字"}:
                index += 1
                continue
            if segment.role != "属性名称":
                raise NativeCandidateError(f"候选{candidate_id}的显示组必须从属性名称开始")
            source_property = segment.source_property
            for offset, role in enumerate(("正负号", "属性值"), start=1):
                if index + offset >= len(candidate_segments):
                    raise NativeCandidateError(f"候选{candidate_id}的显示组缺少{role}且必须同一来源")
                following = candidate_segments[index + offset]
                if following.role != role or following.source_property != source_property:
                    raise NativeCandidateError(f"候选{candidate_id}的显示组必须同一来源属性且顺序为名称、符号、值、单位")
            index += 3
            if index < len(candidate_segments) and candidate_segments[index].role == "单位":
                if candidate_segments[index].source_property != source_property:
                    raise NativeCandidateError(f"候选{candidate_id}的显示组必须同一来源属性且顺序为名称、符号、值、单位")
                index += 1
        first = candidate_properties[0]
        candidates.append(NativeCandidate(
            candidate_id=candidate_id,
            target_item_name=item_name,
            equip_slot=equip_slot,
            write_real_property=True,
            property_row=first.property_row,
            property_color=DEFAULT_PROPERTY_COLOR,
            property_binding=first.binding,
            property_position=first.property_row,
            property_mode=DEFAULT_PROPERTY_MODE,
            property_percent_type=DEFAULT_PROPERTY_PERCENT_TYPE,
            property_value1=first.value,
            property_value2=0,
            property_value3=0,
            default_text_color=255,
            note=note,
            segments=tuple(candidate_segments),
            properties=tuple(candidate_properties),
            mingge_name=mingge_name,
            color_scheme=color_scheme,
        ))
    if not candidates:
        raise NativeCandidateError("至少需要一个启用候选")
    return NativeCandidateWorkbook(source=source, candidates=tuple(candidates))


def _read_simple_native_candidate_workbook(path: Path) -> NativeCandidateWorkbook:
    """读取面向人工编辑的两页中文简表，内部字段全部由平台生成。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise NativeCandidateError("当前平台缺少XLSX读取组件 openpyxl") from exc
    source = Path(path).resolve()
    if not source.is_file():
        raise NativeCandidateError(f"命格配置表不存在：{source}")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        if tuple(workbook.sheetnames) != SIMPLE_SHEETS:
            raise NativeCandidateError("中文简表必须恰好包含两张工作表：命格配置、数据字典")
        for sheet_name, headers in (
            ("命格配置", SIMPLE_CONFIG_HEADERS),
            ("数据字典", SIMPLE_DICTIONARY_HEADERS),
        ):
            actual = tuple(cell.value for cell in next(workbook[sheet_name].iter_rows(min_row=1, max_row=1)))
            if actual != headers:
                raise NativeCandidateError(f"工作表{sheet_name}标题必须逐字匹配：{'、'.join(headers)}")

        candidates: list[NativeCandidate] = []
        for row, values in _table_rows(workbook["命格配置"], SIMPLE_CONFIG_HEADERS):
            if not _bool(values[0], "启用", row):
                continue
            item_name = _text(values[1], "目标装备", row)
            part = _text(values[2], "部位", row)
            if part in AMBIGUOUS_EQUIP_PARTS:
                raise NativeCandidateError(f"第{row}行部位“{part}”存在多槽歧义，请选择明确的左右或编号部位")
            equip_slot = TRUSTED_EQUIP_SLOTS.get(part)
            if equip_slot is None:
                raise NativeCandidateError(f"第{row}行部位不在中文部位目录中：{part}")
            mingge_name = _text(values[3], "命格名称", row)
            if "$$" in mingge_name or any(character in FORBIDDEN_TEXT for character in mingge_name):
                raise NativeCandidateError(f"第{row}行命格名称含空格、脚本变量或原生命令控制符")
            color_scheme = _simple_color_scheme(values[4], row)

            candidate_properties: list[NativeProperty] = []
            property_names: set[str] = set()
            property_keys: set[str] = set()
            for visible_index, (name_value, property_value) in enumerate(
                ((values[5], values[6]), (values[7], values[8]), (values[9], values[10])),
                start=1,
            ):
                name = _text(name_value, f"属性{visible_index}", row, allow_empty=True)
                value_is_empty = property_value is None or (
                    isinstance(property_value, str) and not property_value.strip()
                )
                if not name and value_is_empty:
                    continue
                if not name or value_is_empty:
                    raise NativeCandidateError(f"第{row}行属性{visible_index}与数值{visible_index}必须成对填写")
                spec = _v2_property_spec(name, row, instance_routes=True)
                if name in property_names or spec.canonical_key in property_keys:
                    raise NativeCandidateError(f"第{row}行同一命格不能重复填写中文属性：{name}")
                property_names.add(name)
                property_keys.add(spec.canonical_key)
                order = len(candidate_properties) + 1
                property_row = SAFE_PROPERTY_ROW_START + order - 1
                candidate_properties.append(NativeProperty(
                    order=order,
                    display_name=name,
                    value=_signed_integer(property_value, f"数值{visible_index}", row),
                    value2=0,
                    value3=0,
                    property_row=property_row,
                    position=spec.text_line if spec.text_line is not None else property_row,
                    binding=spec.binding,
                    unit=spec.unit,
                    effect_status=spec.effect_status,
                    color=spec.color,
                    type3=spec.type3,
                    type4=spec.type4,
                    value_command=spec.value_command,
                    canonical_key=spec.canonical_key,
                    dependency=spec.dependency,
                    route=spec.route,
                    text_line=spec.text_line,
                ))
            if not candidate_properties:
                raise NativeCandidateError(f"第{row}行【{mingge_name}】至少需要填写一项属性和值")

            first = candidate_properties[0]
            candidate_id = f"candidate-{row:04d}"
            candidates.append(NativeCandidate(
                candidate_id=candidate_id,
                target_item_name=item_name,
                equip_slot=equip_slot,
                write_real_property=True,
                property_row=first.property_row,
                property_color=DEFAULT_PROPERTY_COLOR,
                property_binding=first.binding,
                property_position=first.property_row,
                property_mode=DEFAULT_PROPERTY_MODE,
                property_percent_type=DEFAULT_PROPERTY_PERCENT_TYPE,
                property_value1=first.value,
                property_value2=0,
                property_value3=0,
                default_text_color=255,
                note="平台中文简表自动生成",
                segments=tuple(_derive_segments(candidate_properties, color_scheme)),
                properties=tuple(candidate_properties),
                mingge_name=mingge_name,
                color_scheme=color_scheme,
            ))
    finally:
        workbook.close()
    if not candidates:
        raise NativeCandidateError("命格配置中至少需要一行启用的命格")
    return NativeCandidateWorkbook(source=source, candidates=tuple(candidates))


def read_native_candidate_workbook(path: Path, *, derive_v3_segments: bool = False) -> NativeCandidateWorkbook:
    """识别旧版V1/V2/V3或面向人工编辑的两页中文简表。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise NativeCandidateError("当前平台缺少XLSX读取组件 openpyxl") from exc
    source = Path(path).resolve()
    if not source.is_file():
        raise NativeCandidateError(f"命格原生多色候选表不存在：{source}")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        sheets = tuple(workbook.sheetnames)
    finally:
        workbook.close()
    if sheets == (DEFINITION_SHEET, SEGMENT_SHEET):
        return _read_v1_native_candidate_workbook(source)
    if sheets == V2_SHEETS:
        return _read_v2_native_candidate_workbook(source)
    if sheets == V3_SHEETS:
        return _read_v3_native_candidate_workbook(source, derive_segments=derive_v3_segments)
    if sheets == SIMPLE_SHEETS:
        return _read_simple_native_candidate_workbook(source)
    raise NativeCandidateError("命格表必须为中文简表两页结构，或旧版V1/V2/V3兼容结构")


def _candidate_properties(candidate: NativeCandidate) -> tuple[NativeProperty, ...]:
    if candidate.properties:
        return candidate.properties
    return (
        NativeProperty(
            order=1,
            display_name="",
            value=candidate.property_value1,
            value2=candidate.property_value2,
            value3=candidate.property_value3,
            property_row=candidate.property_row,
            position=candidate.property_position,
            binding=candidate.property_binding,
            unit="",
            effect_status="V1兼容字段",
            color=candidate.property_color,
            type3=candidate.property_mode,
            type4=candidate.property_percent_type,
            value_command="value_ex",
            canonical_key="v1",
            route="direct",
        ),
    )


def _resolved_segment_text(candidate: NativeCandidate, segment: NativeSegment) -> str:
    if segment.role == "数值":
        return f"{candidate.property_value1:+d}"
    if not candidate.properties:
        return segment.text
    properties = {item.display_name: item for item in candidate.properties}
    if segment.role == "命格名称":
        return candidate.mingge_name
    if segment.role == "固定文字":
        return segment.text
    property_item = properties[segment.source_property]
    if segment.role == "属性名称":
        return property_item.display_name
    if segment.role == "正负号":
        return "+" if property_item.value >= 0 else "-"
    if segment.role == "属性值":
        return str(abs(property_item.value))
    if segment.role == "单位":
        return property_item.unit
    return segment.text


def compile_native_candidate(candidate: NativeCandidate) -> CompiledNativeCandidate:
    """把单个候选编译为当前版本已实测的原生片段命令。"""
    segment_literal = "".join(
        f"{{{_resolved_segment_text(candidate, segment)}|{segment.color}}}"
        for segment in candidate.segments
    )
    lines = [f"LockUpdateItem {candidate.equip_slot}"]
    uses_attack_speed_breakthrough = False
    if candidate.write_real_property:
        slot = candidate.equip_slot
        for item in _candidate_properties(candidate):
            if item.route == "static_only":
                raise NativeCandidateError(f"属性{item.display_name}只有static_only目录路由，不能伪造成实例实效")
            lines.extend((
                f"SetCustomItemAbil {slot} {item.property_row} 0 {item.color}",
                f"SetCustomItemAbil {slot} {item.property_row} 1 {item.binding}",
                f"SetCustomItemAbil {slot} {item.property_row} 2 {item.position}",
                f"SetCustomItemAbil {slot} {item.property_row} 3 {item.type3}",
            ))
            if item.type4 is not None:
                lines.append(f"SetCustomItemAbil {slot} {item.property_row} 4 {item.type4}")
            if item.text_line == 40:
                lines.append(
                    f"SetCustomItemValueEx {slot} {item.property_row} = 40 {item.value} 0"
                )
                uses_attack_speed_breakthrough = True
            elif item.value_command == "value_ex":
                lines.append(f"SetCustomItemValueEx {slot} {item.property_row} = {item.value} {item.value2} {item.value3}")
            else:
                lines.append(f"SetCustomItemValue {slot} {item.property_row} = {item.value}")
    lines.extend(
        (
            f"SetCustomItemText {candidate.equip_slot} {segment_literal}",
            f"SetCustomItemTextColor {candidate.equip_slot} {candidate.default_text_color}",
            f"UpdateItem {candidate.equip_slot}",
        )
    )
    if uses_attack_speed_breakthrough:
        lines.append("#CALL [\\玄渊攻速突破\\全身攻速阈值核心.txt] @XY_AS_CAP_RECALC")
    script = "\r\n".join(lines) + "\r\n"
    return CompiledNativeCandidate(
        candidate_id=candidate.candidate_id,
        script=script,
        payload=script.encode("gb18030"),
        display_text="".join(
            _resolved_segment_text(candidate, segment) for segment in candidate.segments
        ),
        segment_literal=segment_literal,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def validate_native_output_container(
    output_dir: Path, *, allowed_output_root: Path
) -> Path:
    """只允许在平台专用 outputs 根目录内创建候选批次。"""
    allowed_raw = Path(allowed_output_root).absolute()
    is_junction = getattr(os.path, "isjunction", lambda _: False)
    if allowed_raw.is_symlink() or is_junction(allowed_raw):
        raise NativeCandidateError("平台outputs目录本身不能是符号链接或目录联接")
    allowed = allowed_raw.resolve()
    output = Path(output_dir).resolve()
    try:
        output.relative_to(allowed)
    except ValueError as exc:
        raise NativeCandidateError(
            f"候选输出目录必须位于平台outputs目录内：{allowed}"
        ) from exc
    return output


def generate_native_candidates(
    workbook_path: Path,
    output_dir: Path,
    *,
    allowed_output_root: Path,
) -> NativeGenerationReceipt:
    """在平台 outputs 白名单内原子发布一个独立离线候选批次。"""
    book = read_native_candidate_workbook(workbook_path, derive_v3_segments=True)
    allowed_raw = Path(allowed_output_root).absolute()
    is_junction = getattr(os.path, "isjunction", lambda _: False)
    if allowed_raw.is_symlink() or is_junction(allowed_raw):
        raise NativeCandidateError("平台outputs目录本身不能是符号链接或目录联接")
    allowed_raw.mkdir(parents=True, exist_ok=True)
    if allowed_raw.is_symlink() or is_junction(allowed_raw):
        raise NativeCandidateError("平台outputs目录本身不能是符号链接或目录联接")
    allowed = allowed_raw.resolve()
    output_container = validate_native_output_container(
        output_dir, allowed_output_root=allowed
    )
    if book.source == output_container or book.source.is_relative_to(output_container):
        raise NativeCandidateError("候选输出目录必须与输入表格分开")
    output_container.mkdir(parents=True, exist_ok=True)
    output_container = validate_native_output_container(
        output_container.resolve(), allowed_output_root=allowed
    )
    workbook_hash = _sha256(book.source)
    generated_at = datetime.now(timezone.utc).isoformat()
    compiled_items = tuple(compile_native_candidate(item) for item in book.candidates)
    by_id = {item.candidate_id: item for item in book.candidates}
    batch_name = (
        f"batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{workbook_hash[:12]}-{uuid.uuid4().hex[:8]}"
    )
    published = output_container / batch_name
    temporary = Path(
        tempfile.mkdtemp(prefix=".native-segments-", dir=output_container)
    )
    try:
        for compiled in compiled_items:
            definition = by_id[compiled.candidate_id]
            schema_version = 3 if definition.color_scheme is not None else (2 if definition.properties else 1)
            script_path = temporary / f"{compiled.candidate_id}.txt"
            evidence_path = temporary / f"{compiled.candidate_id}.json"
            evidence = {
            "schema_version": schema_version,
            "backend": "native_segments",
            "status": "candidate",
            "candidate_id": compiled.candidate_id,
            "source_workbook": str(book.source),
            "source_workbook_sha256": workbook_hash,
            "generated_at_utc": generated_at,
            "target_item_name": definition.target_item_name,
            "equip_slot": definition.equip_slot,
            "writes_real_property_in_candidate_script": definition.write_real_property,
            "real_property": {
                "row": definition.property_row,
                "color": definition.property_color,
                "binding": definition.property_binding,
                "position": definition.property_position,
                "mode": definition.property_mode,
                "percent_type": definition.property_percent_type,
                "value1": definition.property_value1,
                "value2": definition.property_value2,
                "value3": definition.property_value3,
            } if not definition.properties else None,
            "v2_properties": [
                {
                    "中文属性": item.display_name,
                    "属性值": item.value,
                    "单位": item.unit,
                    "实效状态": item.effect_status,
                    "依赖": item.dependency,
                }
                for item in definition.properties
            ],
            "color_scheme": asdict(definition.color_scheme) if definition.color_scheme is not None else None,
            "segments": [
                {
                    **asdict(segment),
                    "resolved_text": _resolved_segment_text(definition, segment),
                }
                for segment in definition.segments
            ],
            "segment_literal": compiled.segment_literal,
            "display_text": compiled.display_text,
            "script_encoding": "GB18030",
            "script_newline": "CRLF",
            "script_sha256": hashlib.sha256(compiled.payload).hexdigest(),
            "writes_server": False,
            "writes_client": False,
            "writes_database": False,
            "image_gradient_pipeline_called": False,
            "safety_boundary": "offline candidate only; manual review required",
            }
            _atomic_write(script_path, compiled.payload)
            _atomic_write(
                evidence_path,
                (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
        receipt = NativeGenerationReceipt(
            schema_version=(
                3 if any(item.color_scheme is not None for item in book.candidates)
                else (2 if any(item.properties for item in book.candidates) else 1)
            ),
            backend="native_segments",
            status="candidate",
            source=str(book.source),
            output=str(published),
            workbook_sha256=workbook_hash,
            candidate_ids=tuple(item.candidate_id for item in compiled_items),
            candidate_evidence_level="candidate",
            dependencies=tuple(sorted({
                item.dependency
                for candidate in book.candidates
                for item in candidate.properties
                if item.dependency
            })),
            writes_server=False,
            writes_client=False,
            writes_database=False,
            image_gradient_pipeline_called=False,
        )
        _atomic_write(
            temporary / "generation-receipt.json",
            (json.dumps(asdict(receipt), ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        os.replace(temporary, published)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return receipt
