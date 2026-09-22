from __future__ import annotations

import json
import unittest
from pathlib import Path

from xydp.runtime import platform_root
from xydp.validator import validate_package
from xydp.king_mode_flow import KingModeFlowService, _merge_missing_config_keys, _parse_config, _replace_map_display


class KingModePackageTests(unittest.TestCase):
    root = platform_root() / "packages/candidate"

    def package(self, package_id: str):
        return validate_package(self.root / package_id)

    def text(self, package_id: str, name: str) -> str:
        return (self.root / package_id / "payload" / name).read_text(encoding="utf-8")

    def test_all_packages_validate_and_are_candidate(self):
        for package_id in (
            "xy.optional.king-mode.core",
            "xy.optional.king-mode.npc",
            "xy.optional.king-mode.admin",
            "xy.optional.king-mode.flow",
        ):
            package = self.package(package_id)
            self.assertEqual(package.status, "candidate")
            self.assertEqual(package.engine, "LFM2")
            self.assertEqual(package.residency, "optional")

    def test_core_rules_and_event_contract(self):
        package = self.package("xy.optional.king-mode.core")
        script = self.text(package.id, "国王模式核心.txt")
        config = self.text(package.id, "国王模式配置.txt")
        for label in (
            "[@XY_KING_JOIN_A]", "[@XY_KING_JOIN_B]", "[@XY_KING_SET_A]",
            "[@XY_KING_SET_B]", "[@XY_KING_START]", "[@XY_KING_END]",
            "[@XY_KING_RESET]", "[@XY_KING_ATTACK_GUARD]", "[@XY_KING_PLAY_DIE]",
            "[@XY_KING_REVIVAL]",
        ):
            self.assertIn(label, script)
        for event in ("AttackDamage", "HeroAttackDamage", "StruckDamage", "HeroStruckDamage", "PlayDie", "Revival"):
            self.assertIn(event, json.dumps(package.operations, ensure_ascii=False))
        self.assertIn("CheckJob Warrior", script)
        self.assertIn("GIVEFENGHAO", script)
        self.assertIn("ChangeHumAbilityEX 11 +", script)
        self.assertIn("ChangeDamageValue 0 = 0", script)
        self.assertIn("CheckKillByHum", script)
        self.assertIn("<$KILLER>.GAMEDIAMOND +", script)
        self.assertIn("国王达到最大死亡次数", script)
        self.assertIn("状态 胜者 B队", script)
        self.assertIn("状态 胜者 A队", script)
        self.assertIn("普通击杀奖励=100", config)
        self.assertIn("普通死亡扣除=25", config)
        self.assertIn("国王击杀奖励=500", config)
        self.assertIn("国王死亡扣除=500", config)
        self.assertIn("每队人数=5", config)
        self.assertIn("国王最大死亡次数=10", config)
        self.assertIn("全元素=10", config)
        self.assertIn("全元素命令=待在目标服实测后填写", config)
        self.assertIn("CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\A队名单.txt <$USERNAME>", script)
        self.assertIn("CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\B队名单.txt <$USERNAME>", script)
        self.assertIn("CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\A队名单.txt <$KILLER>", script)
        self.assertIn("CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\B队名单.txt <$KILLER>", script)
        self.assertNotIn("sqlite_upsert", json.dumps(package.operations, ensure_ascii=False))
        self.assertNotIn(".py", json.dumps(package.operations, ensure_ascii=False))
        self.assertNotIn("CheckLEVELEX > 0\nCheckJob Warrior", script)

    def test_adapters_call_core_and_use_unique_npc_lines(self):
        npc = self.package("xy.optional.king-mode.npc")
        admin = self.package("xy.optional.king-mode.admin")
        npc_text = self.text(npc.id, "国王模式报名.txt")
        admin_text = self.text(admin.id, "国王模式管理.txt")
        flow_signup = self.text("xy.optional.king-mode.flow", "国王模式赛前报名模板.txt")
        for label in ("@XY_KING_JOIN_A", "@XY_KING_JOIN_B"):
            self.assertIn(label, npc_text)
        for label in ("@XY_KING_SET_A", "@XY_KING_SET_B", "@XY_KING_START", "@XY_KING_END", "@XY_KING_RESET"):
            self.assertIn(label, admin_text)
        for package in (npc, admin):
            self.assertIn("unique_line", {item["type"] for item in package.operations})
            targets = "\n".join(str(item.get("target", "")) for item in package.operations)
            self.assertIn("MerChant.txt", targets)
        self.assertIn("管理员单人测试", flow_signup)
        self.assertIn("取消当前选择", flow_signup)
        self.assertIn("[@XY_KING_FLOW_SINGLE_TEST_REQUEST]", flow_signup)
        self.assertIn("[@XY_KING_FLOW_SINGLE_TEST_RESET_REQUEST]", flow_signup)
        self.assertIn("[@XY_KING_FLOW_CANCEL]", flow_signup)
        flow = self.text("xy.optional.king-mode.flow", "国王模式赛前流程模板.txt")
        for public_label in (
            "JOIN_A_KING", "JOIN_A_COMMONER", "JOIN_B_KING", "JOIN_B_COMMONER",
            "START", "SINGLE_TEST_REQUEST", "SINGLE_TEST_RESET_REQUEST", "CANCEL",
        ):
            self.assertIn(f"[@XY_KING_FLOW_{public_label}_IMPL]", flow)
            self.assertIn(
                f"#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_{public_label}_IMPL",
                flow_signup,
            )
        self.assertNotIn(
            "#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_JOIN_A_KING\n",
            flow_signup,
        )

    def test_flow_renders_five_waves_and_clear_map_contract(self):
        service = KingModeFlowService(platform_root())
        values = service._default_values(_parse_config(service.default_config.read_text(encoding="utf-8")))
        script = service._render(service.template, values).decode("gb18030")
        self.assertEqual(values["total_waves"], 5)
        self.assertEqual(script.count("MonGenEx "), 20)
        self.assertEqual(script.count("ClearMapMon "), 10)
        self.assertIn("Check [1511] 30", script)
        self.assertIn("Check [1511] 600", script)
        self.assertIn("SET [1512] 15", script)
        for name in ("玄渊恶灵", "玄渊恶鬼", "玄渊魔将", "玄渊魔王", "玄渊终焉使"):
            self.assertIn(name, script)
        self.assertNotIn("ReadConfigFileItem", script)
        self.assertNotIn("GAMEDIAMOND", script)
        self.assertNotIn("KillMon ", script)
        self.assertIn("Check G1514 0", script)
        self.assertIn("SET G1514 1", script)
        self.assertIn("SETONTIMEREX 8 1000", script)
        self.assertNotIn("SETONTIMEREX 10", script)
        self.assertNotIn("SETOFFTIMEREX 10", script)
        self.assertNotRegex(script, r"(?:INC|DEC) \\[15(?:0\\d|1\\d)\\]")
        self.assertIn("INC G1501 1", script)
        self.assertIn("[@XY_KING_FLOW_SINGLE_TEST_START]", script)
        self.assertIn("[@XY_KING_FLOW_CANCEL_IMPL]", script)
        self.assertEqual(script.count("DelTextList "), 8)
        self.assertIn("ISADMIN", script)

    def test_existing_config_keys_are_preserved_while_new_wave_keys_are_added(self):
        old = "[刷怪]\n总波数=2\n刷新间隔分钟=5\n\n[状态]\n示例配置=0\n"
        defaults = self.text("xy.optional.king-mode.flow", "国王模式配置.txt")
        merged = _merge_missing_config_keys(old, defaults, "\n")
        cfg = _parse_config(merged)
        self.assertEqual(cfg["刷怪"]["总波数"], "2")
        self.assertEqual(cfg["刷怪"]["刷新间隔分钟"], "5")
        self.assertEqual(cfg["刷怪"]["首波延迟秒数"], "30")
        self.assertEqual(cfg["刷怪"]["第5波普通怪"], "玄渊终焉使")

    def test_mapinfo_display_replaces_header_and_keeps_flags(self):
        text = "[XYGDZY|vx605 古代庄园] FIGHT2 NORECALL\n"
        updated = _replace_map_display(text, "XYGDZY", "角斗场", "\n", "[XYGDZY|角斗场] FIGHT2")
        self.assertEqual(updated, "[XYGDZY|vx605 角斗场] FIGHT2 NORECALL\n")


if __name__ == "__main__":
    unittest.main()
