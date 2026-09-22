from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EQUIPMENT_ROOT / "src"))


def tree_hash(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def make_target(root: Path) -> None:
    (root / "Mir200/Envir/Market_Def").mkdir(parents=True)
    (root / "Mir200/Envir/MapQuest_Def").mkdir(parents=True)
    (root / "Mud2/DB").mkdir(parents=True)
    (root / "Mir200/M2Server.exe").write_bytes(b"fixture")
    for name in ("ItemDescList.txt", "ItemRuleList.txt", "GroupItemList.txt"):
        (root / "Mir200/Envir" / name).write_bytes(b"")
    (root / "Mir200/Envir/Market_Def/QFunction-0.txt").write_text(
        "[@PlayLogin]\n#ACT\n"
        "; XY_EQUIP_MAKER_LOGIN_ANCHOR\n"
        "; XY_EQUIP_MAKER_POWER_ANCHOR\n"
        "; XY_EQUIP_MAKER_ATTACK_ANCHOR\n"
        "; XY_EQUIP_MAKER_BLAST_ANCHOR\n"
        "; XY_EQUIP_MAKER_DROP_ANCHOR\n"
        "; XY_EQUIP_MAKER_CORPSE_ANCHOR\n",
        encoding="gb18030",
    )
    (root / "Mir200/Envir/MapQuest_Def/QManage.txt").write_text(
        "[@MAIN1]\n#IF\n#ACT\nBREAK\n",
        encoding="gb18030",
    )
    attribute_panel = root / "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt"
    attribute_panel.parent.mkdir(parents=True)
    attribute_panel.write_text(
        "; XY-EQUIPMENT-WASH-UI-END TEXT47_EXEC_CHANCE\r\n"
        "; XY-EQUIPMENT-WASH-UI-END TEXT48_EXEC_TIME\r\n"
        "; XY-EQUIPMENT-WASH-UI-END TEXT49_EXEC_DAMAGE\r\n",
        encoding="gb18030",
    )
    connection = sqlite3.connect(root / "Mud2/DB/ApexM2.DB")
    connection.execute(
        "CREATE TABLE StdItems (Idx INTEGER PRIMARY KEY, Name TEXT, StdMode INTEGER, Shape INTEGER, Looks INTEGER, Ac INTEGER, Ac2 INTEGER)"
    )
    connection.execute("INSERT INTO StdItems VALUES (1, '青铜头盔', 15, 0, 1, 0, 1)")
    connection.commit()
    connection.close()


class EquipmentPreflightTests(unittest.TestCase):
    def compiled(self, name: str = "第三方头盔", with_resource: bool = False):
        from xyequip.batch import BatchEquipmentService

        row = {"名称": name, "部位": "头盔", "防御": "0-1"}
        if with_resource:
            row["来源编号"] = "4460"
        return BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows([row], Path("fixture.xlsx"))

    def test_invalid_target_is_rejected(self):
        from xyequip.planner import EquipmentPlanner, EquipmentPreflightError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(EquipmentPreflightError, "缺少"):
                EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(Path(directory), self.compiled())

    def test_preflight_is_read_only_and_lists_all_text_and_db_changes(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            before = tree_hash(target)
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, self.compiled())
            self.assertEqual(tree_hash(target), before)
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.equipment_names, ["第三方头盔"])
            relative = {change.relative_path for change in plan.changes}
            self.assertIn("Mud2/DB/ApexM2.DB", relative)
            self.assertIn("Mir200/Envir/ItemDescList.txt", relative)
            self.assertIn("Mir200/Envir/Market_Def/QFunction-0.txt", relative)

    def test_ring_without_xlsx_template_selects_lowest_idx_slot_base(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (50, '高编号戒指母版', 22, 50, 50, 5, 6)")
            connection.execute("INSERT INTO StdItems VALUES (10, '低编号戒指母版', 22, 10, 10, 1, 2)")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "自动模板戒指", "部位": "戒指", "防御": "0-1"}],
                Path("fixture.xlsx"),
            )

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)

            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.base_templates, {"自动模板戒指": "低编号戒指母版"})

    def test_slot_without_target_base_uses_platform_base_profile(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "无母版戒指", "部位": "戒指"}],
                Path("fixture.xlsx"),
            )

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)

            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.base_templates, {"无母版戒指": "平台基础母版（戒指，StdMode=22）"})

    def test_extended_slot_uses_same_target_stdmode_template_resolution(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (83, '时装勋章母版', 83, 0, 83, 0, 0)")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "新时装勋章", "部位": "时装勋章"}],
                Path("fixture.xlsx"),
            )

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)

            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.base_templates, {"新时装勋章": "时装勋章母版"})

    def test_all_extended_slots_use_platform_base_profiles_on_blank_target(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            expected = {
                "盾牌": 12,
                "护身符": 25,
                "马牌": 28,
                "宝石": 63,
                "军鼓": 65,
                "时装衣服": 66,
                "时装女衣服": 67,
                "时装武器": 68,
                "时装项链": 75,
                "时装头盔": 78,
                "时装手镯": 79,
                "时装戒指": 81,
                "时装勋章": 83,
                "时装腰带": 84,
                "时装靴子": 86,
                "时装宝石": 88,
                "灵玉": 90,
            }
            rows = [
                {"名称": f"空白服{slot}", "部位": slot}
                for slot in expected
            ]
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                rows, Path("fixture.xlsx")
            )

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)

            self.assertEqual(plan.blockers, [])
            self.assertEqual(
                plan.base_templates,
                {
                    f"空白服{slot}": f"平台基础母版（{slot}，StdMode={mode}）"
                    for slot, mode in expected.items()
                },
            )

    def test_extended_platform_profiles_are_neutral_structures(self):
        import json

        profile_path = EQUIPMENT_ROOT / "profiles/slot_base_profiles.json"
        profiles = json.loads(profile_path.read_text(encoding="utf-8"))["profiles"]
        required_modes = {12, 25, 28, 63, 65, 66, 67, 68, 75, 78, 79, 81, 83, 84, 86, 88, 90}
        gameplay_fields = {"Looks", "Ac", "Ac2", "Mac", "Mac2", "Dc", "Dc2", "Mc", "Mc2", "Sc", "Sc2", "HP", "MP", "Element"}

        self.assertTrue(required_modes <= {int(mode) for mode in profiles})
        for mode in required_modes:
            with self.subTest(mode=mode):
                fields = profiles[str(mode)]["fields"]
                self.assertEqual(fields["StdMode"], mode)
                self.assertEqual(fields["Shape"], 0)
                self.assertFalse(gameplay_fields & set(fields))

    def test_update_reverse_mapping_remains_on_original_canonical_slots(self):
        from xyequip.update import _slot_for_mode

        self.assertEqual(_slot_for_mode(22), "戒指")
        self.assertEqual(_slot_for_mode(26), "手镯")
        self.assertEqual(_slot_for_mode(30), "勋章")

    def test_duplicate_equipment_name_blocks_install(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (2, '第三方头盔', 15, 0, 2, 0, 1)")
            connection.commit()
            connection.close()
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, self.compiled())
            self.assertTrue(any("已存在" in item for item in plan.blockers))

    def test_resource_row_requires_client_data(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, self.compiled(with_resource=True))
            self.assertTrue(any("客户端" in item for item in plan.blockers))

    def test_running_target_m2_is_warning_not_blocker(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            running = target / "Mir200/M2Server.exe"
            with patch("xyequip.target.running_executable_paths", return_value=[running]):
                plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, self.compiled())
            self.assertEqual(plan.blockers, [])
            self.assertTrue(any("M2" in item and "运行" in item for item in plan.warnings))

    def test_script_property_builds_addbag_custom_display_block(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.legacy import xy_equip_maker as maker
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{
                    "名称": "入包显示刀", "部位": "武器",
                    "神力倍攻": "20", "固定切割": "500", "鞭尸": "5",
                }],
                Path("fixture.xlsx"),
            )
            previous_paths = maker._PATHS
            maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
            try:
                spec_file = Path(directory) / "入包显示刀.txt"
                spec_file.write_text(compiled.rows[0].equipment_text, encoding="utf-8")
                generated = maker.build_qfunction_text(
                    maker.parse_spec(spec_file), maker.load_script_props()
                )
            finally:
                maker.configure_paths(previous_paths)

            self.assertIn("[@AddBag]", generated)
            self.assertIn("; XY_EQUIP_MAKER_DISPLAY_ANCHOR", generated)
            self.assertIn("; XY-EQUIP-MAKER-DISPLAY 入包显示刀", generated)
            self.assertIn("LINKPICKUPITEM", generated)
            self.assertIn("SetCustomItemAbil -1 0 1 40", generated)
            self.assertIn("SetCustomItemAbil -1 1 1 43", generated)
            self.assertIn("SetCustomItemAbil -1 2 1 48", generated)
            self.assertIn("SetCustomItemValue -1 0 = 20", generated)
            self.assertIn("SetCustomItemValue -1 1 = 500", generated)
            self.assertIn("SetCustomItemValue -1 2 = 5", generated)
            self.assertIn("UpdateItem -1", generated)
            self.assertIn("ClearLinkItem", generated)

    def test_script_display_bind_types_do_not_overlap_effect_bind_types(self):
        from xyequip.legacy.xy_equip_maker import load_script_props

        effect_bind_types = {13, 14, 20, 21, 22, 24, 25, 27, 31}
        properties = load_script_props()["properties"]
        display_bind_types = {
            meta["display"]["bind_type"]
            for meta in properties.values()
            if "bind_type" in meta["display"]
        }

        self.assertEqual(display_bind_types, set(range(40, 56)) | {60})
        self.assertFalse(display_bind_types & effect_bind_types)
        self.assertEqual(properties["攻速突破"]["display"]["mode"], "textvar_value_ex")
        self.assertEqual(properties["攻速突破"]["display"]["textvar_line"], 40)
        self.assertEqual(properties["对怪伤害吸收"]["display"]["mode"], "item_desc_only")
        self.assertEqual(properties["伤害吸收上限"]["display"]["mode"], "item_desc_only")
        self.assertEqual(properties["回收增加"]["display"]["mode"], "item_desc_only")

    def test_recycle_bonus_requires_both_recycle_anchors_and_builds_both_routes(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.legacy import xy_equip_maker as maker
        from xyequip.paths import EquipmentPaths
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "回收测试戒", "部位": "戒指", "回收增加": "20"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qmanage = target / "Mir200/Envir/MapQuest_Def/QManage.txt"
            qfunction.write_text(
                qfunction.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR\n",
                encoding="gb18030",
            )
            qmanage.write_text(
                qmanage.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_RECYCLE_BONUS_QMANAGE_ANCHOR\n",
                encoding="gb18030",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertEqual(plan.blockers, [])
            previous_paths = maker._PATHS
            maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
            try:
                spec_file = Path(directory) / "回收测试戒.txt"
                spec_file.write_text(compiled.rows[0].equipment_text, encoding="utf-8")
                generated = maker.build_script_texts(maker.parse_spec(spec_file), maker.load_script_props())
            finally:
                maker.configure_paths(previous_paths)
            self.assertIn("INC N$XY_RecycleEquipBonus 20", generated["qfunction"])
            self.assertIn("INC N$XY_RecycleEquipBonus 20", generated["qmanage"])
            self.assertNotIn("SetCustomItemAbil", generated["qfunction"])

    def test_sustain_properties_require_formal_resident_anchors(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "缺续航锚点刀", "部位": "武器", "吸血": "12", "每秒回血": "80"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EQUIP_MAKER_LIFESTEAL_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_text(
                qfunction.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR\n"
                + "; XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR\n",
                encoding="gb18030",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )

    def test_sustain_properties_generate_effect_and_display_blocks(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.legacy import xy_equip_maker as maker
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_text(
                qfunction.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR\n"
                + "; XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR\n",
                encoding="gb18030",
            )
            qmanage = target / "Mir200/Envir/MapQuest_Def/QManage.txt"
            qmanage.write_text(
                qmanage.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR\n",
                encoding="gb18030",
            )
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "续航测试刀", "部位": "武器", "吸血": "12", "每秒回血": "80"}],
                Path("fixture.xlsx"),
            )
            previous_paths = maker._PATHS
            maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
            try:
                spec_file = Path(directory) / "续航测试刀.txt"
                spec_file.write_text(compiled.rows[0].equipment_text, encoding="utf-8")
                generated_scripts = maker.build_script_texts(
                    maker.parse_spec(spec_file), maker.load_script_props()
                )
            finally:
                maker.configure_paths(previous_paths)
            generated = generated_scripts["qfunction"]
            generated_qmanage = generated_scripts["qmanage"]
            self.assertIn("INC N$XY_SUS_LifeSteal 12", generated)
            self.assertIn("MOV N$XY_SUS_HPActive 1", generated)
            self.assertIn("HumanHP + 80", generated_qmanage)
            self.assertNotIn("N$XY_SUS_HPPerSec", generated + generated_qmanage)
            self.assertIn("SetCustomItemAbil -1 0 1 54", generated)
            self.assertIn("SetCustomItemAbil -1 1 1 55", generated)
            self.assertIn("SetCustomItemAbil -1 0 3 1", generated)
            self.assertIn("SetCustomItemAbil -1 1 3 0", generated)
            self.assertIn("SetCustomItemValue -1 0 = 12", generated)
            self.assertIn("SetCustomItemValue -1 1 = 80", generated)

    def test_damage_coefficient_requires_formal_resident_anchor(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "缺伤害系数锚点刀", "部位": "武器", "伤害系数": "25"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )

    def test_monster_absorb_requires_both_formal_resident_anchors(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "缺怪伤吸收锚点甲", "部位": "衣服", "对怪伤害吸收": "30", "伤害吸收上限": "5"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_text(
                qfunction.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR\n",
                encoding="gb18030",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )
    def test_execution_equipment_properties_use_strict_lab_anchors(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.legacy import xy_equip_maker as maker
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_text(
                qfunction.read_text(encoding="gb18030")
                + "; XY_EXECUTION_LAB_CHANCE_ANCHOR\n"
                + "; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR\n"
                + "; XY_EXECUTION_LAB_PVE_BONUS_ANCHOR\n"
                + "; XY_EXECUTION_LAB_PVE_DURATION_ANCHOR\n",
                encoding="gb18030",
            )
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{
                    "名称": "处决四属性刀",
                    "部位": "武器",
                    "处决": "10",
                    "韧性": "10",
                    "处决倍率": "10",
                    "处决时间": "1",
                }],
                Path("fixture.xlsx"),
            )
            equipment_text = compiled.rows[0].equipment_text
            self.assertIn("处决概率=10", equipment_text)
            self.assertIn("韧性=10", equipment_text)
            self.assertIn("处决倍率=10", equipment_text)
            self.assertIn("处决时间=1", equipment_text)

            previous_paths = maker._PATHS
            maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
            try:
                spec_file = Path(directory) / "处决四属性刀.txt"
                spec_file.write_text(equipment_text, encoding="utf-8")
                generated = maker.build_qfunction_text(
                    maker.parse_spec(spec_file), maker.load_script_props()
                )
            finally:
                maker.configure_paths(previous_paths)

            self.assertIn("INC N$XY_EXEC_ChanceBP 1000", generated)
            self.assertIn("INC N$XY_EXEC_Toughness 10", generated)
            self.assertIn("INC N$XY_EXEC_PVEEquipBonusPercent 10", generated)
            self.assertIn("INC N$XY_EXEC_PVEEquipDurationMs 1000", generated)
            for bind_type in range(49, 53):
                self.assertIn(f" 1 {bind_type}", generated)

            from xyequip.planner import EquipmentPlanner
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertIn(
                "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt",
                {change.relative_path for change in plan.changes},
            )

    def test_existing_equipment_execution_update_still_requires_attribute_panel(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import _requires_attribute_panel

        compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
            [{"名称": "覆盖处决刀", "处决概率": "2", "处决倍率": "3", "处决时间": "1"}],
            Path("fixture.xlsx"),
        )

        self.assertTrue(_requires_attribute_panel(compiled))

    def test_execution_property_blocks_when_lab_anchor_is_absent(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "缺处决锚点刀", "部位": "武器", "处决概率": "10"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(
                any("XY_EXECUTION_LAB_CHANCE_ANCHOR" in item for item in plan.blockers),
                plan.blockers,
            )

    def test_missing_qfunction_anchor_is_reported_during_preflight(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            (target / "Mir200/Envir/Market_Def/QFunction-0.txt").write_bytes(b"")
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "缺锚点头盔", "部位": "头盔", "神力倍攻": "20"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(any("QFunction" in item and "锚点" in item for item in plan.blockers))

    def test_corpse_attribute_uses_standard_killmon_event_when_legacy_anchor_is_absent(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.legacy.xy_equip_maker import build_qfunction_text, load_script_props
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_text(
                "; XYDP-EVENT-STUB-BEGIN xy.combat.core KillMon\r\n"
                "[@KillMon]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
                "; XYDP-EVENT-STUB-END xy.combat.core KillMon\r\n",
                encoding="gb18030",
            )
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "鞭尸测试甲", "部位": "衣服", "鞭尸": "25"}],
                Path("fixture.xlsx"),
            )

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)

            self.assertEqual(plan.blockers, [])
            from xyequip.legacy import xy_equip_maker as maker
            from xyequip.paths import EquipmentPaths
            previous_paths = maker._PATHS
            maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
            try:
                spec_file = Path(directory) / "鞭尸测试甲.txt"
                spec_file.write_text(compiled.rows[0].equipment_text, encoding="utf-8")
                generated = build_qfunction_text(maker.parse_spec(spec_file), load_script_props())
            finally:
                maker.configure_paths(previous_paths)
            self.assertIn("; XY_EQUIP_MAKER_CORPSE_INIT", generated)
            self.assertIn("CHECKITEMW 鞭尸测试甲 1", generated)

    def test_missing_shared_equipment_lists_are_planned_as_safe_creates(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            for name in ("ItemDescList.txt", "ItemRuleList.txt", "GroupItemList.txt"):
                (target / "Mir200/Envir" / name).unlink()
            before = tree_hash(target)
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, self.compiled())
            self.assertEqual(tree_hash(target), before)
            self.assertEqual(plan.blockers, [])
            creates = {change.relative_path for change in plan.changes if change.kind == "create"}
            self.assertEqual(
                creates,
                {
                    "Mir200/Envir/ItemDescList.txt",
                    "Mir200/Envir/ItemRuleList.txt",
                    "Mir200/Envir/GroupItemList.txt",
                },
            )
            self.assertTrue(any("将安全创建" in warning for warning in plan.warnings))

    def test_update_allows_shared_columns_and_rejects_raw_database_columns(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (2, '覆盖测试刀', 5, 7, 9, 0, 0)")
            connection.commit()
            connection.close()
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)

            partial = service.compile_update_rows([{"名称": "青铜头盔", "防御": "0-9"}], Path("update.xlsx"))
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, partial, mode="update")
            self.assertEqual(plan.blockers, [])

            shared = service.compile_update_rows(
                [{"名称": "青铜头盔", "部位": "头盔", "来源编号": "", "持久": "1234"}],
                Path("shared-update.xlsx"),
            )
            shared_plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, shared, mode="update")
            self.assertEqual(shared_plan.blockers, [])

            with self.assertRaisesRegex(Exception, "不允许包含"):
                service.compile_update_rows([{"名称": "青铜头盔", "Looks": "9"}], Path("bad-update.xlsx"))

    def test_create_and_update_preflight_block_illegal_slot_attributes(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)

            created = service.compile_rows(
                [{"名称": "错误幸运头盔", "部位": "头盔", "幸运": "3"}],
                Path("create.xlsx"),
            )
            create_plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, created)
            self.assertTrue(any("幸运只允许武器、项链" in item for item in create_plan.blockers))

            updated = service.compile_update_rows(
                [{"名称": "青铜头盔", "幸运": "3"}], Path("update.xlsx")
            )
            update_plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, updated, mode="update")
            self.assertTrue(any("幸运只允许武器、项链" in item for item in update_plan.blockers))

    def test_export_update_workbook_lists_all_names_without_protected_columns(self):
        from xyequip.batch import BatchEquipmentService

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (2, '导出测试刀', 5, 0, 2, 0, 0)")
            connection.commit()
            connection.close()
            output = Path(directory) / "XuanYuanItems_Update.xlsx"
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            service.export_update_workbook(target, output)
            inspection = service.inspect(output)
            rows = __import__("xyequip.source", fromlist=["read_equipment_rows"]).read_equipment_rows(output)
            self.assertEqual(inspection.row_count, 2)
            self.assertIn("名称", inspection.headers)
            self.assertIn("部位", inspection.headers)
            self.assertIn("来源编号", inspection.headers)
            self.assertNotIn("持久", inspection.headers)
            self.assertEqual({row["名称"] for row in rows}, {"青铜头盔", "导出测试刀"})

    def test_search_equipment_finds_partial_and_exact_name_without_writing_target(self):
        from xyequip.batch import BatchEquipmentService

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (2, '暴击戒指', 22, 0, 8, 0, 0)")
            connection.commit()
            connection.close()
            before = tree_hash(target)
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            partial = service.search_equipment(target, "暴击")
            exact = service.search_equipment(target, "暴击戒指")
            self.assertEqual([item["name"] for item in partial], ["暴击戒指"])
            self.assertEqual([item["name"] for item in exact], ["暴击戒指"])
            self.assertEqual(partial[0]["stdmode"], 22)
            self.assertEqual(tree_hash(target), before)


if __name__ == "__main__":
    unittest.main()
