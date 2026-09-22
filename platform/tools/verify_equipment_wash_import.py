from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from xydp.equipment_wash import (
    ATTACK_SPEED_CORE_RELATIVE,
    EFFECT_CORE_RELATIVE,
    EquipmentWashImportService,
    MAIN_RELATIVE,
    RANDOM_CORE_RELATIVE,
    TEXTVAR_LINES,
    WASH_DIRECTORY,
)
from xydp.mingge_dual import _script_text


def read_script(path: Path) -> str:
    return _script_text(path.read_bytes())


def verify(server: Path, document: Path, platform: Path, client: Path | None = None) -> dict[str, object]:
    root = Path(server).resolve()
    envir = root / "Mir200/Envir"
    violations: list[str] = []
    checks: dict[str, object] = {}
    service = EquipmentWashImportService(platform)
    plan = service.preflight(root, document, client=client)
    checks["repeat_preflight_blockers"] = list(plan.blockers)
    checks["repeat_preflight_change_count"] = len(plan.changes)
    if plan.blockers or plan.changes:
        violations.append("重复预检必须无阻止且无待写入变更")

    if plan.blockers:
        return {"status": "failed", "server": str(root), "document": str(document), "violations": list(plan.blockers), "checks": checks}
    params = plan.target_parameters
    directory = Path("Mir200/Envir/QuestDiary") / params["wash_core_directory"]
    main_relative = Path(f"Mir200/Envir/Market_Def/{params['wash_npc_script']}-{params['wash_npc_map']}.txt")
    checks["target_parameters"] = params
    checks["external_call_targets"] = list(plan.external_calls)
    # The service validates the actual CALL graph; internal GOTO labels are not a wrapper requirement.
    random_core = read_script(root / directory / "洗练词条随机核心.txt")
    checks["randomex_1_1000_count"] = len(re.findall(r"(?m)^RANDOMEX 1 1000$", random_core))
    checks["randomex_category_heads"] = [
        len(re.findall(rf"(?m)^RANDOMEX 1 {value}$", random_core)) for value in range(15, 1, -1)
    ]
    checks["randomex_tier_80_100_count"] = random_core.count("RANDOMEX 80 100")
    checks["randomex_tier_40_100_count"] = random_core.count("RANDOMEX 40 100")
    checks["randomex_tier_40_60_count"] = random_core.count("RANDOMEX 40 60")
    if checks["randomex_1_1000_count"] != 2 or any(value != 2 for value in checks["randomex_category_heads"]):
        violations.append("随机核心缺少完整的15类等权或千分之一突破分支")
    effect_core = read_script(root / directory / "洗练词条实效核心.txt")
    required_effects = (
        "ChangeHumAbility 6 =", "ChangeHumAbility 8 =", "ChangeHumAbility 10 =",
        "ChangeHumAbilityPercentage 5 =", "ChangeHumAbilityPercentage 10 =",
        "INC N$XY_EXEC_Toughness", "INC N$XY_SUS_LifeSteal", "INC N$XY_MDA_CapBonus",
    )
    checks["effect_core_required"] = {item: item in effect_core for item in required_effects}
    if not all(checks["effect_core_required"].values()):
        violations.append("实效核心缺少已验证的属性汇总出口")
    checks["direct_script_blocks"] = {}
    for filename, label in (
        ("仙级直出.txt", "仙级特殊"), ("圣级直出.txt", "圣级特殊"),
        ("天赐开光.txt", "天赐特殊"), ("神佑开光.txt", "神佑特殊"),
    ):
        text = read_script(root / directory / filename)
        complete = bool(re.search(rf"(?ms)^\[@{label}\]\n\{{\n.*?^\}}\s*$", text))
        checks["direct_script_blocks"][filename] = complete
    if not all(checks["direct_script_blocks"].values()):
        violations.append("四份直出/开光脚本存在无法提取完整CALL脚本体的入口")

    textvar = read_script(envir / "CustomItemPropertyTextVarList.txt").splitlines()
    checks["textvar_lines"] = {str(line): textvar[line - 1] if len(textvar) >= line else "" for line in TEXTVAR_LINES.values() if line >= 43}
    if any(not value.strip() for value in checks["textvar_lines"].values()):
        violations.append("TextVar 43至55存在空行")

    main = read_script(root / main_relative)
    checks["main_uses_dynamic_value_ex"] = main.count("SetCustomItemValueEx boxitem27")
    checks["main_calls_random_core"] = main.count("洗练词条随机核心.txt")
    if checks["main_uses_dynamic_value_ex"] != 8 or checks["main_calls_random_core"] != 8:
        violations.append("主洗练脚本未完整改为8个动态词条写入位")

    qfunction = read_script(envir / "Market_Def/QFunction-0.txt")
    checks["qfunction_managed_block_count"] = qfunction.count("XY-EQUIPMENT-WASH-IMPORT-V1-") // 2
    speed = read_script(root / params["attack_speed_core_relative"])
    checks["speed_core_hook_count"] = speed.count("XY-EQUIPMENT-WASH-IMPORT-V1-NORMAL-SPEED") // 2
    if checks["qfunction_managed_block_count"] != 9 or checks["speed_core_hook_count"] != 1:
        violations.append("公共汇总CALL锚点数量不符合预期")

    return {
        "status": "passed" if not violations else "failed",
        "server": str(root),
        "document": str(Path(document).resolve()),
        "violations": violations,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证装备洗练TXT统一候选静态合同")
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--platform", type=Path, required=True)
    parser.add_argument("--client", type=Path, help="只读校验已准备好的工作台资源")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.server, args.document, args.platform, args.client)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
