from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .installer import InstallError
from .manifest import PackageManifest


PVE_TRIGGER = """#IF
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_Triggered 0
LARGE N$XY_EXEC_ChanceBP 0
RANDOMEX <$STR(N$XY_EXEC_ChanceBP)> 10000
#ACT
MOV N$XY_EXEC_Triggered 1
MOV N$XY_EXEC_EffectiveBP <$STR(N$XY_EXEC_ChanceBP)>"""

PVE_ANCHOR = "; XY_EXECUTION_LAB_PVE_MAP_RULE_ANCHOR"


@dataclass(frozen=True)
class MapExecutionRule:
    map_id: int | str
    enabled: int
    required_toughness: int
    base_chance_bp: int
    monster_execution_toughness: int


XX_MAP_ID = re.compile(r"^XX([0-9]+)$", re.IGNORECASE)


def _parse_map_id(value: object) -> int | str:
    token = str(value).strip()
    if token.isdecimal():
        map_id = int(token)
        if 0 <= map_id <= 65535:
            return map_id
        raise InstallError(f"地图编号越界: {token}")
    match = XX_MAP_ID.fullmatch(token)
    if match:
        suffix = int(match.group(1))
        if 0 <= suffix <= 65535:
            return token.upper()
        raise InstallError(f"地图编号越界: {token}")
    raise InstallError(f"地图编号格式错误，应为纯数字或XX加数字: {token}")


def _map_sort_key(rule: MapExecutionRule) -> tuple[int, int, str]:
    if isinstance(rule.map_id, int):
        return (0, rule.map_id, str(rule.map_id))
    return (1, int(rule.map_id[2:]), rule.map_id)


def load_map_rules(path: Path) -> tuple[list[MapExecutionRule], str]:
    path = Path(path)
    if not path.is_file():
        raise InstallError(f"地图处决规则表不存在: {path}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InstallError("地图处决规则表必须使用UTF-8编码") from exc
    reader = csv.DictReader(text.splitlines())
    headers = set(reader.fieldnames or [])
    required = {
        "map_id",
        "enabled",
        "required_toughness",
        "base_chance_bp",
        "monster_execution_toughness",
    }
    allowed = required | {"中文说明", "填写说明"}
    missing = required - headers
    unknown = headers - allowed
    rows = list(reader)
    if missing or unknown or not rows:
        raise InstallError(
            f"地图规则表头或内容错误；缺少={sorted(missing)}，未知={sorted(unknown)}"
        )
    result: list[MapExecutionRule] = []
    seen: set[int | str] = set()
    for row in rows:
        map_id = _parse_map_id(row.get("map_id", ""))
        try:
            values = {
                name: int(str(row[name]).strip())
                for name in required - {"map_id"}
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise InstallError(f"地图规则存在非整数值: {row}") from exc
        if map_id in seen:
            raise InstallError(f"地图规则重复: {map_id}")
        seen.add(map_id)
        if values["enabled"] not in (0, 1):
            raise InstallError(f"enabled只能是0或1: 地图{map_id}")
        if not 0 <= values["required_toughness"] <= 10000:
            raise InstallError(f"玩家免疫所需韧性越界: 地图{map_id}")
        if values["enabled"] and values["required_toughness"] == 0:
            raise InstallError(f"启用地图必须设置正的玩家免疫所需韧性: 地图{map_id}")
        if not 0 <= values["base_chance_bp"] <= 10000:
            raise InstallError(f"怪物处决玩家基础概率越界: 地图{map_id}")
        if not 0 <= values["monster_execution_toughness"] <= 10000:
            raise InstallError(f"地图怪物韧性越界: 地图{map_id}")
        result.append(MapExecutionRule(map_id=map_id, **values))
    return sorted(result, key=_map_sort_key), hashlib.sha256(raw).hexdigest()


def render_rule_rows(rows: list[MapExecutionRule]) -> str:
    lines = ["; XY_EXECUTION_MONSTER_MAP_RULES_BEGIN"]
    for row in rows:
        lines.extend(
            (
                "#IF",
                f"ISONMAP {row.map_id}",
                "#ACT",
                f"MOV N$XY_EXEC_MONSTER_MapEnabled {row.enabled}",
                f"MOV N$XY_EXEC_MONSTER_MapRequiredToughness {row.required_toughness}",
                f"MOV N$XY_EXEC_MONSTER_MapChanceBP {row.base_chance_bp}",
                f"MOV N$XY_EXEC_MONSTER_MapPVEToughness {row.monster_execution_toughness}",
            )
        )
    lines.append("; XY_EXECUTION_MONSTER_MAP_RULES_END")
    return "\n".join(lines)


def _map_core(rows: list[MapExecutionRule]) -> str:
    return f"""[@XYDP_ExecutionLoadMapRule]
#IF
#ACT
MOV N$XY_EXEC_MONSTER_MapEnabled 0
MOV N$XY_EXEC_MONSTER_MapRequiredToughness 0
MOV N$XY_EXEC_MONSTER_MapChanceBP 0
MOV N$XY_EXEC_MONSTER_MapPVEToughness 0
MOV N$XY_EXEC_MONSTER_MapRuleLoaded 0
{render_rule_rows(rows)}
MOV N$XY_EXEC_MONSTER_MapRuleLoaded 1

[@XYDP_ExecutionMonsterClear]
#IF
EQUAL N$XY_EXEC_MONSTER_SlowActive 1
#ACT
ChangeSpeed 1 0
MOV N$XY_EXEC_MONSTER_SlowActive 0
#IF
#ACT
MOV N$XY_EXEC_MONSTER_ACTIVE 0
MOV N$XY_EXEC_MONSTER_BonusPercent 0
MOV N$XY_EXEC_MONSTER_DurationMs 0
MOV N$XY_EXEC_MONSTER_EffectiveBP 0
MOV N$XY_EXEC_MONSTER_Tier 0"""


STRUCK_DAMAGE = """#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_ACTIVE 1
#ACT
ChangeDamageValue 1 + <$STR(N$XY_EXEC_MONSTER_BonusPercent)>
BREAK
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_ACTIVE 0
LARGE N$XY_EXEC_MONSTER_MapRequiredToughness 0
#ACT
MOV N$XY_EXEC_MONSTER_ChanceBP <$STR(N$XY_EXEC_MONSTER_MapChanceBP)>
FORMULATION <$STR(N$XY_EXEC_MONSTER_MapChanceBP)>-((<$STR(N$XY_EXEC_MONSTER_MapChanceBP)>*<$STR(N$XY_EXEC_Toughness)>)/<$STR(N$XY_EXEC_MONSTER_MapRequiredToughness)>) N$XY_EXEC_MONSTER_EffectiveBP
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_ACTIVE 0
LARGE N$XY_EXEC_MONSTER_EffectiveBP 0
RANDOMEX <$STR(N$XY_EXEC_MONSTER_EffectiveBP)> 10000
#ACT
MOV N$XY_EXEC_MONSTER_Triggered 1
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_Triggered 1
#ACT
FORMULATION <$STR(N$XY_EXEC_MONSTER_EffectiveBP)>/100 N$XY_EXEC_MONSTER_Tier
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_Triggered 1
SMALL N$XY_EXEC_MONSTER_Tier 1
#ACT
MOV N$XY_EXEC_MONSTER_Tier 1
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_Triggered 1
LARGE N$XY_EXEC_MONSTER_Tier 100
#ACT
MOV N$XY_EXEC_MONSTER_Tier 100
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_Triggered 1
LARGE N$XY_EXEC_MONSTER_Tier 0
#ACT
FORMULATION 100+(<$STR(N$XY_EXEC_MONSTER_Tier)>-1)*80/3 N$XY_EXEC_MONSTER_BonusPercent
FORMULATION (5+(<$STR(N$XY_EXEC_MONSTER_Tier)>-1))*200 N$XY_EXEC_MONSTER_DurationMs
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_MONSTER_Triggered 1
LARGE N$XY_EXEC_MONSTER_DurationMs 0
#ACT
MOV N$XY_EXEC_MONSTER_ACTIVE 1
ChangeDamageValue 1 + <$STR(N$XY_EXEC_MONSTER_BonusPercent)>
ChangeSpeed 1 -10
FORMULATION <$STR(N$XY_EXEC_MONSTER_DurationMs)>/1000 N$XY_EXEC_MONSTER_DurationWholeSec
FORMULATION (<$STR(N$XY_EXEC_MONSTER_DurationMs)>-(<$STR(N$XY_EXEC_MONSTER_DurationWholeSec)>*1000))/100 N$XY_EXEC_MONSTER_DurationTenth
SendNewLineMsg 1 251 0 16 120 5 0 您已被击倒！||移动速度降低50%，持续<$STR(N$XY_EXEC_MONSTER_DurationWholeSec)>.<$STR(N$XY_EXEC_MONSTER_DurationTenth)>秒。||持续期间受到<$STR(N$XY_EXEC_MONSTER_BonusPercent)>%额外伤害。
MOV N$XY_EXEC_MONSTER_SlowActive 1
DelayCall <$STR(N$XY_EXEC_MONSTER_DurationMs)> @XYDP_ExecutionMonsterClear
SENDMSG 6 MONSTER_EXECUTION_MAP_RULE_TRIGGERED
MOV N$XY_EXEC_MONSTER_Triggered 0
BREAK"""


PVE_MAP_HOOK = """#IF
#ACT
MOV N$XY_EXEC_PVEMapEffectiveBP <$STR(N$XY_EXEC_ChanceBP)>
#IF
EQUAL N$XY_EXEC_MONSTER_MapEnabled 1
LARGE N$XY_EXEC_MONSTER_MapPVEToughness 0
#ACT
FORMULATION <$STR(N$XY_EXEC_ChanceBP)>-(<$STR(N$XY_EXEC_MONSTER_MapPVEToughness)>*10) N$XY_EXEC_PVEMapEffectiveBP
#IF
SMALL N$XY_EXEC_PVEMapEffectiveBP 0
#ACT
MOV N$XY_EXEC_PVEMapEffectiveBP 0
#IF
LARGE N$XY_EXEC_PVEMapEffectiveBP 10000
#ACT
MOV N$XY_EXEC_PVEMapEffectiveBP 10000
#IF
NOT CHECKCURRTARGETRACE = 0
EQUAL N$XY_EXEC_Triggered 0
LARGE N$XY_EXEC_PVEMapEffectiveBP 0
RANDOMEX <$STR(N$XY_EXEC_PVEMapEffectiveBP)> 10000
#ACT
MOV N$XY_EXEC_Triggered 1
MOV N$XY_EXEC_EffectiveBP <$STR(N$XY_EXEC_PVEMapEffectiveBP)>"""


RESET = """#IF
EQUAL N$XY_EXEC_MONSTER_SlowActive 1
#ACT
ChangeSpeed 1 0
MOV N$XY_EXEC_MONSTER_SlowActive 0
#IF
#ACT
MOV N$XY_EXEC_MONSTER_ACTIVE 0
MOV N$XY_EXEC_MONSTER_BonusPercent 0
MOV N$XY_EXEC_MONSTER_DurationMs 0
MOV N$XY_EXEC_MONSTER_EffectiveBP 0
MOV N$XY_EXEC_MONSTER_Tier 0
MOV N$XY_EXEC_MONSTER_MapEnabled 0
MOV N$XY_EXEC_MONSTER_MapRequiredToughness 0
MOV N$XY_EXEC_MONSTER_MapChanceBP 0
MOV N$XY_EXEC_MONSTER_MapPVEToughness 0
MOV N$XY_EXEC_PVEMapEffectiveBP 0
MOV N$XY_EXEC_MONSTER_MapRuleLoaded 0
MOV N$XY_EXEC_MONSTER_Triggered 0"""


def augment_package(package: PackageManifest, rows: list[MapExecutionRule]) -> PackageManifest:
    operations: list[dict] = []
    replaced_trigger = False
    extended_managed_block = False
    for operation in package.operations:
        item = dict(operation)
        if item.get("type") == "event_hook" and item.get("label") == "AttackDamage":
            content = str(item["content"])
            if content.count(PVE_TRIGGER) != 1:
                raise InstallError("处决PVE原始概率段无法唯一识别，禁止接入地图韧性")
            item["content"] = content.replace(PVE_TRIGGER, PVE_ANCHOR)
            replaced_trigger = True
        if (
            item.get("type") == "managed_block"
            and item.get("target") == "Mir200/Envir/Market_Def/QFunction-0.txt"
        ):
            item["content"] = str(item["content"]).rstrip() + "\n\n" + _map_core(rows)
            extended_managed_block = True
        operations.append(item)
    if not replaced_trigger:
        raise InstallError("处决包缺少AttackDamage事件，禁止接入地图韧性")
    if not extended_managed_block:
        raise InstallError("处决包缺少QFunction受管块，禁止接入地图规则")

    legacy = ["xy.lab.execution.monster-map0", "xy.lab.execution.map-monster-toughness"]
    qfunction = "Mir200/Envir/Market_Def/QFunction-0.txt"
    operations.extend(
        [
            {"type": "ensure_event_label", "target": qfunction, "label": "StruckDamage"},
            {"type": "ensure_event_label", "target": qfunction, "label": "EnterMap"},
            {"type": "event_hook", "target": qfunction, "label": "StruckDamage", "content": STRUCK_DAMAGE, "legacy_package_ids": legacy},
            {"type": "event_hook", "target": qfunction, "label": "EnterMap", "content": RESET + "\nDELAYGOTO 1 @XYDP_ExecutionLoadMapRule", "legacy_package_ids": legacy},
            {"type": "event_hook", "target": qfunction, "label": "PlayLogin", "content": RESET + "\nDELAYGOTO 1 @XYDP_ExecutionLoadMapRule", "legacy_package_ids": legacy},
            {"type": "event_hook", "target": qfunction, "label": "PlayDie", "content": RESET, "legacy_package_ids": legacy},
            {"type": "event_hook", "target": qfunction, "label": "PlayOffLine", "content": RESET, "legacy_package_ids": legacy},
            {"type": "managed_anchor_hook", "target": qfunction, "anchor": PVE_ANCHOR.removeprefix("; "), "content": PVE_MAP_HOOK, "legacy_package_ids": legacy},
        ]
    )
    claims = {key: list(value) for key, value in package.claims.items()}
    claims.setdefault("labels", []).extend(["XYDP_ExecutionLoadMapRule", "XYDP_ExecutionMonsterClear"])
    claims.setdefault("variables", []).extend(
        [
            "N$XY_EXEC_MONSTER_MapEnabled", "N$XY_EXEC_MONSTER_MapRequiredToughness",
            "N$XY_EXEC_MONSTER_MapChanceBP", "N$XY_EXEC_MONSTER_MapPVEToughness",
            "N$XY_EXEC_PVEMapEffectiveBP", "N$XY_EXEC_MONSTER_MapRuleLoaded",
            "N$XY_EXEC_MONSTER_EffectiveBP", "N$XY_EXEC_MONSTER_ChanceBP",
            "N$XY_EXEC_MONSTER_Triggered", "N$XY_EXEC_MONSTER_Tier",
            "N$XY_EXEC_MONSTER_BonusPercent", "N$XY_EXEC_MONSTER_DurationMs",
            "N$XY_EXEC_MONSTER_ACTIVE", "N$XY_EXEC_MONSTER_SlowActive",
        ]
    )
    return replace(package, operations=tuple(operations), claims=claims)
