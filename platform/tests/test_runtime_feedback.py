from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.runtime_feedback import contract_gaps, parse_m2_log, recent_m2_issues, unsafe_npc_commands


class RuntimeFeedbackTests(unittest.TestCase):
    def test_parse_known_npc_config_error(self):
        text = "2026/7/15 12:26:10 脚本错误: ReadConfigFileItem ..\\QuestDiary\\玄渊配置\\国王模式配置.txt 基础 战斗状态 N$XY_KING_MODE 第:14 行: D:\\MirServer\\Mir200\\Envir\\Market_Def\\玄渊国王模式_破釜沉舟-XYGDZY.txt"
        issues = parse_m2_log(text, "m2.log")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "script-error")
        self.assertEqual(issues[0].line, 14)
        self.assertIn("NPC 脚本上下文", issues[0].message)

    def test_recent_log_only_reads_latest_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "server"; log = root / "Mir200/Log"; log.mkdir(parents=True)
            (log / "old.txt").write_text("脚本错误: old 第:1 行: old.txt\n", encoding="gb18030")
            (log / "new.txt").write_text("地图环境加载成功\n", encoding="gb18030")
            issues = recent_m2_issues(root, max_files=1)
            self.assertEqual(issues, [])

    def test_unsafe_npc_command_is_reported(self):
        self.assertEqual(unsafe_npc_commands("[@Main]\n#SAY\n测试\n"), [])
        self.assertEqual(unsafe_npc_commands("[@Main]\n#SAY\n#IF\nReadConfigFileItem x y z n\n"), ["ReadConfigFileItem"])

    def test_contract_gaps_reports_missing_marker(self):
        class Change:
            relative_path = "QFunction.txt"
            after = b"@PlayLogin"
        self.assertEqual(contract_gaps([Change()], {"QFunction.txt": ["@PlayLogin"]}), [])
        self.assertEqual(contract_gaps([Change()], {"QFunction.txt": ["@PlayDie"]}), ["QFunction.txt 缺少运行入口：@PlayDie"])


if __name__ == "__main__":
    unittest.main()
