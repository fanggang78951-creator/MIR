from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path


PLATFORM = Path(r"D:\XuanYuanDevPlatform")
SERVER = Path(r"D:\MirServer")
sys.path.insert(0, str(PLATFORM / "src"))

from xydp.encoding import encode_text_document, read_text_document  # noqa: E402
from xydp.installer import InstallPlan, Installer, PlannedChange  # noqa: E402
from xydp.repository import PackageRepository  # noqa: E402


FILES = {
    "qfunction": Path("Mir200/Envir/Market_Def/QFunction-0.txt"),
    "core": Path("Mir200/Envir/QuestDiary/玄渊功能/国王模式/国王模式核心.txt"),
    "config": Path("Mir200/Envir/QuestDiary/玄渊配置/国王模式配置.txt"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}：预期唯一命中1处，实际{count}处")
    return text.replace(old, new, 1)


def main() -> None:
    docs = {name: read_text_document(SERVER / rel) for name, rel in FILES.items()}
    before = {name: (SERVER / rel).read_bytes() for name, rel in FILES.items()}

    qf = docs["qfunction"].text
    core = docs["core"].text
    config = docs["config"].text
    if qf.count("[@KillPlay]") != 1:
        raise RuntimeError("QFunction中的[@KillPlay]不是唯一入口")
    if "@XY_KING_KILL_EXP" in qf or "[@XY_KING_KILL_EXP]" in core:
        raise RuntimeError("国王模式杀人经验入口已经存在，禁止重复插入")
    for field in ("普通击杀经验百分比=", "国王击杀经验百分比="):
        if field in config:
            raise RuntimeError(f"配置字段已经存在：{field}")

    nl_qf = docs["qfunction"].newline
    old_qf = nl_qf.join((
        "[@KillPlay]",
        "#IF",
        "#ACT",
        "SENDMSG 0 江湖告急：『<$USERNAME>』在%m的%x:%y将『<$CURRRTARGETNAME>』杀害....",
        "break",
    ))
    new_qf = nl_qf.join((
        "[@KillPlay]",
        "; XY-KING-KILL-EXP-BEGIN",
        "#IF",
        "#ACT",
        "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_KILL_EXP",
        "; XY-KING-KILL-EXP-END",
        "#IF",
        "#ACT",
        "SENDMSG 0 江湖告急：『<$USERNAME>』在%m的%x:%y将『<$CURRRTARGETNAME>』杀害....",
        "break",
    ))
    qf = replace_once(qf, old_qf, new_qf, "KillPlay经验入口")

    nl_core = docs["core"].newline
    exp_block = nl_core.join((
        "",
        "[@XY_KING_KILL_EXP]",
        "{",
        "; 百分比由国王模式配置.txt的[奖励]渲染：普通人物10%，国王50%。",
        "; 同队问题由引擎国家模式和现有同队免伤处理，本分支不重复判断同队。",
        "#IF",
        "#ACT",
        "MOV N$XY_KING_EXP_RATE 0",
        "MOV N$XY_KING_LEVEL_MAXEXP 0",
        "MOV N$XY_KING_EXP_REWARD 0",
        "",
        "#IF",
        "EQUAL N$XY_KING_MODE 1",
        "CHECKMAPNAME XYGDZY",
        "CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\A队国王名单.txt <$CURRRTARGETNAME>",
        "#ACT",
        "MOV N$XY_KING_EXP_RATE 50",
        "",
        "#IF",
        "EQUAL N$XY_KING_MODE 1",
        "CHECKMAPNAME XYGDZY",
        "CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\B队国王名单.txt <$CURRRTARGETNAME>",
        "#ACT",
        "MOV N$XY_KING_EXP_RATE 50",
        "",
        "#IF",
        "EQUAL N$XY_KING_MODE 1",
        "CHECKMAPNAME XYGDZY",
        "CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\A队平民名单.txt <$CURRRTARGETNAME>",
        "#ACT",
        "MOV N$XY_KING_EXP_RATE 10",
        "",
        "#IF",
        "EQUAL N$XY_KING_MODE 1",
        "CHECKMAPNAME XYGDZY",
        "CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\B队平民名单.txt <$CURRRTARGETNAME>",
        "#ACT",
        "MOV N$XY_KING_EXP_RATE 10",
        "",
        "#IF",
        "LARGE N$XY_KING_EXP_RATE 0",
        "#ACT",
        "GetPlayInfo MAXEXP N$XY_KING_LEVEL_MAXEXP",
        "FORMULATION <$STR(N$XY_KING_LEVEL_MAXEXP)>*<$STR(N$XY_KING_EXP_RATE)>/100 N$XY_KING_EXP_REWARD",
        "",
        "#IF",
        "LARGE N$XY_KING_EXP_REWARD 0",
        "#ACT",
        "CHANGEEXP + <$STR(N$XY_KING_EXP_REWARD)>",
        "SENDMSG 6 国王模式击杀奖励：获得当前升级经验的<$STR(N$XY_KING_EXP_RATE)>%，共<$STR(N$XY_KING_EXP_REWARD)>点经验。",
        "BREAK",
        "}",
    ))
    if not core.endswith(("\r\n", "\n")):
        core += nl_core
    core += exp_block.lstrip("\r\n") + nl_core

    nl_cfg = docs["config"].newline
    config = replace_once(
        config,
        "国王死亡扣除=500" + nl_cfg,
        "国王死亡扣除=500" + nl_cfg + "普通击杀经验百分比=10" + nl_cfg + "国王击杀经验百分比=50" + nl_cfg,
        "奖励配置插入点",
    )

    after_text = {"qfunction": qf, "core": core, "config": config}
    stamp = time.strftime("%Y%m%d_%H%M%S")
    manual_backup = SERVER / "Backup" / f"XuanYuan_KingKillExp_{stamp}"
    for name, rel in FILES.items():
        source = SERVER / rel
        destination = manual_backup / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    changes = []
    for name, rel in FILES.items():
        after = encode_text_document(docs[name], after_text[name])
        changes.append(PlannedChange(
            relative_path=rel.as_posix(),
            before=before[name],
            after=after,
            operation="direct_king_kill_exp_percent",
            package_id="xy.direct.king-mode.kill-exp",
        ))

    plan = InstallPlan(
        target_root=str(SERVER),
        client_root=None,
        package_ids=["xy.direct.king-mode.kill-exp"],
        package_versions={"xy.direct.king-mode.kill-exp": "1.0.0"},
        parameters={
            "normal_kill_exp_percent": 10,
            "king_kill_exp_percent": 50,
            "check_same_team": False,
            "map": "XYGDZY",
        },
        changes=changes,
        warnings=["本轮先写当前服，游戏验收通过后再回填平台母版。"],
        operation_type="direct-king-mode-kill-exp-percent",
    )
    receipt = Installer(PackageRepository(PLATFORM / "packages"), PLATFORM / "backups").install(plan)

    current = {name: read_text_document(SERVER / rel).text for name, rel in FILES.items()}
    checks = {
        "killplay_unique": current["qfunction"].count("[@KillPlay]") == 1,
        "hook_call_unique": current["qfunction"].count("@XY_KING_KILL_EXP") == 1,
        "handler_unique": current["core"].count("[@XY_KING_KILL_EXP]") == 1,
        "normal_rate_10": current["core"].count("MOV N$XY_KING_EXP_RATE 10") == 2,
        "king_rate_50": current["core"].count("MOV N$XY_KING_EXP_RATE 50") == 2,
        "maxexp_read": current["core"].count("GetPlayInfo MAXEXP N$XY_KING_LEVEL_MAXEXP") == 1,
        "formula_unique": current["core"].count("FORMULATION <$STR(N$XY_KING_LEVEL_MAXEXP)>*<$STR(N$XY_KING_EXP_RATE)>/100 N$XY_KING_EXP_REWARD") == 1,
        "changeexp_unique": current["core"].count("CHANGEEXP + <$STR(N$XY_KING_EXP_REWARD)>") == 1,
        "same_team_check_absent": "本分支不重复判断同队" in current["core"],
        "config_rates": "普通击杀经验百分比=10" in current["config"] and "国王击杀经验百分比=50" in current["config"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"写入后验证失败：{checks}")

    print(json.dumps({
        "transaction_id": receipt.transaction_id,
        "platform_backup": receipt.backup_root,
        "manual_backup": str(manual_backup),
        "checks": checks,
        "hashes": {name: sha256((SERVER / rel).read_bytes()) for name, rel in FILES.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
