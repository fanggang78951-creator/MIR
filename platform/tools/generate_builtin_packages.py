from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
QFUNCTION = "Mir200/Envir/Market_Def/QFunction-0.txt"


def base(package_id, name, status, bundle, dependencies=(), parameters=None, claims=None, operations=None, evidence=None, version="1.0.0", residency="optional"):
    return {
        "schema_version": 1, "id": package_id, "version": version, "display_name": name,
        "status": status, "engine": "LFM2", "residency": residency, "bundle": bundle, "dependencies": list(dependencies),
        "parameters": parameters or {},
        "claims": claims or {"labels": [], "variables": [], "maps": [], "npcs": []},
        "operations": operations or [], "preflight_checks": [], "post_checks": [],
        "evidence": evidence or [],
    }


def managed(package_id, content):
    return {"type": "managed_block", "target": QFUNCTION, "content": content}


def hook(label, content):
    return {"type": "event_hook", "target": QFUNCTION, "label": label, "content": content}


def ensure_event(label):
    return {"type": "ensure_event_label", "target": QFUNCTION, "label": label}


def write_package(data, payloads=None, evidence_files=None):
    folder = PACKAGES / data["status"] / data["id"]
    if folder.exists(): shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for relative, text in (payloads or {}).items():
        path = folder / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
    for relative, value in (evidence_files or {}).items():
        path = folder / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def combat_packages():
    contract = {
        "source": "D:/MirServer/AI_Handoff/tools/xy_equip_maker/script_properties.json",
        "source_version": 1,
        "properties": {
            "神力倍攻": {"anchor": "XY_EQUIP_MAKER_POWER_ANCHOR", "variable": "N$倍攻"},
            "打怪伤害": {"anchors": ["XY_EQUIP_MAKER_POWER_ANCHOR", "XY_EQUIP_MAKER_ATTACK_ANCHOR"], "variables": ["N$XY_PVE", "N$XY_PVE_Extra"]},
            "暴击伤害": {"anchor": "XY_EQUIP_MAKER_BLAST_ANCHOR", "variable": "N$XY_最终爆伤"},
            "爆率": {"anchor": "XY_EQUIP_MAKER_DROP_ANCHOR", "variable": "N$XY_最终爆率"},
            "最大爆率": {"anchor": "XY_EQUIP_MAKER_DROP_ANCHOR", "variable": "N$XY_最大爆率"},
            "首刀斩杀": {"anchor": "XY_EQUIP_MAKER_ATTACK_ANCHOR", "variable": "N$XY_FirstKillRate"},
            "尾刀斩杀": {"anchor": "XY_EQUIP_MAKER_ATTACK_ANCHOR", "variable": "N$XY_TailKillRate"},
            "鞭尸概率": {"anchor": "XY_EQUIP_MAKER_CORPSE_ANCHOR", "variable": "N$XY_CorpseRate"},
            "伤害系数": {"anchor": "XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR", "variable": "N$XY_RT_DamageCoeff"},
        },
        "anchors": ["XY_EQUIP_MAKER_POWER_ANCHOR", "XY_EQUIP_MAKER_ATTACK_ANCHOR", "XY_EQUIP_MAKER_BLAST_ANCHOR", "XY_EQUIP_MAKER_DROP_ANCHOR", "XY_EQUIP_MAKER_CORPSE_ANCHOR", "XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR"],
    }
    write_package(base(
        "xy.combat.core", "战斗附加属性公共契约", "verified", "combat-suite",
        operations=[ensure_event(label) for label in ("PlayLogin", "TakeOnEx", "TakeOffEx", "AttackDamage", "KillMon")],
        evidence=["static:equipment_contract", "source:XY-SKILL-028", "platform:event-bootstrap-contract"], version="1.1.0", residency="resident"),
        evidence_files={"evidence/equipment_contract.json": contract},
    )

    power = """[@XYDP_RecalcPower]
#IF
#ACT
MOV N$倍攻 100
MOV N$XY_PVE 100
MOV N$XY_Bind21Point 0
MOV N$XY_Bind21Rate 0
MOV N$XY_Bind22Point 0
MOV N$XY_Bind22Rate 0
GetAllCustomItemValue 21 N$XY_Bind21Point N$XY_Bind21Rate
GetAllCustomItemValue 22 N$XY_Bind22Point N$XY_Bind22Rate
INC N$倍攻 <$STR(N$XY_Bind21Point)>
INC N$倍攻 <$STR(N$XY_Bind21Rate)>
INC N$XY_PVE <$STR(N$XY_Bind22Point)>
INC N$XY_PVE <$STR(N$XY_Bind22Rate)>
; XYDP-EXTENSION-BEGIN EQUIP_POWER
; XY_EQUIP_MAKER_POWER_ANCHOR
; XYDP-EXTENSION-END EQUIP_POWER
POWERRATE <$STR(N$倍攻)> 0 0 1 0
BREAK"""
    write_package(base(
        "xy.combat.power", "神力倍数与打怪显示重算", "verified", "combat-suite", ["xy.combat.core"],
        claims={"labels": ["XYDP_RecalcPower"], "variables": ["N$倍攻", "N$XY_PVE", "N$XY_Bind21Point", "N$XY_Bind21Rate", "N$XY_Bind22Point", "N$XY_Bind22Rate"], "maps": [], "npcs": []},
        operations=[managed("xy.combat.power", power), hook("PlayLogin", "DELAYGOTO 1 @XYDP_RecalcPower"), hook("TakeOnEx", "DELAYGOTO 1 @XYDP_RecalcPower"), hook("TakeOffEx", "DELAYGOTO 1 @XYDP_RecalcPower")],
        evidence=["runtime:D:/MirServer/Mir200/Envir/QuestDiary/玄渊验收/events.txt", "source:XY-SKILL-012"], residency="resident",
    ))

    pve = """#IF
#ACT
MOV N$XY_PVE_Point 0
MOV N$XY_PVE_Rate 0
MOV N$XY_PVE_Extra 0
MOV N$XY_PVE_Damage 0
MOV N$XY_FirstKillRate 0
MOV N$XY_TailKillRate 0
GetAllCustomItemValue 22 N$XY_PVE_Point N$XY_PVE_Rate
INC N$XY_PVE_Extra <$STR(N$XY_PVE_Point)>
INC N$XY_PVE_Extra <$STR(N$XY_PVE_Rate)>
; XYDP-EXTENSION-BEGIN EQUIP_ATTACK
; XY_EQUIP_MAKER_ATTACK_ANCHOR
; XYDP-EXTENSION-END EQUIP_ATTACK
#IF
LARGE N$XY_PVE_Extra 0
NOT CHECKTEXTLIST ..\\QuestDiary\\不可切割.txt <$ATTACKMONSTER_NAMEEX>
NOT CHECKTEXTLIST ..\\QuestDiary\\不可切割.txt <$ATTACKMONSTER_NAME>
#ACT
CalcPercent <$MAXDC> <$STR(N$XY_PVE_Extra)> N$XY_PVE_Damage
ChangeDamageValue 0 + <$STR(N$XY_PVE_Damage)>"""
    write_package(base(
        "xy.combat.pve", "打怪伤害（ChangeDamageValue路线）", "verified", "combat-suite", ["xy.combat.power"],
        claims={"labels": [], "variables": ["N$XY_PVE_Point", "N$XY_PVE_Rate", "N$XY_PVE_Extra", "N$XY_PVE_Damage"], "maps": [], "npcs": []},
        operations=[hook("AttackDamage", pve)], evidence=["runtime:XY-PVE-DAMAGEFIX-001", "source:XY-SKILL-011"], residency="resident",
    ))

    blast = """[@XYDP_RecalcBlast]
#IF
#ACT
MOV N$XY_最终爆伤 100
MOV N$XY_Bind31Point 0
MOV N$XY_Bind31Rate 0
GetAllCustomItemValue 31 N$XY_Bind31Point N$XY_Bind31Rate
INC N$XY_最终爆伤 <$STR(N$XY_Bind31Point)>
INC N$XY_最终爆伤 <$STR(N$XY_Bind31Rate)>
; XYDP-EXTENSION-BEGIN EQUIP_BLAST
; XY_EQUIP_MAKER_BLAST_ANCHOR
; XYDP-EXTENSION-END EQUIP_BLAST
SetBlastHitRate <$STR(N$XY_最终爆伤)> 0
BREAK"""
    write_package(base(
        "xy.combat.blast", "暴击伤害重算", "verified", "combat-suite", ["xy.combat.core"],
        claims={"labels": ["XYDP_RecalcBlast"], "variables": ["N$XY_最终爆伤", "N$XY_Bind31Point", "N$XY_Bind31Rate"], "maps": [], "npcs": []},
        operations=[managed("xy.combat.blast", blast), hook("PlayLogin", "DELAYGOTO 2 @XYDP_RecalcBlast"), hook("TakeOnEx", "DELAYGOTO 2 @XYDP_RecalcBlast"), hook("TakeOffEx", "DELAYGOTO 2 @XYDP_RecalcBlast")],
        evidence=["runtime:D:/MirServer/Mir200/Envir/QuestDiary/玄渊验收/events.txt", "source:XY-SKILL-017"], residency="resident",
    ))

    drop = """[@XYDP_RecalcDrop]
#IF
#ACT
MOV N$XY_最终爆率 100
MOV N$XY_最大爆率 1000
MOV N$XY_Bind14Point 0
MOV N$XY_Bind14Rate 0
MOV N$XY_Bind20Point 0
MOV N$XY_Bind20Rate 0
GetAllCustomItemValue 14 N$XY_Bind14Point N$XY_Bind14Rate
GetAllCustomItemValue 20 N$XY_Bind20Point N$XY_Bind20Rate
INC N$XY_最终爆率 <$STR(N$XY_Bind14Point)>
INC N$XY_最终爆率 <$STR(N$XY_Bind14Rate)>
INC N$XY_最大爆率 <$STR(N$XY_Bind20Point)>
INC N$XY_最大爆率 <$STR(N$XY_Bind20Rate)>
; XYDP-EXTENSION-BEGIN EQUIP_DROP
; XY_EQUIP_MAKER_DROP_ANCHOR
; XYDP-EXTENSION-END EQUIP_DROP
#IF
LARGE N$XY_最终爆率 <$STR(N$XY_最大爆率)>
#ACT
MOV N$XY_最终爆率 <$STR(N$XY_最大爆率)>
#IF
#ACT
KILLMONBURSTRATE <$STR(N$XY_最终爆率)>
BREAK"""
    write_package(base(
        "xy.combat.drop", "人物爆率与最大爆率", "verified", "combat-suite", ["xy.combat.core"],
        claims={"labels": ["XYDP_RecalcDrop"], "variables": ["N$XY_最终爆率", "N$XY_最大爆率", "N$XY_Bind14Point", "N$XY_Bind14Rate", "N$XY_Bind20Point", "N$XY_Bind20Rate"], "maps": [], "npcs": []},
        operations=[managed("xy.combat.drop", drop), hook("PlayLogin", "DELAYGOTO 3 @XYDP_RecalcDrop"), hook("TakeOnEx", "DELAYGOTO 3 @XYDP_RecalcDrop"), hook("TakeOffEx", "DELAYGOTO 3 @XYDP_RecalcDrop")],
        evidence=["runtime:XY-CUSTOM-ATTR-RECALC-001", "source:XY-SKILL-009"], residency="resident",
    ))

    execute = """#IF
LARGE N$XY_TailKillRate 0
M.CheckHpPer < <$STR(N$XY_TailKillRate)>
NOT CHECKTEXTLIST ..\\QuestDiary\\玄渊临时\\XYDP_尾刀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX>
#ACT
M.AddhpPer - 100
AddTextListEx ..\\QuestDiary\\玄渊临时\\XYDP_尾刀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX> 0
BREAK
#IF
LARGE N$XY_FirstKillRate 0
NOT CHECKTEXTLIST ..\\QuestDiary\\玄渊临时\\XYDP_首刀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX>
#ACT
M.AddhpPer - <$STR(N$XY_FirstKillRate)>
AddTextListEx ..\\QuestDiary\\玄渊临时\\XYDP_首刀记录.txt <$ATTACKMONSTER_NAMEEX>|<$ATTACKMONSTER_XEX>|<$ATTACKMONSTER_YEX> 0"""
    write_package(base(
        "xy.combat.execute", "首刀与尾刀累计斩杀", "candidate", "combat-suite", ["xy.combat.core"],
        claims={"labels": [], "variables": ["N$XY_FirstKillRate", "N$XY_TailKillRate"], "maps": [], "npcs": []},
        operations=[hook("AttackDamage", execute)], evidence=["tool-test:20260703_1636", "game-validation:required"], residency="resident",
    ))

    corpse = """#IF
#ACT
MOV N$XY_CorpsePoint 0
MOV N$XY_CorpseRate 0
GetAllCustomItemValue 13 N$XY_CorpsePoint N$XY_CorpseRate
; XYDP-EXTENSION-BEGIN EQUIP_CORPSE
; XY_EQUIP_MAKER_CORPSE_ANCHOR
; XYDP-EXTENSION-END EQUIP_CORPSE
#IF
LARGE N$XY_CorpseRate 0
#ACT
MOVR N$XY_CorpseRoll 0 99
#IF
LARGE N$XY_CorpseRate <$STR(N$XY_CorpseRoll)>
#ACT
ScatterMonItems <$KILLMONNAME>
SENDMSG 6 [玄渊鞭尸] 已触发尸体额外掉落。
BREAK"""
    write_package(base(
        "xy.combat.corpse", "鞭尸概率", "candidate", "combat-suite", ["xy.combat.core"],
        claims={"labels": [], "variables": ["N$XY_CorpsePoint", "N$XY_CorpseRate", "N$XY_CorpseRoll"], "maps": [], "npcs": []},
        operations=[hook("KillMon", corpse)], evidence=["tool-test:20260703_1541", "game-validation:required"], residency="resident",
    ))

    write_package(base(
        "xy.combat-suite", "战斗附加属性整套", "candidate", "combat-suite",
        ["xy.combat.power", "xy.combat.pve", "xy.combat.blast", "xy.combat.drop", "xy.combat.execute", "xy.combat.corpse", "xy.combat.damage-coefficient"],
        evidence=["bundle:contains-candidate-modules"],
    ))


def npc_parameters(prefix, defaults):
    result = {}
    for name, value in defaults.items():
        result[f"{prefix}_{name}"] = {"type": "integer" if isinstance(value, int) else "string", "required": True, "default": value}
    return result


def render_npc(source, target):
    return {"type": "render", "source": source, "target": target, "source_encoding": "utf-8", "target_encoding": "gb18030"}


def merchant(line, keys=(0, 1)):
    return {"type": "unique_line", "target": "Mir200/Envir/MerChant.txt", "line": line, "key_fields": list(keys)}


def ops_packages():
    write_package(base(
        "xy.ops.core", "运营系统公共货币与变量规则", "candidate", "ops-suite",
        evidence=["verified-command:GAMEDIAMOND", "verified-command:ChangeHumAbilityEX", "game-validation:bundle-required"],
    ), evidence_files={"evidence/variable_contract.json": {
        "title": ["N$XY_Title_Level", "N$XY_Title_Sponsor"], "rage": ["[003]"],
        "donate": ["G1", "G2", "G3", "S$10", "N$XY_DONATE_TOTAL"],
    }})

    title_params = {}
    title_params.update(npc_parameters("title", {"map": "0", "x": 30, "y": 30, "dir": "玄渊运营", "script": "神印修行", "name": "神印修行", "appearance": 222}))
    title_params.update(npc_parameters("sponsor", {"map": "0", "x": 32, "y": 30, "dir": "玄渊运营", "script": "赞助称号", "name": "赞助称号", "appearance": 226}))
    for index, value in enumerate((50, 100, 200, 350, 600, 900, 1300, 1900, 2800, 4200), 1):
        title_params[f"title_cost_{index}"] = {"type": "integer", "required": True, "default": value}
    title_ops = [
        render_npc("payload/title_npc.txt", "Mir200/Envir/Market_Def/{title_dir}/{title_script}-{title_map}.txt"),
        merchant("{title_dir}/{title_script}\t{title_map}\t{title_x}\t{title_y}\t{title_name}\t0\t{title_appearance}\t0"),
        render_npc("payload/sponsor_npc.txt", "Mir200/Envir/Market_Def/{sponsor_dir}/{sponsor_script}-{sponsor_map}.txt"),
        merchant("{sponsor_dir}/{sponsor_script}\t{sponsor_map}\t{sponsor_x}\t{sponsor_y}\t{sponsor_name}\t0\t{sponsor_appearance}\t0"),
    ]
    title_claims = {"labels": [], "variables": ["N$XY_Title_Level", "N$XY_Title_Sponsor"], "maps": [], "npcs": ["{title_dir}/{title_script}", "{sponsor_dir}/{sponsor_script}"]}
    title_payload = """[@Main]
#SAY
神印修行共10重，消耗金刚石并永久增加攻魔道和生命。\\
当前等级：<$STR(N$XY_Title_Level)>\\
<提升一重/@XY_TITLE_UP> <关闭/@exit>

[@XY_TITLE_UP]
#IF
EQUAL N$XY_Title_Level 0
#ACT
GOTO @XY_TITLE_1
BREAK
#IF
EQUAL N$XY_Title_Level 1
#ACT
GOTO @XY_TITLE_2
BREAK
#IF
EQUAL N$XY_Title_Level 2
#ACT
GOTO @XY_TITLE_3
BREAK
#IF
EQUAL N$XY_Title_Level 3
#ACT
GOTO @XY_TITLE_4
BREAK
#IF
EQUAL N$XY_Title_Level 4
#ACT
GOTO @XY_TITLE_5
BREAK
#IF
EQUAL N$XY_Title_Level 5
#ACT
GOTO @XY_TITLE_6
BREAK
#IF
EQUAL N$XY_Title_Level 6
#ACT
GOTO @XY_TITLE_7
BREAK
#IF
EQUAL N$XY_Title_Level 7
#ACT
GOTO @XY_TITLE_8
BREAK
#IF
EQUAL N$XY_Title_Level 8
#ACT
GOTO @XY_TITLE_9
BREAK
#IF
EQUAL N$XY_Title_Level 9
#ACT
GOTO @XY_TITLE_10
BREAK
#ELSEACT
MESSAGEBOX 神印修行已满10重。
BREAK

[@XY_TITLE_1]
#IF
CHECKGAMEDIAMOND {title_cost_1}
#ACT
GAMEDIAMOND - {title_cost_1}
ChangeHumAbilityEX 5 + 20
ChangeHumAbilityEX 6 + 20
ChangeHumAbilityEX 7 + 20
ChangeHumAbilityEX 8 + 20
ChangeHumAbilityEX 9 + 20
ChangeHumAbilityEX 10 + 20
ChangeHumAbilityEX 11 + 200
MOV N$XY_Title_Level 1
SENDMSG 6 [神印修行] 已提升至1重。
BREAK
#ELSEACT
MESSAGEBOX 金刚石不足，需要{title_cost_1}。
BREAK
""" + "\n".join(
        f"""[@XY_TITLE_{i}]
#IF
CHECKGAMEDIAMOND {{title_cost_{i}}}
#ACT
GAMEDIAMOND - {{title_cost_{i}}}
ChangeHumAbilityEX 5 + {attack}
ChangeHumAbilityEX 6 + {attack}
ChangeHumAbilityEX 7 + {attack}
ChangeHumAbilityEX 8 + {attack}
ChangeHumAbilityEX 9 + {attack}
ChangeHumAbilityEX 10 + {attack}
ChangeHumAbilityEX 11 + {hp}
MOV N$XY_Title_Level {i}
SENDMSG 6 [神印修行] 已提升至{i}重。
BREAK
#ELSEACT
MESSAGEBOX 金刚石不足，需要{{title_cost_{i}}}。
BREAK
""" for i, attack, hp in zip(range(2, 11), (25, 35, 45, 55, 70, 90, 110, 140, 170), (250, 350, 450, 550, 700, 900, 1100, 1400, 1700)))
    sponsor_payload = """[@Main]
#SAY
赞助称号使用金刚石激活，档位只升不降。\\
当前档位：<$STR(N$XY_Title_Sponsor)>\\
<档位1（100）/@XY_SPONSOR_1> <档位2（200）/@XY_SPONSOR_2>\\
<档位3（500）/@XY_SPONSOR_3> <档位4（1000）/@XY_SPONSOR_4> <关闭/@exit>

[@XY_SPONSOR_1]
#IF
SMALL N$XY_Title_Sponsor 1
CHECKGAMEDIAMOND 100
#ACT
GAMEDIAMOND - 100
ChangeHumAbilityEX 5 + 200
ChangeHumAbilityEX 6 + 200
ChangeHumAbilityEX 11 + 1000
MOV N$XY_Title_Sponsor 1
BREAK
#ELSEACT
MESSAGEBOX 档位已激活或金刚石不足。
BREAK
[@XY_SPONSOR_2]
#IF
SMALL N$XY_Title_Sponsor 2
CHECKGAMEDIAMOND 200
#ACT
GAMEDIAMOND - 200
ChangeHumAbilityEX 5 + 250
ChangeHumAbilityEX 6 + 250
ChangeHumAbilityEX 11 + 1500
MOV N$XY_Title_Sponsor 2
BREAK
#ELSEACT
MESSAGEBOX 档位已激活或金刚石不足。
BREAK
[@XY_SPONSOR_3]
#IF
SMALL N$XY_Title_Sponsor 3
CHECKGAMEDIAMOND 500
#ACT
GAMEDIAMOND - 500
ChangeHumAbilityEX 5 + 550
ChangeHumAbilityEX 6 + 550
ChangeHumAbilityEX 11 + 4000
MOV N$XY_Title_Sponsor 3
BREAK
#ELSEACT
MESSAGEBOX 档位已激活或金刚石不足。
BREAK
[@XY_SPONSOR_4]
#IF
SMALL N$XY_Title_Sponsor 4
CHECKGAMEDIAMOND 1000
#ACT
GAMEDIAMOND - 1000
ChangeHumAbilityEX 5 + 1200
ChangeHumAbilityEX 6 + 1200
ChangeHumAbilityEX 11 + 8500
MOV N$XY_Title_Sponsor 4
BREAK
#ELSEACT
MESSAGEBOX 档位已激活或金刚石不足。
BREAK
"""
    write_package(base("xy.ops.title", "神印与赞助称号", "candidate", "ops-suite", ["xy.ops.core"], title_params, title_claims, title_ops, ["source:NPC4-chushidi", "game-validation:required"]),
                  {"payload/title_npc.txt": title_payload, "payload/sponsor_npc.txt": sponsor_payload})

    rage_params = npc_parameters("rage", {"map": "0", "x": 34, "y": 30, "dir": "玄渊运营", "script": "狂暴之力", "name": "狂暴之力", "appearance": 255, "cost": 100, "rate": 200})
    rage_payload = """[@Main]
#SAY
消耗金刚石{rage_cost}开启狂暴，人物攻击倍率为{rage_rate}%。死亡自动关闭。\\
<开启狂暴/@XY_RAGE_ON> <关闭狂暴/@XY_RAGE_OFF> <退出/@exit>
[@XY_RAGE_ON]
#IF
EQUAL [003] 0
CHECKGAMEDIAMOND {rage_cost}
#ACT
GAMEDIAMOND - {rage_cost}
MOV [003] 1
POWERRATE {rage_rate} 0 0 1 0
SENDMSG 6 [狂暴] 已开启。
BREAK
#ELSEACT
MESSAGEBOX 狂暴已开启或金刚石不足。
BREAK
[@XY_RAGE_OFF]
#IF
EQUAL [003] 1
#ACT
MOV [003] 0
POWERRATE 100 0 0 1 0
SENDMSG 6 [狂暴] 已关闭。
BREAK
"""
    rage_ops = [render_npc("payload/rage_npc.txt", "Mir200/Envir/Market_Def/{rage_dir}/{rage_script}-{rage_map}.txt"), merchant("{rage_dir}/{rage_script}\t{rage_map}\t{rage_x}\t{rage_y}\t{rage_name}\t0\t{rage_appearance}\t0"),
                hook("PlayLogin", "#IF\nEQUAL [003] 1\n#ACT\nPOWERRATE {rage_rate} 0 0 1 0"), hook("PlayDie", "#IF\nEQUAL [003] 1\n#ACT\nMOV [003] 0\nPOWERRATE 100 0 0 1 0")]
    write_package(base("xy.ops.rage", "狂暴系统", "candidate", "ops-suite", ["xy.ops.core"], rage_params,
                       {"labels": [], "variables": ["[003]"], "maps": [], "npcs": ["{rage_dir}/{rage_script}"]}, rage_ops,
                       ["source:NPC6-powerrate-test", "game-validation:required"]), {"payload/rage_npc.txt": rage_payload})

    donate_params = npc_parameters("donate", {"map": "0", "x": 36, "y": 30, "dir": "玄渊运营", "script": "沙城捐献", "name": "沙城捐献", "appearance": 256, "amount": 100})
    donate_payload = """[@Main]
#SAY
每次捐献{donate_amount}金刚石。\\
个人累计：<$STR(N$XY_DONATE_TOTAL)> 全服累计：<$STR(G1)>\\
榜一：<$STR(S$10)>，金额：<$STR(G2)>\\
<捐献一次/@XY_DONATE_ONCE> <查看榜单/@XY_DONATE_BOARD> <退出/@exit>
[@XY_DONATE_ONCE]
#IF
EQUAL G3 0
CHECKGAMEDIAMOND {donate_amount}
#ACT
GAMEDIAMOND - {donate_amount}
INC N$XY_DONATE_TOTAL {donate_amount}
INC G1 {donate_amount}
GOTO @XY_DONATE_RANK
BREAK
#ELSEACT
MESSAGEBOX 捐献已封榜或金刚石不足。
BREAK
[@XY_DONATE_RANK]
#IF
LARGE N$XY_DONATE_TOTAL G2
#ACT
MOV G2 <$STR(N$XY_DONATE_TOTAL)>
MOV S$10 <$USERNAME>
SENDMSG 0 [沙捐] <$USERNAME> 成为新的捐献榜一。
BREAK
[@XY_DONATE_BOARD]
#SAY
全服累计：<$STR(G1)>\\
榜一玩家：<$STR(S$10)>\\
榜一金额：<$STR(G2)>\\
<返回/@Main> <退出/@exit>
"""
    donate_ops = [render_npc("payload/donate_npc.txt", "Mir200/Envir/Market_Def/{donate_dir}/{donate_script}-{donate_map}.txt"), merchant("{donate_dir}/{donate_script}\t{donate_map}\t{donate_x}\t{donate_y}\t{donate_name}\t0\t{donate_appearance}\t0")]
    write_package(base("xy.ops.donate", "沙城捐献系统", "candidate", "ops-suite", ["xy.ops.core"], donate_params,
                       {"labels": [], "variables": ["G1", "G2", "G3", "S$10", "N$XY_DONATE_TOTAL"], "maps": [], "npcs": ["{donate_dir}/{donate_script}"]}, donate_ops,
                       ["source:XY-SKILL-DONATE-001", "game-validation:required"]), {"payload/donate_npc.txt": donate_payload})

    write_package(base("xy.ops-suite", "狂暴、称号、沙捐整套", "candidate", "ops-suite", ["xy.ops.title", "xy.ops.rage", "xy.ops.donate"], evidence=["bundle:game-validation-required"]))


def main():
    combat_packages()
    ops_packages()
    print("built-in packages generated")


if __name__ == "__main__":
    main()
