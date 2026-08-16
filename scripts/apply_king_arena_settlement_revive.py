from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


QFUNCTION = Path(r"D:\MirServer\Mir200\Envir\Market_Def\QFunction-0.txt")
CORE = Path(
    r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊功能\国王模式\国王模式核心.txt"
)

EXPECTED_Q_SHA256 = "3DEC194318E47BC49DDF3BFDD903C4467A3DD956BFC1B7A8ACB356E77A882CA0"
EXPECTED_CORE_SHA256 = "EF35CF6CF0D28943E63A54712D3128B52B50864778BF230178C03701006BEB93"


SCHEDULE_BLOCK = r"""; XY-KING-AUTO-REVIVE-SCHEDULE-BEGIN
; 以死亡地图和持久报名名单为准，不依赖重启后可能丢失的N$/S$在线变量。
#IF
CHECKMAPNAME XYKWA
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
DelayCall 1000 @XY_KING_AUTO_REVIVE
#IF
CHECKMAPNAME XYKWB
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
DelayCall 1000 @XY_KING_AUTO_REVIVE
#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
DelayCall 1000 @XY_KING_AUTO_REVIVE
#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
DelayCall 1000 @XY_KING_AUTO_REVIVE
; XY-KING-AUTO-REVIVE-SCHEDULE-END"""


AUTO_REVIVE_BLOCK = r"""; XY-KING-AUTO-REVIVE-BEGIN
; 野区死亡只回本方野区；角斗场死亡由[@Revival]按持久名单送往A/B复活点。
[@XY_KING_AUTO_REVIVE]
#IF
CHECKMAPNAME XYKWA
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
#ACT
MAPMOVE XYKWA 50 50
REALIVE
HumanHP = 100 0 1 0 0 1
HumanMP = 100 0 1 1
BREAK

#IF
CHECKMAPNAME XYKWA
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
MAPMOVE XYKWA 50 50
REALIVE
HumanHP = 50 0 1 0 0 1
HumanMP = 50 0 1 1
BREAK

#IF
CHECKMAPNAME XYKWB
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
#ACT
MAPMOVE XYKWB 50 50
REALIVE
HumanHP = 100 0 1 0 0 1
HumanMP = 100 0 1 1
BREAK

#IF
CHECKMAPNAME XYKWB
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
MAPMOVE XYKWB 50 50
REALIVE
HumanHP = 50 0 1 0 0 1
HumanMP = 50 0 1 1
BREAK

; A方国王在角斗场第10次死亡后不再复活。
#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
EQUAL N$XY_KING_A_DEATHS 10
#ACT
SENDMSG 6 你已达到国王最大死亡次数，不能再次复活。
BREAK

; B方国王在角斗场第10次死亡后不再复活。
#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
EQUAL N$XY_KING_B_DEATHS 10
#ACT
SENDMSG 6 你已达到国王最大死亡次数，不能再次复活。
BREAK

#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
REALIVE
BREAK

#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
REALIVE
BREAK
; XY-KING-AUTO-REVIVE-END"""


PLAY_DIE_BLOCK = r"""[@XY_KING_PLAY_DIE]
{
; 角斗场人物击杀结算只依赖XYGDZY和持久名单，不依赖N$/S$在线缓存。
#IF
CHECKMAPNAME XYGDZY
KillByHum
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
#ACT
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_A_KING_DIE
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_LOSS_500
BREAK

#IF
CHECKMAPNAME XYGDZY
KillByHum
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
#ACT
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_B_KING_DIE
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_LOSS_500
BREAK

#IF
CHECKMAPNAME XYGDZY
KillByHum
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_LOSS_25
BREAK

#IF
CHECKMAPNAME XYGDZY
KillByHum
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_LOSS_25
BREAK
}

[@XY_KING_A_KING_DIE]
{
#IF
#ACT
INC N$XY_KING_A_DEATHS 1
INC N$XY_KING_A_STREAK 1
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 A国王死亡 <$STR(N$XY_KING_A_DEATHS)>
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 A国王连死 <$STR(N$XY_KING_A_STREAK)>
#IF
EQUAL N$XY_KING_A_DEATHS 10
#ACT
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 胜者 B队
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 模式 结束
WriteConfigFileItem ..\QuestDiary\玄渊配置\国王模式配置.txt 基础 战斗状态 0
SENDMSG 0 A队国王达到最大死亡次数，B队获胜。
BREAK
}

[@XY_KING_B_KING_DIE]
{
#IF
#ACT
INC N$XY_KING_B_DEATHS 1
INC N$XY_KING_B_STREAK 1
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 B国王死亡 <$STR(N$XY_KING_B_DEATHS)>
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 B国王连死 <$STR(N$XY_KING_B_STREAK)>
#IF
EQUAL N$XY_KING_B_DEATHS 10
#ACT
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 胜者 A队
WriteConfigFileItem ..\QuestDiary\玄渊数据\xy_king_mode\国王模式状态.txt 状态 模式 结束
WriteConfigFileItem ..\QuestDiary\玄渊配置\国王模式配置.txt 基础 战斗状态 0
SENDMSG 0 B队国王达到最大死亡次数，A队获胜。
BREAK
}

[@XY_KING_LOSS_25]
{
#IF
CHECKGAMEGOLD > 24
#ACT
GAMEGOLD - 25
SENDMSG 6 国王模式死亡扣除25元宝。
BREAK
#IF
CHECKGAMEGOLD > 0
#ACT
MOV N$XY_KING_VICTIM_LOSS <$GAMEGOLD>
GAMEGOLD - <$STR(N$XY_KING_VICTIM_LOSS)>
SENDMSG 6 元宝不足25，已扣除现有<$STR(N$XY_KING_VICTIM_LOSS)>元宝。
BREAK
#ELSEACT
SENDMSG 6 当前元宝为0，本次死亡不扣除元宝。
BREAK
}

[@XY_KING_LOSS_500]
{
#IF
CHECKGAMEGOLD > 499
#ACT
GAMEGOLD - 500
SENDMSG 6 国王死亡扣除500元宝。
BREAK
#IF
CHECKGAMEGOLD > 0
#ACT
MOV N$XY_KING_VICTIM_LOSS <$GAMEGOLD>
GAMEGOLD - <$STR(N$XY_KING_VICTIM_LOSS)>
SENDMSG 6 元宝不足500，已扣除现有<$STR(N$XY_KING_VICTIM_LOSS)>元宝。
BREAK
#ELSEACT
SENDMSG 6 当前元宝为0，本次死亡不扣除元宝。
BREAK
}

"""


REVIVAL_BLOCK = r"""[@XY_KING_REVIVAL]
{
; 只处理角斗场复活；野区已在延迟回调中直接回本方野区。
#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
#ACT
MAPMOVE XYGDZY 15 50
HumanHP = 100 0 1 0 0 1
HumanMP = 100 0 1 1
BREAK

#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
MAPMOVE XYGDZY 15 50
HumanHP = 50 0 1 0 0 1
HumanMP = 50 0 1 1
BREAK

#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
#ACT
MAPMOVE XYGDZY 100 50
HumanHP = 100 0 1 0 0 1
HumanMP = 100 0 1 1
BREAK

#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
MAPMOVE XYGDZY 100 50
HumanHP = 50 0 1 0 0 1
HumanMP = 50 0 1 1
BREAK
}

"""


KILL_REWARD_BLOCK = r"""[@XY_KING_KILL_EXP]
{
; @KillPlay中的当前脚本对象是击杀者；<$CURRRTARGETNAME>是被杀者。
#IF
#ACT
MOV N$XY_KING_KILLER_OK 0
MOV N$XY_KING_KILL_REWARD 0
MOV N$XY_KING_EXP_RATE 0
MOV N$XY_KING_LEVEL_MAXEXP 0
MOV N$XY_KING_EXP_REWARD 0

#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
MOV N$XY_KING_KILLER_OK 1
#IF
CHECKMAPNAME XYGDZY
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
MOV N$XY_KING_KILLER_OK 1

#IF
EQUAL N$XY_KING_KILLER_OK 1
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$CURRRTARGETNAME>
#ACT
MOV N$XY_KING_KILL_REWARD 500
MOV N$XY_KING_EXP_RATE 50
#IF
EQUAL N$XY_KING_KILLER_OK 1
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$CURRRTARGETNAME>
#ACT
MOV N$XY_KING_KILL_REWARD 500
MOV N$XY_KING_EXP_RATE 50
#IF
EQUAL N$XY_KING_KILLER_OK 1
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队平民名单.txt <$CURRRTARGETNAME>
#ACT
MOV N$XY_KING_KILL_REWARD 100
MOV N$XY_KING_EXP_RATE 10
#IF
EQUAL N$XY_KING_KILLER_OK 1
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队平民名单.txt <$CURRRTARGETNAME>
#ACT
MOV N$XY_KING_KILL_REWARD 100
MOV N$XY_KING_EXP_RATE 10

; 兼容旧报名残留：在队伍名单但角色名单缺失时按普通成员结算。
#IF
EQUAL N$XY_KING_KILLER_OK 1
EQUAL N$XY_KING_KILL_REWARD 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$CURRRTARGETNAME>
#ACT
MOV N$XY_KING_KILL_REWARD 100
MOV N$XY_KING_EXP_RATE 10
#IF
EQUAL N$XY_KING_KILLER_OK 1
EQUAL N$XY_KING_KILL_REWARD 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$CURRRTARGETNAME>
#ACT
MOV N$XY_KING_KILL_REWARD 100
MOV N$XY_KING_EXP_RATE 10

#IF
LARGE N$XY_KING_KILL_REWARD 0
#ACT
GAMEGOLD + <$STR(N$XY_KING_KILL_REWARD)>
SENDMSG 6 国王模式击杀奖励：获得<$STR(N$XY_KING_KILL_REWARD)>元宝。

#IF
LARGE N$XY_KING_EXP_RATE 0
#ACT
GetPlayInfo MAXEXP N$XY_KING_LEVEL_MAXEXP
FORMULATION <$STR(N$XY_KING_LEVEL_MAXEXP)>*<$STR(N$XY_KING_EXP_RATE)>/100 N$XY_KING_EXP_REWARD

#IF
LARGE N$XY_KING_EXP_REWARD 0
#ACT
CHANGEEXP + <$STR(N$XY_KING_EXP_REWARD)>
SENDMSG 6 国王模式击杀经验：获得当前升级经验的<$STR(N$XY_KING_EXP_RATE)>%，共<$STR(N$XY_KING_EXP_REWARD)>点经验。
BREAK
}
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def replace_inclusive(text: str, start: str, end: str, replacement: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"受管标记无法唯一识别：{start} / {end}")
    begin = text.index(start)
    finish = text.index(end, begin) + len(end)
    return text[:begin] + replacement + text[finish:]


def replace_between_labels(text: str, start: str, end: str, replacement: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"脚本标签无法唯一识别：{start} / {end}")
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[:begin] + replacement + text[finish:]


def validate(q_text: str, core_text: str) -> list[str]:
    checks: dict[str, bool] = {}
    schedule = q_text[q_text.index("; XY-KING-AUTO-REVIVE-SCHEDULE-BEGIN") : q_text.index("; XY-KING-AUTO-REVIVE-SCHEDULE-END")]
    revive = q_text[q_text.index("; XY-KING-AUTO-REVIVE-BEGIN") : q_text.index("; XY-KING-AUTO-REVIVE-END")]
    play_die = core_text[core_text.index("[@XY_KING_PLAY_DIE]") : core_text.index("[@XY_KING_REVIVAL]")]
    revival = core_text[core_text.index("[@XY_KING_REVIVAL]") : core_text.index("[@XY_KING_CLEAR_TITLE]")]
    kill = core_text[core_text.index("[@XY_KING_KILL_EXP]") :]

    volatile = ("N$XY_KING_FLOW_REGISTERED", "S$XY_KING_FLOW_TEAM", "S$XY_KING_FLOW_ROLE")
    checks["复活调度不依赖易失报名变量"] = not any(x in schedule + revive for x in volatile)
    checks["角斗场复活不依赖战斗缓存"] = "N$XY_KING_MODE" not in revive + revival
    checks["死亡结算按地图和持久名单"] = "CHECKMAPNAME XYGDZY" in play_die and play_die.count("KillByHum") == 4
    checks["奖励币种为元宝"] = "GAMEDIAMOND" not in play_die + kill and "GAMEGOLD +" in kill
    checks["普通与国王扣除已实现"] = all(x in play_die for x in ("@XY_KING_LOSS_25", "@XY_KING_LOSS_500", "GAMEGOLD - 25", "GAMEGOLD - 500", "<$GAMEGOLD>"))
    checks["普通与国王奖励已实现"] = all(x in kill for x in ("MOV N$XY_KING_KILL_REWARD 100", "MOV N$XY_KING_KILL_REWARD 500", "MOV N$XY_KING_EXP_RATE 10", "MOV N$XY_KING_EXP_RATE 50"))
    checks["击杀经验公共出口保留"] = all(x in kill for x in ("GetPlayInfo MAXEXP", "FORMULATION", "CHANGEEXP +"))
    checks["四类死亡地图调度存在"] = schedule.count("DelayCall 1000 @XY_KING_AUTO_REVIVE") == 4
    checks["野区和角斗场分流存在"] = all(x in revive for x in ("MAPMOVE XYKWA 50 50", "MAPMOVE XYKWB 50 50", "CHECKMAPNAME XYGDZY", "REALIVE"))
    checks["角斗场A/B复活点固定"] = "MAPMOVE XYGDZY 15 50" in revival and "MAPMOVE XYGDZY 100 50" in revival
    checks["国王第十次死亡仍阻止复活"] = "EQUAL N$XY_KING_A_DEATHS 10" in revive and "EQUAL N$XY_KING_B_DEATHS 10" in revive
    labels = re.findall(r"^\[@([^\]]+)\]\r?$", q_text + "\n" + core_text, re.MULTILINE)
    checks["关键标签无重复"] = all(labels.count(x) == 1 for x in ("PlayDie", "KillPlay", "Revival", "XY_KING_AUTO_REVIVE", "XY_KING_PLAY_DIE", "XY_KING_REVIVAL", "XY_KING_KILL_EXP"))
    checks["既有QFunction入口保留"] = q_text.count("@XY_KING_PLAY_DIE") == 1 and q_text.count("@XY_KING_KILL_EXP") == 1 and q_text.count("@XY_KING_REVIVAL") == 1
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("静态契约失败：" + "、".join(failed))
    return list(checks)


def main() -> None:
    q_original = QFUNCTION.read_bytes()
    core_original = CORE.read_bytes()
    if digest(q_original) != EXPECTED_Q_SHA256:
        raise SystemExit("QFunction预检后发生变化，停止写入。")
    if digest(core_original) != EXPECTED_CORE_SHA256:
        raise SystemExit("国王模式核心预检后发生变化，停止写入。")

    q_text = q_original.decode("gb18030")
    core_text = core_original.decode("gb18030")
    q_new = replace_inclusive(
        q_text,
        "; XY-KING-AUTO-REVIVE-SCHEDULE-BEGIN",
        "; XY-KING-AUTO-REVIVE-SCHEDULE-END",
        SCHEDULE_BLOCK,
    )
    q_new = replace_inclusive(
        q_new,
        "; XY-KING-AUTO-REVIVE-BEGIN",
        "; XY-KING-AUTO-REVIVE-END",
        AUTO_REVIVE_BLOCK,
    )
    core_new = replace_between_labels(
        core_text,
        "[@XY_KING_PLAY_DIE]",
        "[@XY_KING_REVIVAL]",
        PLAY_DIE_BLOCK,
    )
    core_new = replace_between_labels(
        core_new,
        "[@XY_KING_REVIVAL]",
        "[@XY_KING_CLEAR_TITLE]",
        REVIVAL_BLOCK,
    )
    if core_new.count("[@XY_KING_KILL_EXP]") != 1:
        raise SystemExit("击杀经验标签无法唯一识别，停止写入。")
    core_new = core_new[: core_new.index("[@XY_KING_KILL_EXP]")] + KILL_REWARD_BLOCK

    check_names = validate(q_new, core_new)
    q_payload = q_new.encode("gb18030")
    core_payload = core_new.encode("gb18030")
    q_tmp = QFUNCTION.with_suffix(QFUNCTION.suffix + ".king-tmp")
    core_tmp = CORE.with_suffix(CORE.suffix + ".king-tmp")
    q_tmp.write_bytes(q_payload)
    core_tmp.write_bytes(core_payload)
    if q_tmp.read_bytes().decode("gb18030") != q_new:
        raise SystemExit("QFunction临时副本校验失败。")
    if core_tmp.read_bytes().decode("gb18030") != core_new:
        raise SystemExit("核心临时副本校验失败。")

    try:
        os.replace(core_tmp, CORE)
        os.replace(q_tmp, QFUNCTION)
    except Exception:
        CORE.write_bytes(core_original)
        QFUNCTION.write_bytes(q_original)
        q_tmp.unlink(missing_ok=True)
        core_tmp.unlink(missing_ok=True)
        raise

    print(f"QFUNCTION_SHA256={digest(q_payload)}")
    print(f"CORE_SHA256={digest(core_payload)}")
    for name in check_names:
        print(f"CHECK {name}=PASS")


if __name__ == "__main__":
    main()
