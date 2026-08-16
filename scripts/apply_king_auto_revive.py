from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


QFUNCTION = Path(r"D:\MirServer\Mir200\Envir\Market_Def\QFunction-0.txt")
CORE = Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊功能\国王模式\国王模式核心.txt")
BACKUPS = Path(r"D:\XuanYuanDevPlatform\backups")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".xydp.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def main() -> None:
    if not QFUNCTION.exists() or not CORE.exists():
        raise RuntimeError("QFunction 或国王模式核心不存在")

    qf_raw = QFUNCTION.read_bytes()
    core_raw = CORE.read_bytes()
    qf = qf_raw.decode("gb18030")
    core = core_raw.decode("gb18030")
    nl = "\r\n" if "\r\n" in qf else "\n"

    for marker in (
        "; XY-KING-AUTO-REVIVE-SCHEDULE-BEGIN",
        "; XY-KING-AUTO-REVIVE-BEGIN",
        "[@XY_KING_AUTO_REVIVE]",
    ):
        if marker in qf:
            raise RuntimeError(f"自动复活内容已经存在，停止重复写入：{marker}")

    hook_end = "; XYDP-HOOK-END xy.optional.king-mode.core PlayDie" + nl
    if qf.count(hook_end) != 1:
        raise RuntimeError("无法唯一识别国王模式 PlayDie 钩子结束位置")

    schedule = nl.join(
        [
            "; XY-KING-AUTO-REVIVE-SCHEDULE-BEGIN",
            "; 只为已报名玩家安排一次延迟回调；回调再次按死亡地图和阵营严格分流。",
            "#IF",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "#ACT",
            "DelayCall 1000 @XY_KING_AUTO_REVIVE",
            "; XY-KING-AUTO-REVIVE-SCHEDULE-END",
            "",
        ]
    )
    qf = qf.replace(hook_end, hook_end + schedule, 1)

    kill_marker = ";杀人触发" + nl
    if qf.count(kill_marker) != 1:
        raise RuntimeError("无法唯一识别 KillPlay 前插入位置")

    callback = nl.join(
        [
            "; XY-KING-AUTO-REVIVE-BEGIN",
            "; 野区死亡只回各自野区；角斗场死亡才走A/B复活点。",
            "[@XY_KING_AUTO_REVIVE]",
            "#IF",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYKWA",
            "EQUAL S$XY_KING_FLOW_TEAM A",
            "EQUAL S$XY_KING_FLOW_ROLE KING",
            "#ACT",
            "MAPMOVE XYKWA 50 50",
            "REALIVE",
            "HumanHP = 100 0 1 0 0 1",
            "HumanMP = 100 0 1 1",
            "BREAK",
            "",
            "#IF",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYKWA",
            "EQUAL S$XY_KING_FLOW_TEAM A",
            "#ACT",
            "MAPMOVE XYKWA 50 50",
            "REALIVE",
            "HumanHP = 50 0 1 0 0 1",
            "HumanMP = 50 0 1 1",
            "BREAK",
            "",
            "#IF",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYKWB",
            "EQUAL S$XY_KING_FLOW_TEAM B",
            "EQUAL S$XY_KING_FLOW_ROLE KING",
            "#ACT",
            "MAPMOVE XYKWB 50 50",
            "REALIVE",
            "HumanHP = 100 0 1 0 0 1",
            "HumanMP = 100 0 1 1",
            "BREAK",
            "",
            "#IF",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYKWB",
            "EQUAL S$XY_KING_FLOW_TEAM B",
            "#ACT",
            "MAPMOVE XYKWB 50 50",
            "REALIVE",
            "HumanHP = 50 0 1 0 0 1",
            "HumanMP = 50 0 1 1",
            "BREAK",
            "",
            "; A方国王在角斗场第10次死亡后不再复活。",
            "#IF",
            "EQUAL N$XY_KING_MODE 1",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYGDZY",
            "EQUAL S$XY_KING_FLOW_TEAM A",
            "EQUAL S$XY_KING_FLOW_ROLE KING",
            "EQUAL N$XY_KING_A_DEATHS 10",
            "#ACT",
            "SENDMSG 6 你已达到国王最大死亡次数，不能再次复活。",
            "BREAK",
            "",
            "; B方国王在角斗场第10次死亡后不再复活。",
            "#IF",
            "EQUAL N$XY_KING_MODE 1",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYGDZY",
            "EQUAL S$XY_KING_FLOW_TEAM B",
            "EQUAL S$XY_KING_FLOW_ROLE KING",
            "EQUAL N$XY_KING_B_DEATHS 10",
            "#ACT",
            "SENDMSG 6 你已达到国王最大死亡次数，不能再次复活。",
            "BREAK",
            "",
            "; 角斗场其余有效死亡执行复活，成功后由现有[@Revival]分配A/B复活点和血蓝。",
            "#IF",
            "EQUAL N$XY_KING_MODE 1",
            "EQUAL N$XY_KING_FLOW_REGISTERED 1",
            "CHECKMAPNAME XYGDZY",
            "#ACT",
            "REALIVE",
            "BREAK",
            "; XY-KING-AUTO-REVIVE-END",
            "",
        ]
    )
    qf = qf.replace(kill_marker, callback + kill_marker, 1)

    # 静态契约：野区绝不写角斗场坐标，角斗场复用既有 Revival 分流。
    if qf.count("DelayCall 1000 @XY_KING_AUTO_REVIVE") != 1:
        raise RuntimeError("自动复活延迟入口数量异常")
    if qf.count("[@XY_KING_AUTO_REVIVE]") != 1:
        raise RuntimeError("自动复活回调标签不唯一")
    block = qf.split("; XY-KING-AUTO-REVIVE-BEGIN", 1)[1].split(
        "; XY-KING-AUTO-REVIVE-END", 1
    )[0]
    if block.count("MAPMOVE XYKWA 50 50") != 2:
        raise RuntimeError("A野区国王/平民复活分支不完整")
    if block.count("MAPMOVE XYKWB 50 50") != 2:
        raise RuntimeError("B野区国王/平民复活分支不完整")
    if "MAPMOVE XYGDZY" in block:
        raise RuntimeError("自动回调不应直接硬编码角斗场坐标")
    if block.count("REALIVE") != 5:
        raise RuntimeError("REALIVE分支数量不符合预期")
    if "CHECKMAPNAME XYGDZY" not in block:
        raise RuntimeError("缺少角斗场地图门禁")
    if "EQUAL N$XY_KING_A_DEATHS 10" not in block or "EQUAL N$XY_KING_B_DEATHS 10" not in block:
        raise RuntimeError("缺少国王第10次死亡阻止")

    # 既有 Revival 必须仍能把角斗场双方送到唯一复活点。
    required_core = (
        "MOV N$XY_KING_A_X 15",
        "MOV N$XY_KING_A_Y 50",
        "MOV N$XY_KING_B_X 100",
        "MOV N$XY_KING_B_Y 50",
        "HumanHP = 100 0 1 0 0 1",
        "HumanHP = 50 0 1 0 0 1",
    )
    if not all(item in core for item in required_core):
        raise RuntimeError("既有角斗场 Revival 回点/血蓝契约不完整")

    qf_new = qf.encode("gb18030")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUPS / f"king_auto_revive_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(QFUNCTION, backup / "QFunction-0.txt")

    try:
        atomic_write(QFUNCTION, qf_new)
    except Exception:
        atomic_write(QFUNCTION, qf_raw)
        raise

    receipt = {
        "operation": "king-mode-map-aware-auto-revive",
        "status": "applied-awaiting-game-validation",
        "backup": str(backup),
        "qfunction": {
            "path": str(QFUNCTION),
            "before": sha256(qf_raw),
            "after": sha256(qf_new),
        },
        "routing": {
            "XYKWA": "A -> XYKWA 50,50",
            "XYKWB": "B -> XYKWB 50,50",
            "XYGDZY": "existing Revival: A 15,50 / B 100,50",
        },
        "delay_ms": 1000,
        "king_arena_max_deaths": 10,
    }
    (backup / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
