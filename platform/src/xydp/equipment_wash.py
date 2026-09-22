from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import os
import stat
from typing import Any
from pathlib import Path

from .mingge_dual import (
    DualInstallPlan,
    MinggeDualError,
    _DualService,
    _change,
    _managed_block,
    _plan_id,
    _script_bytes,
    _script_text,
    _sha256,
    _target,
    _upsert_after_anchor,
    _upsert_after_label,
)


ROUTE = "equipment-wash-import"
NORMAL_CATEGORY_COUNT = 15
ATTACK_SPEED_BREAKTHROUGH_DENOMINATOR = 1000
PACKAGE_ID = "xy.optional.equipment-wash-opening"

MAIN_RELATIVE = Path("Mir200/Envir/Market_Def/玄渊实验室/装备洗练-XY_NMGF_MAIN.txt")
WASH_DIRECTORY = Path("Mir200/Envir/QuestDiary/玄渊实验室/装备洗练")
RANDOM_CORE_RELATIVE = WASH_DIRECTORY / "洗练词条随机核心.txt"
EFFECT_CORE_RELATIVE = WASH_DIRECTORY / "洗练词条实效核心.txt"
QFUNCTION_RELATIVE = Path("Mir200/Envir/Market_Def/QFunction-0.txt")
ATTACK_SPEED_CORE_RELATIVE = Path("Mir200/Envir/QuestDiary/玄渊攻速突破/全身攻速阈值核心.txt")
TEXTVAR_RELATIVE = Path("Mir200/Envir/CustomItemPropertyTextVarList.txt")

_BASELINE_SHA256 = {
    MAIN_RELATIVE: "D51CA2D0828AC7D8C07A771B1E1AC68CC93F6EF4E8E2A543B49F3B603E95A0BD",
    WASH_DIRECTORY / "仙级直出.txt": "04CA49BB6CD51BA3C06EF3F846B81BC21A2DBE3D2183ABB886EB80DA92428F9E",
    WASH_DIRECTORY / "圣级直出.txt": "608598D30E668194724EB321B05CBD57839A722AED71D3E48F3310A97FB12CEE",
    WASH_DIRECTORY / "天赐开光.txt": "5A2F0AC58C1991689CF8A71BCB1FC2563AF7BADF5B53672D1D68E9A06C77F9F5",
    WASH_DIRECTORY / "神佑开光.txt": "33408AAC3D668384DE180B185E8702EDC3B0D0748F14FB6C0DB81B229F9B5B0D",
}
_IMPORT_MARKER = "XY-EQUIPMENT-WASH-IMPORT-V1"
_UNWRAPPED_DIRECT_SHA256 = {
    "仙级直出.txt": "06CAAE7C63D682E45C5B41710CF5C9C6ADF838CD5A54E719BC59CEBD58A069DB",
    "圣级直出.txt": "39262E6E83BD2056D11A5A34E01350A7B11EE0D75290DDA3C81485B89985AD46",
    "天赐开光.txt": "A062C48283B401138984B6F39396831D8C2D4CFD57051D77D4353EE1BCA1EFF3",
    "神佑开光.txt": "A5A166F49B0882ECFB3029470FEAB27E104F9CD1349CBA621438D1641BF3E30F",
}


# Exact stateless legacy outputs already supported before the runtime repair.
_LEGACY_GENERATED_SHA256 = {
    Path('Mir200/Envir/Market_Def/玄渊实验室/装备洗练-XY_NMGF_MAIN.txt'): 'b4b643be532f255d9cf553ea11d4ed65767e1b5c414d379b628e4481e91ef59b',
    Path('Mir200/Envir/QuestDiary/玄渊实验室/装备洗练/洗练词条随机核心.txt'): 'aba3d9d2d25c95fe6ec102c75f3120e9373849186075b1c701160e54c77ea8dc',
    Path('Mir200/Envir/QuestDiary/玄渊实验室/装备洗练/仙级直出.txt'): 'dc497eaac25de3ab45dc45e9bc938723cafbb4d6f8d54254134b9870dfce934b',
    Path('Mir200/Envir/QuestDiary/玄渊实验室/装备洗练/圣级直出.txt'): 'c23cdd20e8250f096d02ed7b26c3ebefff1bbe9ea541228bf27c9ce176af583b',
    Path('Mir200/Envir/QuestDiary/玄渊实验室/装备洗练/天赐开光.txt'): '40aa3511eb552a1ca3858b00392eafab045aa48402339016850ae5c4b7d95528',
    Path('Mir200/Envir/QuestDiary/玄渊实验室/装备洗练/神佑开光.txt'): '3f85806ddcc1055eb4a5372005e71cdcad003b9dac50326cf0feba4384f9ba91',
}

class EquipmentWashError(ValueError):
    pass


@dataclass(frozen=True)
class WashAffix:
    name: str
    tiers: tuple[tuple[int, ...], ...]
    native_new_item_index: int | None = None


@dataclass(frozen=True)
class WashCatalog:
    affixes: tuple[WashAffix, ...]

    def find(self, name: str) -> WashAffix:
        for affix in self.affixes:
            if affix.name == name:
                return affix
        raise EquipmentWashError(f"未找到洗练词条：{name}")


_AFFIXES = (
    WashAffix("攻击", ()),
    WashAffix("魔法", ()),
    WashAffix("道术", ()),
    WashAffix("攻击速度", ((1, 80), (2, 20))),
    WashAffix("处决", ((1, 80), (2, 20))),
    WashAffix("处决时间", ((1, 80), (2, 20))),
    WashAffix("处决伤害", ((1, 80), (2, 20))),
    WashAffix("韧性", ((10, 80), (20, 20))),
    WashAffix("暴击", ((1, 80), (2, 20)), native_new_item_index=0),
    WashAffix("致命一击", ((1, 80), (2, 20)), native_new_item_index=21),
    WashAffix("攻击加成", ((1, 30, 80), (31, 50, 20))),
    WashAffix("吸血", ((1, 80), (2, 20))),
    WashAffix("最大爆率", ((1, 40), (2, 40), (3, 20))),
    WashAffix("伤害系数", ((1, 40), (2, 40), (3, 20))),
    WashAffix("伤害吸收上限", ((1, 40), (2, 40), (3, 20))),
    WashAffix("攻速突破", ((1, 100),)),
)


def parse_wash_affix_text(text: str, source_name: str = 'TXT') -> WashCatalog:
    normalized = text.replace("最大暴率", "最大爆率")
    values: dict[str, list[tuple[int, ...]]] = {a.name: [] for a in _AFFIXES[3:]}
    names = sorted(values, key=len, reverse=True)
    flat_rule = False
    positions: dict[str, list[int]] = {name: [] for name in values}
    for line_number, raw in enumerate(normalized.splitlines(), 1):
        line = re.sub(r"^\d+\s*[，,.、]?\s*", "", raw.strip())
        if not line or line.startswith(";") or line == "洗练可以洗出的属性包括":
            continue
        if line.startswith("攻击/魔法/道术"):
            accepted = "攻击/魔法/道术，数值为1至该装备最大攻击/魔法/道术的上限的一半。"
            if not line.startswith(accepted):
                raise EquipmentWashError(f"{source_name} 第{line_number}行：攻魔道仅支持9月5日的上限一半规则")
            suffix = line[len(accepted):]
            if suffix not in ("", "即原装备30-100攻击，单条最高可50攻击，"):
                raise EquipmentWashError(f"{source_name} 第{line_number}行：攻魔道存在未支持的补充规则")
            if flat_rule:
                raise EquipmentWashError(f"{source_name} 第{line_number}行：攻魔道规则重复")
            flat_rule = True
            continue
        if line == "可多条同时生效。":
            continue
        name = next((n for n in names if line.startswith(n)), None)
        if name is None:
            raise EquipmentWashError(f"{source_name} 第{line_number}行：存在无法识别的属性或规则：{raw}")
        tail = line[len(name):].rstrip("，,。 ")
        if name == "处决" and tail == "+1（处决概率加百分之一）":
            tail = "+1"
        match = re.fullmatch(r"(\d+)-(\d+)", tail) if name == "攻击加成" else re.fullmatch(r"\+(\d+)", tail)
        if not match:
            raise EquipmentWashError(f"{source_name} 第{line_number}行：{name}数值格式不支持：{tail}")
        numbers = tuple(int(v) for v in match.groups())
        maximum = 255 if name in ("暴击", "致命一击") else 1000
        if any(v < 1 or v > maximum for v in numbers) or numbers != tuple(sorted(numbers)):
            raise EquipmentWashError(f"{source_name} 第{line_number}行：{name}数值需为1至{maximum}的递增正整数")
        values[name].append(numbers)
        positions[name].append(line_number)
    if not flat_rule:
        raise EquipmentWashError(f"{source_name}：缺少攻击/魔法/道术上限一半规则")
    affixes = list(_AFFIXES[:3])
    for affix in _AFFIXES[3:]:
        rows = values[affix.name]
        if len(rows) != len(affix.tiers):
            raise EquipmentWashError(f"{source_name} 第{positions[affix.name]}行：{affix.name}应有{len(affix.tiers)}档数值，实有{len(rows)}档")
        if any(rows[i][0] <= rows[i-1][-1] for i in range(1,len(rows))):
            raise EquipmentWashError(f"{source_name} 第{positions[affix.name]}行：{affix.name}各档数值需递增且不能重复或重叠")
        if affix.name == "攻速突破" and rows != [(1,)]:
            raise EquipmentWashError(f"{source_name} 第{positions[affix.name]}行：攻速突破当前只支持+1；更大值需独立引擎验收")
        tiers = tuple((*row, spec[-1]) for row, spec in zip(rows, affix.tiers))
        affixes.append(WashAffix(affix.name, tiers, affix.native_new_item_index))
    return WashCatalog(tuple(affixes))


TEXTVAR_LINES = {
    "攻击": 43,
    "魔法": 44,
    "道术": 45,
    "攻击速度": 46,
    "处决": 47,
    "处决时间": 48,
    "处决伤害": 49,
    "韧性": 50,
    "攻击加成": 51,
    "吸血": 52,
    "最大爆率": 53,
    "伤害系数": 54,
    "伤害吸收上限": 55,
    "攻速突破": 40,
}


def _core_call(label: str) -> str:
    return f"#CALL [\\玄渊实验室\\装备洗练\\洗练词条随机核心.txt] @{label}"


def _picker_reset() -> list[str]:
    return [
        "#IF",
        "#ACT",
        "MOV N$XY_WASH_PICK_LINE 0",
        "MOV N$XY_WASH_PICK_VALUE 0",
        "MOV N$XY_WASH_PICK_NATIVE -1",
    ]


def _set_pick(line: int, value: str, native: int | None = None) -> list[str]:
    result = [f"MOV N$XY_WASH_PICK_LINE {line}", f"MOV N$XY_WASH_PICK_VALUE {value}"]
    if native is not None:
        result.append(f"MOV N$XY_WASH_PICK_NATIVE {native}")
    result.append("BREAK")
    return result


def _two_tier(line: int, low: int, high: int, native: int | None = None) -> list[str]:
    return [
        "#IF",
        "RANDOMEX 80 100",
        "#ACT",
        *_set_pick(line, str(low), native),
        "#IF",
        "#ACT",
        *_set_pick(line, str(high), native),
        "",
    ]


def _three_tier(line: int, values: tuple[int, int, int] = (1, 2, 3)) -> list[str]:
    return [
        "#IF",
        "RANDOMEX 40 100",
        "#ACT",
        *_set_pick(line, str(values[0])),
        "#IF",
        "RANDOMEX 40 60",
        "#ACT",
        *_set_pick(line, str(values[1])),
        "#IF",
        "#ACT",
        *_set_pick(line, str(values[2])),
        "",
    ]


def _flat_pick(box: int, property_name: str, line: int) -> list[str]:
    # Preserve the existing current-item maximum contract.
    ability = {"攻击": "HDC", "魔法": "HMC", "道术": "HSC"}[property_name]
    return [
        f"FORMULATION <$BOXITEM[{box}].{ability}>/2 N$XY_WASH_PICK_MAX",
        "#IF",
        "#ACT",
        "MOVR N$XY_WASH_PICK_VALUE 1 <$STR(N$XY_WASH_PICK_MAX)>",
        f"MOV N$XY_WASH_PICK_LINE {line}",
        "BREAK",
        "",
    ]


def _normal_picker(box: int, label: str, catalog: WashCatalog) -> list[str]:
    choices: list[tuple[str | None, list[str]]] = [
        ("HDC", _flat_pick(box, "攻击", 43)),
        ("HMC", _flat_pick(box, "魔法", 44)),
        ("HSC", _flat_pick(box, "道术", 45)),
    ]
    for affix in catalog.affixes[3:-1]:
        line = TEXTVAR_LINES.get(affix.name, 0)
        if affix.name == "攻击加成":
            low, high = affix.tiers
            choices.append((None, [
                "#IF", "RANDOMEX 80 100", "#ACT",
                f"MOVR N$XY_WASH_PICK_VALUE {low[0]} {low[1]}", f"MOV N$XY_WASH_PICK_LINE {line}", "BREAK",
                "#IF", "#ACT", f"MOVR N$XY_WASH_PICK_VALUE {high[0]} {high[1]}", f"MOV N$XY_WASH_PICK_LINE {line}", "BREAK", "",
            ]))
        elif len(affix.tiers) == 3:
            choices.append((None, _three_tier(line, tuple(t[0] for t in affix.tiers))))
        else:
            choices.append((None, _two_tier(line, affix.tiers[0][0], affix.tiers[1][0], affix.native_new_item_index)))
    fixed_count = len(catalog.affixes[3:-1])
    if len(choices) != NORMAL_CATEGORY_COUNT or fixed_count != len(choices) - 3:
        raise EquipmentWashError("洗练词条实际目录数量与普通等权选择器不一致")
    result = [
        f"[@{label}]", "{", "#IF", "#ACT",
        f"MOV N$XY_WASH_VALID_COUNT {fixed_count}",
    ]
    for ability, _ in choices[:3]:
        result.extend(("#IF", f"LARGE <$BOXITEM[{box}].{ability}> 1", "#ACT", "INC N$XY_WASH_VALID_COUNT 1"))
    # Rejection sampling over invalid flat categories is equivalent to equal
    # sampling over valid categories. Sequential 1/remaining choices avoid an
    # unverified MOVR endpoint convention and an import-time recursive CALL.
    for index, (ability, _) in enumerate(choices):
        condition = [f"LARGE <$BOXITEM[{box}].{ability}> 1"] if ability else []
        result.extend(("#IF", *condition,
                       "RANDOMEX 1 <$STR(N$XY_WASH_VALID_COUNT)>", "#ACT",
                       _core_call(f"{label}_CATEGORY_{index}"), "BREAK"))
        result.extend(("#IF", *condition, "#ACT", "DEC N$XY_WASH_VALID_COUNT 1"))
    result.extend(("}", ""))
    for index, (_, choice) in enumerate(choices):
        result.extend((f"[@{label}_CATEGORY_{index}]", "{", "#IF", "#ACT", *choice, "}", ""))
    return result


def render_random_core(catalog: WashCatalog) -> str:
    """Render deterministic LFM2 random branches from the imported TXT contract."""
    required = {item.name for item in _AFFIXES}
    if {item.name for item in catalog.affixes} != required:
        raise EquipmentWashError("洗练词条TXT与1.1固定实效映射不一致")
    lines = [
        "; 玄渊装备洗练1.2：TXT导入后的随机词条核心。",
        "; 外部脚本只使用显式CALL；普通有效类别等权；攻速突破每词条独立千分之一。",
        "[@XY_WASH_PICK_27]",
        "{",
        *_picker_reset(),
        "#IF",
        "RANDOMEX 1 1000",
        "#ACT",
        _core_call("XY_WASH_PICK_BREAKTHROUGH_27"),
        "BREAK",
        "#IF",
        "#ACT",
        _core_call("XY_WASH_PICK_NORMAL_27"),
        "BREAK",
        "}",
        "",
        "[@XY_WASH_PICK_BREAKTHROUGH_27]", "{", "#IF", "#ACT",
        *_set_pick(40, "1"), "}", "",
        *_normal_picker(27, "XY_WASH_PICK_NORMAL_27", catalog),
        "",
        "[@XY_WASH_PICK_28]",
        "{",
        *_picker_reset(),
        "#IF",
        "RANDOMEX 1 1000",
        "#ACT",
        _core_call("XY_WASH_PICK_BREAKTHROUGH_28"),
        "BREAK",
        "#IF",
        "#ACT",
        _core_call("XY_WASH_PICK_NORMAL_28"),
        "BREAK",
        "}",
        "",
        "[@XY_WASH_PICK_BREAKTHROUGH_28]", "{", "#IF", "#ACT",
        *_set_pick(40, "1"), "}", "",
        *_normal_picker(28, "XY_WASH_PICK_NORMAL_28", catalog),
    ]
    return "\n".join(lines) + "\n"


def render_effect_core() -> str:
    """Render only the runtime aggregation supported by this target server."""
    return """; 玄渊装备洗练1.1：已穿戴装备词条实效汇总。
; 仅重算临时叠加值；不读取或改写角色数据库。

[@XY_WASH_APPLY_ABIL]
{
#IF
EQUAL N$XY_WASH_ABIL_BUSY 1
#ACT
BREAK
#IF
#ACT
MOV N$XY_WASH_ABIL_BUSY 1
GetAllCustomItemValueByTextLine 60 -1 43 N$XY_WASH_TMP N$XY_WASH_ATTACK_UP N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 44 N$XY_WASH_TMP N$XY_WASH_MAGIC_UP N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 45 N$XY_WASH_TMP N$XY_WASH_TAO_UP N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 51 N$XY_WASH_TMP N$XY_WASH_ABILITY_PERCENT N$XY_WASH_TMP
ChangeHumAbility 6 = <$STR(N$XY_WASH_ATTACK_UP)>
ChangeHumAbility 8 = <$STR(N$XY_WASH_MAGIC_UP)>
ChangeHumAbility 10 = <$STR(N$XY_WASH_TAO_UP)>
INC N$XY_WASH_ABILITY_PERCENT 100
ChangeHumAbilityPercentage 5 = <$STR(N$XY_WASH_ABILITY_PERCENT)>
ChangeHumAbilityPercentage 6 = <$STR(N$XY_WASH_ABILITY_PERCENT)>
ChangeHumAbilityPercentage 7 = <$STR(N$XY_WASH_ABILITY_PERCENT)>
ChangeHumAbilityPercentage 8 = <$STR(N$XY_WASH_ABILITY_PERCENT)>
ChangeHumAbilityPercentage 9 = <$STR(N$XY_WASH_ABILITY_PERCENT)>
ChangeHumAbilityPercentage 10 = <$STR(N$XY_WASH_ABILITY_PERCENT)>
MOV N$XY_WASH_ABIL_BUSY 0
BREAK
}

[@XY_WASH_ADD_ATTACK]
{
#IF
#ACT
GetAllCustomItemValueByTextLine 60 -1 47 N$XY_WASH_TMP N$XY_WASH_EXEC_CHANCE N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 48 N$XY_WASH_TMP N$XY_WASH_EXEC_TIME N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 49 N$XY_WASH_TMP N$XY_WASH_EXEC_DAMAGE N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 53 N$XY_WASH_TMP N$XY_WASH_DROP_MAX N$XY_WASH_TMP
GetAllCustomItemValueByTextLine 60 -1 54 N$XY_WASH_TMP N$XY_WASH_DAMAGE_COEFF N$XY_WASH_TMP
FORMULATION <$STR(N$XY_WASH_EXEC_CHANCE)>*100 N$XY_WASH_EXEC_CHANCE_BP
FORMULATION <$STR(N$XY_WASH_EXEC_TIME)>*1000 N$XY_WASH_EXEC_TIME_MS
INC N$XY_EXEC_ChanceBP <$STR(N$XY_WASH_EXEC_CHANCE_BP)>
INC N$XY_EXEC_PVEEquipBonusPercent <$STR(N$XY_WASH_EXEC_DAMAGE)>
INC N$XY_EXEC_PVEEquipDurationMs <$STR(N$XY_WASH_EXEC_TIME_MS)>
INC N$XY_RT_DropMax <$STR(N$XY_WASH_DROP_MAX)>
INC N$XY_RT_DamageCoeff <$STR(N$XY_WASH_DAMAGE_COEFF)>
BREAK
}

[@XY_WASH_ADD_DROP_UI]
{
#IF
#ACT
GetAllCustomItemValueByTextLine 60 -1 53 N$XY_WASH_TMP N$XY_WASH_DROP_MAX N$XY_WASH_TMP
INC N$XY_最大爆率 <$STR(N$XY_WASH_DROP_MAX)>
BREAK
}

[@XY_WASH_ADD_SUSTAIN]
{
#IF
#ACT
GetAllCustomItemValueByTextLine 60 -1 52 N$XY_WASH_TMP N$XY_WASH_LIFESTEAL N$XY_WASH_TMP
INC N$XY_SUS_LifeSteal <$STR(N$XY_WASH_LIFESTEAL)>
BREAK
}

[@XY_WASH_ADD_TOUGHNESS]
{
#IF
#ACT
GetAllCustomItemValueByTextLine 60 -1 50 N$XY_WASH_TMP N$XY_WASH_TOUGHNESS N$XY_WASH_TMP
INC N$XY_EXEC_Toughness <$STR(N$XY_WASH_TOUGHNESS)>
BREAK
}

[@XY_WASH_ADD_MONSTER_ABSORB]
{
#IF
#ACT
GetAllCustomItemValueByTextLine 60 -1 55 N$XY_WASH_TMP N$XY_WASH_MONSTER_ABSORB N$XY_WASH_TMP
INC N$XY_MDA_CapBonus <$STR(N$XY_WASH_MONSTER_ABSORB)>
BREAK
}
"""


def _pick_and_store(slot: int, box: int) -> list[str]:
    return [*_picker_reset(), _core_call(f"XY_WASH_PICK_{box}"), "#IF", "#ACT",
            f"MOV N$XY_WASH_LINE{slot} <$STR(N$XY_WASH_PICK_LINE)>",
            f"MOV N$XY_WASH_VALUE{slot} <$STR(N$XY_WASH_PICK_VALUE)>",
            f"MOV N$XY_WASH_NATIVE{slot} <$STR(N$XY_WASH_PICK_NATIVE)>"]


def _reset_temporary_rows() -> list[str]:
    lines = ["; XY-WASH-TEMP-RESET-BEGIN"]
    for slot in range(8):
        lines.extend((f"MOV N$XY_WASH_LINE{slot} 0", f"MOV N$XY_WASH_VALUE{slot} 0", f"MOV N$XY_WASH_NATIVE{slot} -1"))
    lines.extend(("MOV N$XY_WASH_PICK_LINE 0", "MOV N$XY_WASH_PICK_VALUE 0", "MOV N$XY_WASH_PICK_NATIVE -1", "MOV N$XY_WASH_PICK_MAX 0", "; XY-WASH-TEMP-RESET-END"))
    return lines


def _without_temporary_reset(text: str) -> str:
    return re.sub(r"(?ms)^; XY-WASH-TEMP-RESET-BEGIN\n.*?^; XY-WASH-TEMP-RESET-END\n", "", text)


def _clear_custom_rows(box: int) -> list[str]:
    lines: list[str] = []
    for slot in range(8):
        lines.extend((
            f"SetCustomItemValue boxitem{box} {slot} = 0",
            f"SetCustomItemAbil boxitem{box} {slot} 0 0",
            f"SetCustomItemAbil boxitem{box} {slot} 1 0",
            f"SetCustomItemAbil boxitem{box} {slot} 2 0",
            f"SetCustomItemAbil boxitem{box} {slot} 3 0",
            f"SetCustomItemAbil boxitem{box} {slot} 4 0",
        ))
    return lines


def _write_dynamic_rows(box: int, count: int, color: str, quality: str, stars: str) -> list[str]:
    lines = [
        "#IF",
        "#ACT",
        f"SetUpgradeItem {box}",
        *[f"SetNewItemValue boxitem{box} {index} = 0"
          for index in (list(range(12)) + [21] if box == 27 else [0, 21])],
        *([f"SetCustomItemValue boxitem{box} {slot} = 0" for slot in (8, 9)] if box == 27 else []),
        f"SetCustomItemText boxitem{box} [装备品质:{quality}]",
        f"SetCustomItemTextColor boxitem{box} {color}",
        *_clear_custom_rows(box),
    ]
    for slot in range(count):
        for native in (0, 21):
            lines.extend(("#IF", f"LARGE N$XY_WASH_EXPECTED {slot}",
                          f"EQUAL N$XY_WASH_NATIVE{slot} {native}", "#ACT",
                          f"SetNewItemValue boxitem{box} {native} + <$STR(N$XY_WASH_VALUE{slot})>"))
        lines.extend((
            "#IF",
            f"LARGE N$XY_WASH_LINE{slot} 0",
            "#ACT",
            f"SetCustomItemAbil boxitem{box} {slot} 0 {color}",
            f"SetCustomItemAbil boxitem{box} {slot} 1 60",
            f"SetCustomItemAbil boxitem{box} {slot} 2 <$STR(N$XY_WASH_LINE{slot})>",
            f"SetCustomItemAbil boxitem{box} {slot} 3 0",
            f"SetCustomItemAbil boxitem{box} {slot} 4 9",
            f"SetCustomItemValueEx boxitem{box} {slot} = <$STR(N$XY_WASH_LINE{slot})> <$STR(N$XY_WASH_VALUE{slot})> 0",
        ))
    lines.extend((
        "#IF",
        "#ACT",
        f"ChangeItemUpgradeCount boxitem{box} = {stars}",
        "MOV N$XY_WASH_BUSY_V2 0" if box == 27 else "MOV N$XYEW_O_开光锁 0",
        f"UpdateItem boxitem{box}",
    ))
    return lines


def _validate_results(box: int, allow_unopened: bool = False) -> list[str]:
    lock = "N$XY_WASH_BUSY_V2" if box == 27 else "N$XYEW_O_开光锁"
    lines = ["#IF", "#ACT", "MOV N$XY_WASH_RESULT_VALID 1",
             "#IF", "LARGE N$XY_WASH_EXPECTED 8", "#ACT", "MOV N$XY_WASH_RESULT_VALID 0",
             "#IF", "SMALL N$XY_WASH_EXPECTED 1"]
    if allow_unopened:
        lines.append("NOT EQUAL N$XY_WASH_ALLOW_ZERO 1")
    lines.extend(("#ACT", "MOV N$XY_WASH_RESULT_VALID 0"))
    for slot in range(8):
        lines.extend(("#IF", "#ACT", "MOV N$XY_WASH_SLOT_VALID 0"))
        for native in (0, 21):
            lines.extend(("#IF", f"EQUAL N$XY_WASH_NATIVE{slot} {native}",
                          f"EQUAL N$XY_WASH_LINE{slot} 0", f"LARGE N$XY_WASH_VALUE{slot} 0",
                          "#ACT", "MOV N$XY_WASH_SLOT_VALID 1"))
        for conditions in [(f"EQUAL N$XY_WASH_LINE{slot} 40",),
                           (f"LARGE N$XY_WASH_LINE{slot} 42", f"SMALL N$XY_WASH_LINE{slot} 56")]:
            lines.extend(("#IF", *conditions, f"EQUAL N$XY_WASH_NATIVE{slot} -1",
                          f"LARGE N$XY_WASH_VALUE{slot} 0", "#ACT", "MOV N$XY_WASH_SLOT_VALID 1"))
        lines.extend(("#IF", f"LARGE N$XY_WASH_EXPECTED {slot}",
                      "EQUAL N$XY_WASH_SLOT_VALID 0", "#ACT", "MOV N$XY_WASH_RESULT_VALID 0"))
    lines.extend(("#IF", "EQUAL N$XY_WASH_RESULT_VALID 0", "#ACT", f"MOV {lock} 0",
                  "MESSAGEBOX 词条生成失败，本次未扣费、未修改装备，请联系管理员。" if box == 27
                  else "MESSAGEBOX 开光词条生成失败，请联系管理员。", "BREAK"))
    return lines


def _charge_wash() -> list[str]:
    return ["#IF", "NOT CHECKGAMEGOLD > 99", "#ACT", "MOV N$XY_WASH_BUSY_V2 0",
            "MESSAGEBOX 洗练装备需要100元宝，本次未修改装备。", "BREAK",
            "#IF", "#ACT", "GAMEGOLD - 100"]


def _render_main_tail() -> str:
    lines = [f"; {_IMPORT_MARKER}-BEGIN", "[@洗练给予属性]",
             *_validate_results(27, allow_unopened=True), *_charge_wash(),
             *_write_dynamic_rows(27, 8, "<$STR(S$XYEW_W_词缀颜色)>",
                                  "<$STR(S$XYEW_W_装备词缀)>", "<$STR(N$XYEW_W_洗练星星)>"),
             "#IF", "EQUAL N$XY_WASH_ALLOW_ZERO 1", "#ACT", "ReturnBoxItem 27",
             "MESSAGEBOX <$STR(S$XY_WASH_QUALITY_MESSAGE)>", "BREAK",
             "#IF", "#ACT", "SENDMSG 7 提示：洗练成功，请移动装备上查看属性！！！", "BREAK", "",
             "[@XY_WASH_COLLECT]"]
    for slot, numeral in enumerate("一二三四五六七八"):
        lines.extend(("#IF", f"LARGE N$XY_WASH_EXPECTED {slot}", "#ACT", f"GOTO @获取属性{numeral}"))
    lines.extend(("#IF", "#ACT", "BREAK", ""))
    for slot, numeral in enumerate("一二三四五六七八"):
        lines.extend((f"[@获取属性{numeral}]", *_pick_and_store(slot, 27), "BREAK", ""))
    lines.append(f"; {_IMPORT_MARKER}-END")
    return "\n".join(lines) + "\n"


def render_main_script(before: str) -> str:
    before = before.replace("\r\n", "\n").replace("\r", "\n")
    if "[@XYEW_WASH_EXEC]" not in before or "[@洗练给予属性]" not in before:
        raise EquipmentWashError("装备洗练主脚本缺少已知入口锚点")
    # Preserve the registered UI and box trigger; replace only the wash execution.
    lines = [before.split("[@XYEW_WASH_EXEC]", 1)[0].rstrip(), "", "[@XYEW_WASH_EXEC]",
             "#IF", "EQUAL <$BOXITEM[27].NAME>", "#ACT", "MESSAGEBOX 请先放入装备在洗练!", "BREAK",
             "#IF", "NOT CHECKGAMEGOLD > 99", "#ACT", "MESSAGEBOX 洗练装备需要100元宝", "BREAK",
             "#IF", "EQUAL N$XY_WASH_BUSY_V2 1", "#ACT", "BREAK",
             "#IF", "#ACT", "MOV N$XY_WASH_BUSY_V2 1", "MOV N$XY_WASH_ALLOW_ZERO 0",
             "MOV N$XY_WASH_EXPECTED 0", *_reset_temporary_rows(),
             "GOTO @区分级别洗练", "BREAK", "", "[@区分级别洗练]"]
    for chance, quality, color, stars, message in [
        (350, "神佑未开光", 125, 8, "您得到了天神的庇佑，获得了神佑属性。"),
        (300, "天赐未开光", 31, 7, "您得到了天神的赐福，获得了天赐属性。")]:
        lines.extend(("#IF", f"RANDOM {chance}", "#ACT", "MOV N$XY_WASH_ALLOW_ZERO 1",
                      "MOV N$XY_WASH_EXPECTED 0", f"MOV S$XYEW_W_装备词缀 {quality}",
                      f"MOV S$XYEW_W_词缀颜色 {color}", f"MOV N$XYEW_W_洗练星星 {stars}",
                      f"MOV S$XY_WASH_QUALITY_MESSAGE {message}", "GOTO @洗练给予属性", "BREAK"))
    for chance, name in [(250, "圣级"), (150, "仙级")]:
        lines.extend(("#IF", f"RANDOM {chance}", "#ACT",
                      f"#CALL [\\玄渊实验室\\装备洗练\\{name}直出.txt] @{name}特殊", "BREAK"))
    lines.extend(("#IF", "#ACT", "MOV S$XYEW_W_装备词缀 普通", "MOV N$XYEW_W_属性条数 1",
                  "MOV S$XYEW_W_词缀颜色 151", "MOV N$XYEW_W_洗练星星 1"))
    for chance, quality, low, high, color, stars in [(3,"灵级",1,3,215,2),(5,"上古",2,4,253,3),(10,"传说",2,5,70,4)]:
        lines.extend(("#IF", f"RANDOM {chance}", "#ACT", f"MOV S$XYEW_W_装备词缀 {quality}",
                      f"MOVR N$XYEW_W_属性条数 {low} {high}", f"MOV S$XYEW_W_词缀颜色 {color}",
                      f"MOV N$XYEW_W_洗练星星 {stars}"))
    lines.extend(("#IF", "#ACT", "MOV N$XY_WASH_EXPECTED <$STR(N$XYEW_W_属性条数)>",
                  "GOTO @XY_WASH_COLLECT", "GOTO @洗练给予属性", "BREAK", "", _render_main_tail()))
    return "\n".join(lines) + "\n"


def render_direct_script(label: str, box: int, quality: str, color: int, stars: int, success_message: str) -> str:
    lines = [f"; {_IMPORT_MARKER}: 同步生成、完整校验后提交。", f"[@{label}]", "{",
             "#IF", "#ACT", *_reset_temporary_rows(), f"MOV N$XY_WASH_EXPECTED {stars}"]
    for slot in range(stars):
        lines.extend(_pick_and_store(slot, box))
    lines.extend(_validate_results(box))
    if box == 27:
        lines.extend(_charge_wash())
    lines.extend((*_write_dynamic_rows(box, stars, str(color), quality, str(stars)),
                  "CLOSE", f"MESSAGEBOX {success_message}", "BREAK", "}"))
    return "\n".join(lines) + "\n"


def _append_managed_block(text: str, marker: str, lines: list[str]) -> tuple[str, str]:
    block = _managed_block(marker, lines)
    begin = f"; {marker}-BEGIN"
    end = f"; {marker}-END"
    start = text.find(begin)
    finish = text.find(end)
    if start >= 0 or finish >= 0:
        if start < 0 or finish < start or text.find(begin, start + 1) >= 0 or text.find(end, finish + 1) >= 0:
            raise EquipmentWashError(f"受管块{marker}重复或残缺")
        return text[:start] + block + text[finish + len(end):], block
    return text.rstrip("\n") + "\n\n" + block + "\n", block


def _patch_qfunction(text: str) -> tuple[str, list[str], list[str]]:
    operations = (
        ("PlayLogin", "XY-EQUIPMENT-WASH-IMPORT-V1-LOGIN", ("#IF", "#ACT", "DELAYGOTO 1500 @XY_WASH_RECALC_DELAY")),
        ("TakeOnEx", "XY-EQUIPMENT-WASH-IMPORT-V1-TAKEON", ("#IF", "#ACT", "DELAYGOTO 200 @XY_WASH_RECALC_DELAY")),
        ("TakeOffEx", "XY-EQUIPMENT-WASH-IMPORT-V1-TAKEOFF", ("#IF", "#ACT", "DELAYGOTO 200 @XY_WASH_RECALC_DELAY")),
    )
    markers: list[str] = []
    blocks: list[str] = []
    patched = text
    for label, marker, lines in operations:
        patched, block = _upsert_after_label(patched, label, marker, lines)
        markers.append(marker); blocks.append(block)
    for anchor, marker, lines in (
        ("MOV N$XY_RT_DamageCoeff 100", "XY-EQUIPMENT-WASH-IMPORT-V1-ATTACK", ("#CALL [\\玄渊实验室\\装备洗练\\洗练词条实效核心.txt] @XY_WASH_ADD_ATTACK",)),
        ("MOV N$XY_最大爆率 100", "XY-EQUIPMENT-WASH-IMPORT-V1-DROP", ("#CALL [\\玄渊实验室\\装备洗练\\洗练词条实效核心.txt] @XY_WASH_ADD_DROP_UI",)),
        ("MOV N$XY_SUS_LifeStealHeal 0", "XY-EQUIPMENT-WASH-IMPORT-V1-SUSTAIN", ("#CALL [\\玄渊实验室\\装备洗练\\洗练词条实效核心.txt] @XY_WASH_ADD_SUSTAIN",)),
        ("; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR", "XY-EQUIPMENT-WASH-IMPORT-V1-TOUGHNESS", ("#CALL [\\玄渊实验室\\装备洗练\\洗练词条实效核心.txt] @XY_WASH_ADD_TOUGHNESS",)),
        ("MOV N$XY_MDA_Final 0", "XY-EQUIPMENT-WASH-IMPORT-V1-MONSTER-ABSORB", ("#CALL [\\玄渊实验室\\装备洗练\\洗练词条实效核心.txt] @XY_WASH_ADD_MONSTER_ABSORB",)),
    ):
        patched, block = _upsert_after_anchor(patched, anchor, marker, lines)
        markers.append(marker); blocks.append(block)
    marker = "XY-EQUIPMENT-WASH-IMPORT-V1-RECALC-LABEL"
    patched, block = _append_managed_block(patched, marker, [
        "[@XY_WASH_RECALC_DELAY]", "#IF", "#ACT",
        "#CALL [\\玄渊实验室\\装备洗练\\洗练词条实效核心.txt] @XY_WASH_APPLY_ABIL", "BREAK",
    ])
    markers.append(marker); blocks.append(block)
    return patched, markers, blocks


def _patch_attack_speed_core(text: str) -> tuple[str, str]:
    return _upsert_after_anchor(
        text, "MOV N$XY_AS_RAW <$HITSPD>", "XY-EQUIPMENT-WASH-IMPORT-V1-NORMAL-SPEED",
        (
            "MOV N$XY_WASH_AS_TMP 0", "MOV N$XY_WASH_AS_NORMAL 0",
            "GetAllCustomItemValueByTextLine 60 -1 46 N$XY_WASH_AS_TMP N$XY_WASH_AS_NORMAL N$XY_WASH_AS_TMP",
            "INC N$XY_AS_RAW <$STR(N$XY_WASH_AS_NORMAL)>",
        ),
    )


def _patch_textvar(text: str) -> tuple[str, list[str], list[str]]:
    labels = {
        43: "{攻击上限∶|251}+$$2", 44: "{魔法上限∶|251}+$$2", 45: "{道术上限∶|251}+$$2",
        46: "{攻击速度∶|251}+$$2", 47: "{处决几率∶|251}+$$2%", 48: "{处决时间∶|251}+$$2秒",
        49: "{处决伤害∶|251}+$$2%", 50: "{韧性∶|251}+$$2", 51: "{攻击加成∶|251}+$$2%",
        52: "{攻击吸血∶|251}+$$2%", 53: "{最大爆率∶|251}+$$2%", 54: "{伤害系数∶|251}+$$2%",
        55: "{伤害吸收上限∶|251}+$$2%",
    }
    source_lines = text.splitlines()
    while len(source_lines) < 55:
        source_lines.append("")
    before = source_lines[42:55]
    for offset, expected in enumerate(labels.values()):
        current = before[offset].strip()
        if current and current != expected:
            raise EquipmentWashError(f"TextVar第{43 + offset}行已被其他系统占用，禁止覆盖")
    after = list(labels.values())
    source_lines[42:55] = after
    return "\n".join(source_lines), before, after


VERSION = "1.2.0-candidate.3"
STATE_RELATIVE = Path(".xydp/equipment-wash-import.json")
PARAMETER_FILENAME = "洗练目标参数.json"
DIRECT_SPECS = (
    ("仙级直出.txt", "仙级特殊", 27, "仙级", 242, 5, "洗练成功，获得了仙级属性。"),
    ("圣级直出.txt", "圣级特殊", 27, "圣级", 249, 6, "洗练成功，获得了圣级属性。"),
    ("天赐开光.txt", "天赐特殊", 28, "天赐", 31, 7, "开光成功，获得了天赐属性。"),
    ("神佑开光.txt", "神佑特殊", 28, "神佑", 125, 8, "开光成功，获得了神佑属性。"),
)
CHINESE_PARAMETERS = {
    "洗练NPC脚本": "wash_npc_script", "洗练NPC名称": "wash_npc_display", "洗练地图": "wash_npc_map",
    "洗练坐标X": "wash_npc_x", "洗练坐标Y": "wash_npc_y", "洗练NPC外观": "wash_npc_appearance",
    "开光NPC脚本": "open_npc_script", "开光NPC名称": "open_npc_display", "开光地图": "open_npc_map",
    "开光坐标X": "open_npc_x", "开光坐标Y": "open_npc_y", "开光NPC外观": "open_npc_appearance",
    "洗练核心目录": "wash_core_directory", "攻速核心路径": "attack_speed_core_relative",
}


@dataclass(frozen=True)
class WashInstallPlan(DualInstallPlan):
    input_hashes: tuple[tuple[Path, str], ...] = ()
    target_parameters: dict[str, Any] = field(default_factory=dict)
    external_calls: tuple[tuple[str, str], ...] = ()


def _checked_path(root: Path, relative: Path) -> Path:
    raw = root / relative
    if relative.is_absolute() or ".." in relative.parts:
        raise EquipmentWashError(f"目标路径越界：{relative}")
    for part in (raw, *raw.parents):
        if part.exists() and (part.is_symlink() or getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise EquipmentWashError(f"禁止路径链接：{part}")
        if part == root:
            break
    return _target(root, relative)


def _npc_relative(params: dict[str, Any], kind: str) -> Path:
    return Path(f"Mir200/Envir/Market_Def/{params[kind + '_npc_script']}-{params[kind + '_npc_map']}.txt")


def _adapt_script(text: str, params: dict[str, Any], index: int = 12) -> str:
    directory = str(params["wash_core_directory"]).replace("/", "\\")
    text = text.replace("\\玄渊实验室\\装备洗练\\", "\\" + directory + "\\")
    text = text.replace("OPENMERCHANTBIGDLG 12 ", f"OPENMERCHANTBIGDLG {index} ")
    text = text.replace("<ITEMBOX:27:12:", f"<ITEMBOX:27:{index}:").replace("<ITEMBOX:28:12:", f"<ITEMBOX:28:{index}:")
    # Keep prices, quality selection, ITEMBOX layout and opening costs from the accepted templates.
    text = text.replace("<&Text:装备洗练:24:10", f"<&Text:{params['wash_npc_display']}:24:10")
    return text.replace("<&Text:装备开光:24:10", f"<&Text:{params['open_npc_display']}:24:10")


def check_external_calls(scripts: dict[Path, str], read_script) -> tuple[tuple[str, str], ...]:
    """Validate actual static external CALL targets, not unrelated internal GOTO labels.

    read_script(relative) must be a read-only target reader and also record its input hash.
    Only the generated/inserted callers are roots; recursively follow their external calls.
    """
    pending = list(scripts.items())
    seen: set[Path] = set()
    calls: set[tuple[str, str]] = set()
    while pending:
        caller, text = pending.pop()
        if caller in seen:
            continue
        seen.add(caller)
        for line in text.splitlines():
            if not re.match(r"(?i)^\s*#CALL\b", line):
                continue
            match = re.fullmatch(r"\s*#CALL\s+\[([^\]]+)\]\s+(@[^\s;]+)\s*(?:;.*)?", line, re.I)
            if not match:
                raise EquipmentWashError(f"外部CALL无法静态解析：{caller}: {line}")
            name, label = match.groups()
            if any(c in name for c in ("<", ">", "$", ":")):
                raise EquipmentWashError(f"外部CALL路径不支持动态表达式：{name}")
            relative = Path("Mir200/Envir/QuestDiary") / name.replace("\\", "/").lstrip("/")
            if ".." in relative.parts:
                raise EquipmentWashError(f"外部CALL路径越界：{name}")
            target = scripts.get(relative)
            if target is None:
                target = read_script(relative)
            labels = list(re.finditer(rf"(?m)^\[{re.escape(label)}\][ \t]*$", target))
            if len(labels) != 1:
                raise EquipmentWashError(f"外部CALL目标标签缺失或重复：{relative} {label}")
            body = target[labels[0].end():].lstrip("\n \t")
            # The matching outer block must close before the next top-level label.
            if not body.startswith("{\n"):
                raise EquipmentWashError(f"外部CALL目标缺少脚本块：{relative} {label}")
            block_end = re.search(r"(?m)^\}[ \t]*(?:\n|$)", body)
            next_label = re.search(r"(?m)^\[@[^\]]+\]", body)
            if block_end is None or (next_label and next_label.start() < block_end.start()):
                raise EquipmentWashError(f"外部CALL目标脚本块不完整：{relative} {label}")
            if not body[2:block_end.start()].strip():
                raise EquipmentWashError(f"外部CALL目标脚本块为空：{relative} {label}")
            calls.add((relative.as_posix(), label))
            pending.append((relative, target))
    return tuple(sorted(calls))


def _strict_managed_patch(before: str, builder, required_existing: bool = False):
    from .mingge_dual import _find_block
    after, markers, blocks = builder(before)
    for marker, expected in zip(markers, blocks):
        found = _find_block(before, marker)
        if found and before[slice(*found)] != expected:
            raise EquipmentWashError(f"受管块发生未知手改：{marker}")
        if required_existing and not found:
            raise EquipmentWashError(f"已安装受管块缺失：{marker}")
    return after


class EquipmentWashImportService(_DualService):
    route = ROUTE
    package_id = PACKAGE_ID

    def preflight(self, server: Path, source: Path, *, client: Path | None = None,
                  parameters: dict[str, Any] | None = None) -> WashInstallPlan:
        blockers: list[str] = []
        warnings = [
            "candidate：保留9月5日规则与原NPC收费/品质/开光流程，仍缺M2与游戏验收。",
            "只生成后续洗练入口与实例词条；不扫描角色数据库、不改写历史装备。",
            "客户端工作台资源须先由独立资源事务准备；本路由只读校验，不写客户端。",
        ]
        changes = []
        watched: dict[Path, str] = {}
        root = Path(server).absolute()
        document = Path(source).absolute()
        params: dict[str, Any] = {}
        calls: tuple[tuple[str, str], ...] = ()

        def read(path: Path, required: bool = True) -> bytes | None:
            path = _checked_path(path.parent, Path(path.name))
            if path in watched:
                data = path.read_bytes() if path.is_file() else None
                if _sha256(data) != watched[path]:
                    raise EquipmentWashError(f"预检期间输入发生变化：{path}")
            else:
                data = path.read_bytes() if path.is_file() else None
                watched[path] = _sha256(data)
            if required and data is None:
                raise EquipmentWashError(f"依赖文件不存在：{path}")
            return data

        def target_read(relative: Path, required: bool = True):
            return read(_checked_path(root, relative), required)

        def stage(relative: Path, after: bytes):
            before = target_read(relative, False)
            if before != after:
                changes.append(_change(root, relative, "exclusive", before, after))

        try:
            if not (root / "Mir200/Envir").is_dir():
                raise EquipmentWashError("目标目录不是可识别的翎风/LFM2服务端")
            source_data = read(document)
            catalog = parse_wash_affix_text(source_data.decode("utf-8-sig"), source_name=str(document))
            # Load exactly one current package; duplicate IDs remain a repository error.
            from .repository import PackageRepository
            repository = PackageRepository(self.platform_root / "packages")
            repository.refresh()
            package = repository.packages.get(PACKAGE_ID)
            if package is None or package.install_route != ROUTE or package.version != VERSION or package.status != "candidate":
                raise EquipmentWashError("洗练包必须为1.2.0-candidate.2专项候选，拒绝旧版普通包payload")
            manifest_bytes = read(package.source_path)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            params = {key: spec["default"] for key, spec in package.parameters.items() if "default" in spec}
            state_before = target_read(STATE_RELATIVE, False)
            state = json.loads(state_before.decode("utf-8")) if state_before else None
            if state:
                if state.get("schema_version") != 1 or state.get("package_id") != PACKAGE_ID:
                    raise EquipmentWashError("洗练受管状态文件无效")
                params.update(state["parameters"])
            explicit: set[str] = set(parameters or {})
            adapter = document.parent / PARAMETER_FILENAME
            adapter_data = read(adapter, False)
            if adapter_data is not None:
                config = json.loads(adapter_data.decode("utf-8-sig"))
                if not isinstance(config, dict) or set(config) - set(CHINESE_PARAMETERS):
                    raise EquipmentWashError("洗练目标参数JSON包含未知中文字段")
                params.update({CHINESE_PARAMETERS[key]: value for key, value in config.items()})
                explicit.update(CHINESE_PARAMETERS[key] for key in config)
            if parameters:
                if set(parameters) - set(package.parameters):
                    raise EquipmentWashError("洗练目标参数包含未知字段")
                params.update(parameters)
            if not state:
                merchant = _script_text(target_read(Path("Mir200/Envir/MerChant.txt")))
                for kind in ("wash", "open"):
                    rows = [line.split() for line in merchant.splitlines() if line.split() and line.split()[0].replace("\\", "/") == params[kind + "_npc_script"]]
                    if len(rows) > 1:
                        raise EquipmentWashError(f"NPC注册重复：{params[kind + '_npc_script']}")
                    if rows:
                        row = rows[0]
                        if len(row) != 8 or row[5] != "0" or row[7] != "0":
                            raise EquipmentWashError("NPC注册格式与候选底座不兼容")
                        for suffix, value in zip(("_npc_map", "_npc_x", "_npc_y", "_npc_display", "_npc_appearance"), (row[1], int(row[2]), int(row[3]), row[4], int(row[6]))):
                            key = kind + suffix
                            if key not in explicit:
                                params[key] = value
            for key, spec in package.parameters.items():
                value = params.get(key)
                if spec.get("type") == "integer":
                    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
                        raise EquipmentWashError(f"目标参数{key}必须为0至65535的整数")
                elif not isinstance(value, str) or not value or not re.fullmatch(r"[\w\u4e00-\u9fff./-]+", value):
                    raise EquipmentWashError(f"目标参数{key}包含非法路径或脚本文字")
                if isinstance(value, str) and (value.startswith(("/", "\\")) or ".." in value.split("/") or "//" in value):
                    raise EquipmentWashError(f"目标参数{key}路径越界或不规范")
            for kind in ("wash", "open"):
                if "/" in params[kind + "_npc_map"]:
                    raise EquipmentWashError("地图编号不能包含路径分隔符")
            if _npc_relative(params, "wash") == _npc_relative(params, "open"):
                raise EquipmentWashError("洗练与开光NPC脚本路径不能相同")
            core_directory = Path("Mir200/Envir/QuestDiary") / params["wash_core_directory"]
            speed_relative = Path(params["attack_speed_core_relative"])
            if not speed_relative.as_posix().startswith("Mir200/Envir/QuestDiary/"):
                raise EquipmentWashError("攻速核心必须位于目标服QuestDiary目录")
            if state:
                if state.get("schema_version") != 1 or state.get("package_id") != PACKAGE_ID:
                    raise EquipmentWashError("洗练受管状态文件无效")
                # Renaming/moving an installed entry requires a separate migration transaction.
                for key in ("wash_npc_script", "wash_npc_map", "open_npc_script", "open_npc_map", "wash_core_directory", "attack_speed_core_relative"):
                    if state["parameters"].get(key) != params[key]:
                        raise EquipmentWashError(f"已安装目标参数{key}改变需要独立迁移，禁止遗留旧入口")

            # Preserve the accepted payment/quality/opening templates and pin their exact bytes.
            templates: dict[str, str] = {}
            for filename in ("装备洗练.txt", "装备开光.txt"):
                rel = "payload/server/npc/" + filename
                data = read(package.root / rel)
                if _sha256(data) != manifest["template_sha256"][rel]:
                    raise EquipmentWashError(f"洗练NPC母版哈希不匹配：{filename}")
                templates[filename] = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").format_map(params)
            image_relative = Path("Mir200/Envir/EffectImageList.txt")
            image_before = target_read(image_relative)
            image_lines = _script_text(image_before).splitlines()
            indices = [i for i, line in enumerate(image_lines) if line.strip().casefold() == "xy_equipmentworkbench.wz"]
            if len(indices) > 1:
                raise EquipmentWashError("工作台EffectImageList索引重复")
            index = indices[0] if indices else len(image_lines)
            if not indices:
                image_lines.append("XY_EquipmentWorkbench.wz")
            map_text = _script_text(target_read(Path("Mir200/Envir/MapInfo.txt")))
            for kind in ("wash", "open"):
                map_id = params[kind + "_npc_map"]
                if len(re.findall(rf"(?m)^\[\s*{re.escape(map_id)}(?:\||\s|\])", map_text)) != 1:
                    raise EquipmentWashError(f"目标地图缺失或不唯一：{map_id}")

            generated: dict[Path, str] = {
                _npc_relative(params, "wash"): _adapt_script(render_main_script(templates["装备洗练.txt"]), params, index),
                _npc_relative(params, "open"): _adapt_script(templates["装备开光.txt"], params, index),
                core_directory / "洗练词条随机核心.txt": _adapt_script(render_random_core(catalog), params),
                core_directory / "洗练词条实效核心.txt": render_effect_core(),
            }
            for filename, *args in DIRECT_SPECS:
                generated[core_directory / filename] = _adapt_script(render_direct_script(*args), params)

            owned = state.get("owned", {}) if state else {}
            for relative, rendered in generated.items():
                before = target_read(relative, False)
                after = _script_bytes(rendered)
                if before is not None and before != after:
                    previous = owned.get(relative.as_posix())
                    known: set[str] = set()
                    if previous:
                        known.add(previous)
                    elif state is None:
                        if relative in _LEGACY_GENERATED_SHA256:
                            known.add(_LEGACY_GENERATED_SHA256[relative])
                        # Deterministic compatibility, not a marker/comment bypass.
                        if relative == _npc_relative(params, "wash"):
                            known.add(_sha256(_script_bytes(_adapt_script(templates["装备洗练.txt"], params, index))))
                            known.add(_sha256(_script_bytes(_adapt_script(render_main_script(templates["装备洗练.txt"]), params, index))))
                            known.add(_sha256(_script_bytes(_without_temporary_reset(_adapt_script(render_main_script(templates["装备洗练.txt"]), params, index)))))
                        elif relative == _npc_relative(params, "open"):
                            known.add(_sha256(_script_bytes(_adapt_script(templates["装备开光.txt"], params, 12))))
                        elif relative.name in _UNWRAPPED_DIRECT_SHA256:
                            known.add(_sha256(_script_bytes(_without_temporary_reset(rendered))))
                            if core_directory == WASH_DIRECTORY:
                                known.update((_UNWRAPPED_DIRECT_SHA256[relative.name].lower(), _BASELINE_SHA256[WASH_DIRECTORY / relative.name].lower()))
                        elif relative.name in ("洗练词条随机核心.txt", "洗练词条实效核心.txt"):
                            original = render_random_core(WashCatalog(_AFFIXES)) if relative.name == "洗练词条随机核心.txt" else render_effect_core()
                            known.add(_sha256(_script_bytes(original)))
                            known.add(_sha256(_script_bytes(original.replace("\n{\n", "\n").replace("\n}\n", "\n"))))
                    if _sha256(before) not in known:
                        raise EquipmentWashError(f"生成文件发生未知手改或不是支持的基线，禁止覆盖：{relative}")
                elif before is None and relative.as_posix() in owned:
                    raise EquipmentWashError(f"已安装生成文件缺失：{relative}")
                stage(relative, after)

            # Every anchor is required on every preflight, even if a managed marker exists.
            q_before = _script_text(target_read(QFUNCTION_RELATIVE))
            for label in ("PlayLogin", "TakeOnEx", "TakeOffEx"):
                if len(re.findall(rf"(?m)^\[@{label}\][ \t]*$", q_before)) != 1:
                    raise EquipmentWashError(f"依赖事件标签缺失或重复：{label}")
            for anchor in ("MOV N$XY_RT_DamageCoeff 100", "MOV N$XY_最大爆率 100", "MOV N$XY_SUS_LifeStealHeal 0", "; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR", "MOV N$XY_MDA_Final 0"):
                if q_before.count(anchor) != 1:
                    raise EquipmentWashError(f"战斗/处决/续航依赖接口缺失或重复：{anchor}")
            def q_builder(text):
                after, markers, blocks = _patch_qfunction(text)
                return _adapt_script(after, params), markers, [_adapt_script(block, params) for block in blocks]
            q_after = _strict_managed_patch(q_before, q_builder, bool(state))
            if len(re.findall(r"(?m)^\[@XY_WASH_RECALC_DELAY\][ \t]*$", q_after)) != 1:
                raise EquipmentWashError("QFunction洗练延迟重算标签已被未知内容占用")
            # Include only newly inserted external calls, not unrelated QFunction subsystems.
            _, _, q_blocks = q_builder(q_before)
            call_roots = dict(generated)
            call_roots[QFUNCTION_RELATIVE] = "\n".join(q_blocks)
            speed_before = _script_text(target_read(speed_relative))
            if speed_before.count("MOV N$XY_AS_RAW <$HITSPD>") != 1 or "GetAllCustomItemValueByTextLine 60 -1 40 " not in speed_before:
                raise EquipmentWashError("攻速依赖缺少基础重算或TextVar40突破聚合合同")
            def speed_builder(text):
                after, block = _patch_attack_speed_core(text)
                return after, ["XY-EQUIPMENT-WASH-IMPORT-V1-NORMAL-SPEED"], [block]
            speed_after = _strict_managed_patch(speed_before, speed_builder, bool(state))
            textvar_before = _script_text(target_read(TEXTVAR_RELATIVE))
            textvar_lines = textvar_before.splitlines()
            if len(textvar_lines) < 40 or textvar_lines[39].strip() != "{攻速突破∶|251}+$$2":
                raise EquipmentWashError("TextVar40缺少攻速突破依赖合同")
            textvar_after, _, _ = _patch_textvar(textvar_before)
            calls = check_external_calls(call_roots, lambda rel: _script_text(target_read(rel)))

            # Register target-native NPCs, preserving other merchant lines and detecting collisions.
            merchant_relative = Path("Mir200/Envir/MerChant.txt")
            merchant_before = _script_text(target_read(merchant_relative))
            merchant_lines = merchant_before.splitlines()
            for kind in ("wash", "open"):
                def row(p):
                    return "\t".join(str(p[kind + suffix]) for suffix in ("_npc_script", "_npc_map", "_npc_x", "_npc_y", "_npc_display")) + f"\t0\t{p[kind + '_npc_appearance']}\t0"
                expected = row(params)
                old_row = row(state["parameters"]) if state else expected
                matching = [i for i, line in enumerate(merchant_lines) if line.split() and line.split()[0].replace("\\", "/") == params[kind + "_npc_script"]]
                if len(matching) > 1:
                    raise EquipmentWashError(f"NPC注册重复：{params[kind + '_npc_script']}")
                if matching:
                    existing = merchant_lines[matching[0]]
                    if existing.split() not in (expected.split(), old_row.split()):
                        raise EquipmentWashError(f"NPC注册发生未知手改：{existing}")
                    if existing.split() != expected.split():
                        for i, line in enumerate(merchant_lines):
                            if i != matching[0] and line.split()[1:4] == expected.split()[1:4]:
                                raise EquipmentWashError(f"目标NPC坐标已占用：{line}")
                        merchant_lines[matching[0]] = expected
                else:
                    if state:
                        raise EquipmentWashError("已安装NPC注册缺失")
                    for line in merchant_lines:
                        fields = line.split()
                        if len(fields) >= 4 and fields[1:4] == [str(params[kind + suffix]) for suffix in ("_npc_map", "_npc_x", "_npc_y")]:
                            raise EquipmentWashError(f"目标NPC坐标已占用：{line}")
                    merchant_lines.append(expected)

            # Resources are a required explicit dependency; never infer their presence from server text.
            if client is None:
                raise EquipmentWashError("未提供客户端资源目录；无法验证工作台WZL/WZX依赖，禁止安装")
            for suffix in ("wzl", "wzx"):
                name = f"XY_EquipmentWorkbench.{suffix}"
                expected = read(package.root / "payload/client" / name)
                actual = read(_checked_path(Path(client).absolute(), Path("data") / name))
                if _sha256(actual) != _sha256(expected):
                    raise EquipmentWashError(f"客户端工作台资源哈希不匹配：{name}")
            stage(QFUNCTION_RELATIVE, _script_bytes(q_after))
            stage(speed_relative, _script_bytes(speed_after))
            stage(TEXTVAR_RELATIVE, _script_bytes(textvar_after))
            stage(image_relative, _script_bytes("\n".join(image_lines)))
            stage(merchant_relative, _script_bytes("\n".join(merchant_lines)))
            state_after = {
                "schema_version": 1, "package_id": PACKAGE_ID, "version": VERSION, "status": "candidate",
                "source_sha256": _sha256(source_data), "parameters": params,
                "owned": {rel.as_posix(): _sha256(_script_bytes(text)) for rel, text in generated.items()},
            }
            stage(STATE_RELATIVE, (json.dumps(state_after, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        except (OSError, UnicodeError, MinggeDualError, EquipmentWashError, ValueError, KeyError, TypeError) as exc:
            blockers.append(str(exc))
            changes = []
        document_hash = watched.get(document.resolve(), "")
        return WashInstallPlan(self.route, self.package_id, _plan_id(self.route, document_hash, changes),
                               root.resolve(), document.resolve(), document_hash, tuple(changes), tuple(blockers),
                               tuple(warnings), input_hashes=tuple(sorted(watched.items())), target_parameters=params,
                               external_calls=calls)

    def _validate_install_inputs(self, plan: DualInstallPlan):
        if not isinstance(plan, WashInstallPlan):
            raise EquipmentWashError("洗练安装必须重新生成统一核心计划，拒绝旧计划")
        if plan.blockers:
            raise EquipmentWashError("安装被阻止：" + "；".join(plan.blockers))
        for path, expected in plan.input_hashes:
            _checked_path(path.parent, Path(path.name))
            data = path.read_bytes() if path.is_file() else None
            if _sha256(data) != expected:
                raise EquipmentWashError(f"预检后输入或依赖已变化：{path}")
        for change in plan.changes:
            if _checked_path(plan.server_root, Path(change.relative_path)) != change.path:
                raise EquipmentWashError("预检后目标路径已变化")
            if change.path.with_name(change.path.name + ".xydp-new").exists():
                raise EquipmentWashError(f"目标已有未处理临时文件：{change.relative_path}.xydp-new")




__all__ = [
    "ATTACK_SPEED_BREAKTHROUGH_DENOMINATOR", "ATTACK_SPEED_CORE_RELATIVE", "EFFECT_CORE_RELATIVE",
    "EquipmentWashError", "EquipmentWashImportService", "MAIN_RELATIVE", "NORMAL_CATEGORY_COUNT",
    "PACKAGE_ID", "RANDOM_CORE_RELATIVE", "ROUTE", "TEXTVAR_LINES", "WashAffix", "WashCatalog",
    "WashInstallPlan", "VERSION", "STATE_RELATIVE", "DIRECT_SPECS", "check_external_calls",
    "parse_wash_affix_text", "render_direct_script", "render_effect_core", "render_main_script", "render_random_core",
]
