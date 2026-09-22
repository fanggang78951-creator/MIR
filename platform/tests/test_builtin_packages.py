import json
import re
import unittest
from pathlib import Path

from xydp.repository import PackageRepository
from xydp.runtime import platform_root


class BuiltinPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = platform_root()
        cls.repo = PackageRepository(cls.root / "packages")
        cls.repo.refresh()

    def test_combat_bundle_and_canonical_optional_packages_exist(self):
        expected = {
            "xy.combat-suite", "xy.combat.core", "xy.combat.power", "xy.combat.pve",
            "xy.combat.blast", "xy.combat.drop", "xy.combat.execute", "xy.combat.corpse",
            "xy.combat.runtime-refresh", "xy.combat.damage-coefficient",
            "xy.combat.monster-damage-absorb", "xy.combat.sustain",
            "xy.ops.core", "xy.ops.title", "xy.optional.rage.core", "xy.optional.donate.core",
        }
        self.assertTrue(expected.issubset(self.repo.packages))
        combat = [item.id for item in self.repo.resolve(["xy.combat-suite"])]
        self.assertTrue({"xy.combat.power", "xy.combat.corpse", "xy.combat-suite"}.issubset(combat))

    def test_unverified_bundles_remain_candidate(self):
        self.assertEqual(self.repo.packages["xy.combat-suite"].status, "candidate")
        self.assertEqual(self.repo.packages["xy.optional.rage.core"].status, "candidate")
        self.assertEqual(self.repo.packages["xy.optional.donate.core"].status, "candidate")

    def test_only_combat_and_native_base_packages_are_resident_by_default(self):
        resident = {
            item.id for item in self.repo.packages.values()
            if item.residency == "resident"
        }
        self.assertEqual(resident, {
            "xy.combat.core", "xy.combat.power", "xy.combat.pve", "xy.combat.blast",
            "xy.combat.drop", "xy.combat.execute", "xy.combat.corpse",
            "xy.combat.runtime-refresh", "xy.combat.damage-coefficient",
            "xy.combat.monster-damage-absorb", "xy.combat.sustain",
            "xy.native.auto-basic-skills", "xy.native.initial-bag-200",
            "xy.resident.equipment-level-bonus",
        })
        self.assertEqual(self.repo.packages["xy.combat-suite"].residency, "optional")
        self.assertEqual(self.repo.packages["xy.optional.rage.core"].residency, "optional")
        self.assertEqual(self.repo.packages["xy.optional.donate.core"].residency, "optional")

    def test_pve_uses_verified_change_damage_route_only(self):
        package = self.repo.packages["xy.combat.pve"]
        text = "\n".join(str(operation.get("content", "")) for operation in package.operations)
        self.assertIn("CalcPercent", text)
        self.assertIn("ChangeDamageValue", text)
        self.assertNotIn("POWERRATE", text)
        self.assertIn("XY_EQUIP_MAKER_ATTACK_ANCHOR", text)
        self.assertIn("MOV N$XY_FirstKillRate 0", text)
        self.assertIn("MOV N$XY_TailKillRate 0", text)

    def test_first_tail_variables_are_owned_by_initializer_and_execute_depends_on_it(self):
        pve = self.repo.packages["xy.combat.pve"]
        execute = self.repo.packages["xy.combat.execute"]
        self.assertIn("N$XY_FirstKillRate", pve.claims["variables"])
        self.assertIn("N$XY_TailKillRate", pve.claims["variables"])
        self.assertNotIn("N$XY_FirstKillRate", execute.claims["variables"])
        self.assertNotIn("N$XY_TailKillRate", execute.claims["variables"])
        self.assertIn("xy.combat.pve", execute.dependencies)

    def test_combat_suite_has_only_one_attack_extension_anchor(self):
        resolved = self.repo.resolve(["xy.combat-suite"])
        text = "\n".join(str(operation.get("content", "")) for package in resolved for operation in package.operations)
        self.assertEqual(text.count("XY_EQUIP_MAKER_ATTACK_ANCHOR"), 1)

    def test_equipment_contract_contains_all_requested_properties_and_anchors(self):
        path = self.root / "packages/verified/xy.combat.core/evidence/equipment_contract.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = {
            "神力倍攻", "打怪伤害", "暴击伤害", "爆率", "最大爆率", "首刀斩杀",
            "尾刀斩杀", "鞭尸概率", "伤害系数", "对怪伤害吸收", "伤害吸收上限",
        }
        self.assertEqual(set(data["properties"]), expected)
        self.assertEqual(set(data["anchors"]), {
            "XY_EQUIP_MAKER_POWER_ANCHOR", "XY_EQUIP_MAKER_ATTACK_ANCHOR",
            "XY_EQUIP_MAKER_BLAST_ANCHOR", "XY_EQUIP_MAKER_DROP_ANCHOR", "XY_EQUIP_MAKER_CORPSE_ANCHOR",
            "XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR",
            "XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR",
            "XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR",
        })

    def test_combat_core_bootstraps_all_events_used_by_combat_children(self):
        core = self.repo.packages["xy.combat.core"]
        bootstrapped = {
            item.get("label") for item in core.operations
            if item.get("type") == "ensure_event_label"
        }
        self.assertEqual(bootstrapped, {"PlayLogin", "TakeOnEx", "TakeOffEx", "AttackDamage", "KillMon"})

    def test_combat_core_enables_item_description_delivery(self):
        core = self.repo.packages["xy.combat.core"]
        operation = next(item for item in core.operations if item.get("type") == "config_set")
        self.assertEqual(operation["target"], "Mir200/!setup.txt")
        self.assertEqual(operation["values"], {
            "SendItemDescList": "1",
            "SendTzItemDescList": "1",
        })

    def test_runtime_refresh_package_recalculates_failed_properties_on_attack(self):
        package = self.repo.packages["xy.combat.runtime-refresh"]
        self.assertEqual(package.dependencies, ())
        hooks = [item for item in package.operations if item.get("type") == "event_hook"]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["label"], "AttackDamage")
        content = hooks[0]["content"]
        for anchor in (
            "XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR",
            "XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR",
            "XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR",
            "XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR",
        ):
            self.assertEqual(content.count(anchor), 1)
        self.assertIn("MOV N$XY_RT_Power 100", content)
        self.assertIn("MOV N$XY_RT_Blast 100", content)
        self.assertIn("MOV N$XY_RT_Drop 100", content)
        self.assertIn("MOV N$XY_RT_DropMax 100", content)
        self.assertIn("MOV N$XY_RT_DropFinal 100", content)
        self.assertIn("CalcPercent <$STR(N$XY_RT_Drop)> <$STR(N$XY_RT_DropMax)> N$XY_RT_DropFinal", content)
        self.assertNotIn("LARGE N$XY_RT_Drop <$STR(N$XY_RT_DropMax)>", content)
        self.assertIn("POWERRATE <$STR(N$XY_RT_Power)> 0 0 1 0", content)
        self.assertIn("SetBlastHitRate <$STR(N$XY_RT_Blast)> 0", content)
        self.assertIn("KILLMONBURSTRATE <$STR(N$XY_RT_DropFinal)>", content)

    def test_damage_coefficient_is_verified_resident_and_multiplies_power_once(self):
        package = self.repo.packages["xy.combat.damage-coefficient"]
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.residency, "resident")
        self.assertIn("xy.combat.runtime-refresh", package.dependencies)
        self.assertIn("xy.combat.damage-coefficient", self.repo.packages["xy.combat-suite"].dependencies)
        self.assertEqual(len(package.operations), 1)
        operation = package.operations[0]
        self.assertEqual(operation["type"], "managed_anchor_hook")
        self.assertEqual(operation["anchor"], "XY_DAMAGE_COEFFICIENT_PACKAGE_ANCHOR")
        content = operation["content"]
        self.assertIn("MOV N$XY_RT_DamageCoeff 100", content)
        self.assertIn("XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR", content)
        self.assertIn(
            "CalcPercent <$STR(N$XY_RT_Power)> <$STR(N$XY_RT_DamageCoeff)> N$XY_DC_FinalPower",
            content,
        )
        self.assertIn("MOV N$XY_RT_Power <$STR(N$XY_DC_FinalPower)>", content)
        self.assertNotIn("POWERRATE", content)
        self.assertNotIn("[@UserCmd", content)
        self.assertNotIn(" 1 0 1 0", content)
        self.assertNotIn(" 2 0 1 0", content)

        runtime = self.repo.packages["xy.combat.runtime-refresh"]
        runtime_content = runtime.operations[0]["content"]
        self.assertEqual(runtime_content.count("XY_DAMAGE_COEFFICIENT_PACKAGE_ANCHOR"), 1)
        self.assertLess(
            runtime_content.index("XY_DAMAGE_COEFFICIENT_PACKAGE_ANCHOR"),
            runtime_content.index("POWERRATE <$STR(N$XY_RT_Power)> 0 0 1 0"),
        )

    def test_monster_damage_absorb_is_verified_resident_and_in_combat_suite(self):
        package = self.repo.packages["xy.combat.monster-damage-absorb"]
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.residency, "resident")
        self.assertIn("xy.combat.core", package.dependencies)
        self.assertIn(
            "xy.combat.monster-damage-absorb",
            self.repo.packages["xy.combat-suite"].dependencies,
        )

    def test_sustain_is_candidate_resident_and_in_combat_suite(self):
        package = self.repo.packages["xy.combat.sustain"]
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.residency, "resident")
        self.assertEqual(package.dependencies, ())
        self.assertIn("xy.combat.sustain", self.repo.packages["xy.combat-suite"].dependencies)
        self.assertTrue(any(
            operation.get("type") == "ensure_event_label" and operation.get("label") == "Attack"
            for operation in package.operations
        ))
        content = "\n".join(str(operation.get("content", "")) for operation in package.operations)
        self.assertNotIn("ChangeState 10", content)
        self.assertIn("NOT CHECKCURRTARGETRACE = 0", content)
        self.assertIn(
            "CALCPERCENT <$PKPOWER> <$STR(N$XY_SUS_LifeSteal)> N$XY_SUS_LifeStealHeal",
            content,
        )
        self.assertIn("HUMANHP + <$STR(N$XY_SUS_LifeStealHeal)>", content)
        self.assertIn("SetOnTimer 19 1", content)
        self.assertIn("XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR", content)
        self.assertNotIn("N$XY_SUS_HPPerSec", content)
        self.assertIn("OnTimer19", package.claims.get("labels", []))

    def test_drop_and_max_drop_are_independent_multipliers(self):
        package = self.repo.packages["xy.combat.drop"]
        content = next(item["content"] for item in package.operations if item["type"] == "managed_block")
        self.assertEqual(package.version, "1.2.0")
        self.assertIn("MOV N$XY_最大爆率 100", content)
        self.assertIn("MOV N$XY_DropFinal 100", content)
        self.assertIn(
            "CalcPercent <$STR(N$XY_最终爆率)> <$STR(N$XY_最大爆率)> N$XY_DropFinal",
            content,
        )
        self.assertNotIn("MOV N$XY_最大爆率 1000", content)
        self.assertNotIn("LARGE N$XY_最终爆率 <$STR(N$XY_最大爆率)>", content)
        self.assertEqual((100 + 500) * (100 + 500) // 100, 3600)

    def test_failed_recalc_packages_depend_on_runtime_refresh(self):
        for package_id in ("xy.combat.power", "xy.combat.blast", "xy.combat.drop"):
            self.assertIn("xy.combat.runtime-refresh", self.repo.packages[package_id].dependencies)

    def test_equipment_recalc_delaygotos_are_inside_action_sections(self):
        expected = {
            "xy.combat.power": "DELAYGOTO 1 @XYDP_RecalcPower",
            "xy.combat.blast": "DELAYGOTO 2 @XYDP_RecalcBlast",
            "xy.combat.drop": "DELAYGOTO 3 @XYDP_RecalcDrop",
        }
        for package_id, command in expected.items():
            package = self.repo.packages[package_id]
            hooks = [item for item in package.operations if item.get("type") == "event_hook"]
            self.assertEqual({item.get("label") for item in hooks}, {"PlayLogin", "TakeOnEx", "TakeOffEx"})
            for hook in hooks:
                self.assertEqual(hook["content"], f"#IF\n#ACT\n{command}")

    def test_builtin_payloads_exclude_debug_and_test_routes(self):
        forbidden = ("XY_VERIFY", "测试装备", "POWERRATE 200 60 0 0 2")
        for package in self.repo.packages.values():
            text = "\n".join(str(operation.get("content", "")) for operation in package.operations)
            user_cmd_labels = re.findall(r"\[@UserCmd(\d+)\]", text, flags=re.IGNORECASE)
            if package.id == "xy.optional.recycle.core":
                self.assertEqual(user_cmd_labels, ["31"])
            elif package.id == "xy.ui.world-map.test-grant":
                self.assertEqual(package.status, "candidate")
                self.assertEqual(package.residency, "optional")
                self.assertEqual(user_cmd_labels, ["90"])
            else:
                self.assertEqual(user_cmd_labels, [], f"{package.id} contains a UserCmd route")
            for token in forbidden:
                self.assertNotIn(token, text, f"{package.id} contains {token}")

    def test_remaining_title_npc_location_is_parameterized(self):
        for package_id in ("xy.ops.title",):
            package = self.repo.packages[package_id]
            self.assertTrue(any(name.endswith("_map") for name in package.parameters))
            rendered_targets = "\n".join(str(item.get("target", "")) + str(item.get("line", "")) for item in package.operations)
            self.assertNotIn("chushidi", rendered_targets)

    def test_first_pick_is_optional_and_preserves_config_and_runtime_state(self):
        package = self.repo.packages["xy.ops.first-pick"]
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.residency, "optional")

        hook = next(item for item in package.operations if item.get("type") == "event_hook")
        self.assertEqual(hook["label"], "PickUpItemEX")
        self.assertEqual(hook.get("target_encoding"), "gb18030")
        self.assertIn("#CALL [\\首爆脚本\\首爆处理.txt] @首爆拾取处理", hook["content"])
        bootstraps = [item for item in package.operations if item.get("type") == "ensure_event_label"]
        self.assertEqual([item.get("label") for item in bootstraps], ["PickUpItemEX"])
        self.assertTrue(all(item.get("target_encoding") == "gb18030" for item in bootstraps))

        protected_targets = {
            "Mir200/Envir/QuestDiary/首爆脚本/首爆奖励配置.txt",
            "Mir200/Envir/QuestDiary/首爆脚本/已领取奖励.txt",
        }
        protected_operations = [item for item in package.operations if item.get("target") in protected_targets]
        self.assertEqual({item["target"] for item in protected_operations}, protected_targets)
        self.assertTrue(all(item.get("preserve_existing") is True for item in protected_operations))

        script = (
            self.root / "packages/verified/xy.ops.first-pick/payload/首爆脚本/首爆处理_utf8.txt"
        ).read_text(encoding="utf-8")
        config = (
            self.root / "packages/verified/xy.ops.first-pick/payload/首爆脚本/首爆奖励配置.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("[首爆奖励配置]", config)
        self.assertIn("首爆奖励配置.txt 首爆奖励配置 <$PICKDROPITEMNAME>", script)
        self.assertNotIn("首爆奖励配置.txt 首爆奖励 <$PICKDROPITEMNAME>", script)
        self.assertIn("MOVR N$首爆公告坐标 50 200", script)
        self.assertNotIn("MOVR <$STR(N$首爆公告坐标)>", script)
        used_variables = set(re.findall(r"[NS]\$[\u4e00-\u9fffA-Za-z0-9_]+", script))
        self.assertEqual(used_variables, set(package.claims["variables"]))

    def test_initial_bag_200_is_resident_candidate_with_correct_native_formula(self):
        package = self.repo.packages["xy.native.initial-bag-200"]
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.residency, "resident")
        self.assertEqual(package.version, "2.0.0-candidate.1")
        self.assertEqual(len(package.operations), 1)
        operation = package.operations[0]
        self.assertEqual(operation["type"], "event_hook")
        self.assertEqual(operation["target"], "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt")
        self.assertEqual(operation["label"], "登陆设置")
        self.assertIn("ExtBagPageCount = 4", operation["content"])
        self.assertIn("ExtBagOpenItemCount + 160", operation["content"])
        self.assertNotIn("ExtBagOpenItemCount =", operation["content"])
        self.assertFalse(
            (self.root / "packages/candidate/xy.native.initial-bag-200/payload/初始背包200格.txt").exists()
        )


if __name__ == "__main__":
    unittest.main()
