from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from xydp.skill_upgrade import (
    LEGACY_PACKAGE,
    _strip_legacy,
    compile_backfill,
    compile_qfunction,
    load_workbook,
)


ROOT = Path(
    r"D:\codex临时工作区\elden-npc-v21"
) / (
    "艾尔登法环_全NPC平台填写_V2.1_20260920-normalized"
)
WORKBOOK = ROOT / "C01_漂流群岛_技能" / "12_战士技能强化.xlsx"


class SkillUpgradeV21Tests(unittest.TestCase):
    def test_filled_bundle_contains_five_chains_and_45_cost_rows(self):
        rules, costs = load_workbook(WORKBOOK)

        self.assertEqual(len(rules), 5)
        self.assertEqual(len(costs), 45)
        self.assertEqual({rule.unlock_level for rule in rules}, {9})
        self.assertEqual(
            {rule.target for rule in rules},
            {"开天斩", "逐日剑法", "双龙斩", "十步一杀", "群体施毒术"},
        )

    def test_compiler_generates_all_routes_and_login_backfill(self):
        rules, costs = load_workbook(WORKBOOK)
        selected = {rule.source: type("Skill", (), {"mag_id": index})() for index, rule in enumerate(rules, 1)}

        qfunction = compile_qfunction(rules, costs, selected)
        backfill = compile_backfill(rules)

        self.assertEqual(qfunction.count("_CONFIRM]"), 45)
        for rule in rules:
            self.assertIn(f"ADDSKILL {rule.target} 3", qfunction)
            self.assertIn(f"ADDSKILL {rule.target} 3", backfill)

    def test_historical_block_and_hook_checksum_conventions_are_verified(self):
        block_body = "[@A]\n#IF\n#ACT\nBREAK\n"
        block_hash = hashlib.sha256(block_body.encode("gb18030")).hexdigest()
        block = (
            f"; XYDP-LAB-BEGIN {LEGACY_PACKAGE} SHA256={block_hash}\r\n"
            + block_body.replace("\n", "\r\n")
            + f"; XYDP-LAB-END {LEGACY_PACKAGE}\r\n"
        )
        hook_body = "#CALL [\\玄渊实验室\\技能强化\\登录补写.txt] @XY_WSU_LOGIN_BACKFILL"
        hook_hash = hashlib.sha256(hook_body.encode("utf-8")).hexdigest()
        hook = (
            f"; XYDP-LAB-HOOK-BEGIN {LEGACY_PACKAGE} SHA256={hook_hash}\r\n"
            + hook_body
            + "\r\n"
            + f"; XYDP-LAB-HOOK-END {LEGACY_PACKAGE}\r\n"
        )

        self.assertEqual(_strip_legacy("before\r\n" + block + "after\r\n", "block"), "before\r\nafter\r\n")
        self.assertEqual(_strip_legacy("before\r\n" + hook + "after\r\n", "hook"), "before\r\nafter\r\n")


if __name__ == "__main__":
    unittest.main()
