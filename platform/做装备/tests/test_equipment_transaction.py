from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EQUIPMENT_ROOT / "src"))

from test_equipment_preflight import make_target, tree_hash


class EquipmentTransactionTests(unittest.TestCase):
    def make_plan(self, target: Path, name: str = "事务头盔"):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
            [{"名称": name, "部位": "头盔", "防御": "0-1"}],
            Path("fixture.xlsx"),
            "fixture-hash",
        )
        return EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)

    def test_install_then_rollback_restores_target_byte_exactly(self):
        from xyequip.installer import EquipmentInstaller

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            before = tree_hash(target)
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(self.make_plan(target))
            after = tree_hash(target)
            self.assertNotEqual(after, before)
            self.assertTrue((target / ".xydp/equipment-installed.json").exists())
            installer.rollback(target, receipt.transaction_id)
            restored = tree_hash(target)
            restored.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored, before)

    def test_execution_install_updates_panel_in_same_transaction_and_rolls_back(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_bytes((
                qfunction.read_bytes().decode("gb18030")
                + "; XY_EXECUTION_LAB_CHANCE_ANCHOR\r\n"
                + "; XY_EXECUTION_LAB_PVE_BONUS_ANCHOR\r\n"
                + "; XY_EXECUTION_LAB_PVE_DURATION_ANCHOR\r\n"
            ).encode("gb18030"))
            before = tree_hash(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{
                    "名称": "事务处决同步刀",
                    "部位": "武器",
                    "处决概率": "2",
                    "处决倍率": "3",
                    "处决时间": "1",
                }],
                Path("fixture.xlsx"),
                "fixture-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertEqual(plan.blockers, [])
            panel_relative = "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt"
            self.assertIn(panel_relative, {change.relative_path for change in plan.changes})

            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(plan)
            panel = (target / panel_relative).read_text(encoding="gb18030")
            self.assertIn("; XY-ATTR-PANEL 事务处决同步刀: 处决概率+2%", panel)
            self.assertIn("; XY-ATTR-PANEL 事务处决同步刀: PVE处决额外伤害+3%", panel)
            self.assertIn("; XY-ATTR-PANEL 事务处决同步刀: PVE处决持续时间+1秒", panel)

            installer.rollback(target, receipt.transaction_id)
            restored = tree_hash(target)
            restored.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored, before)

    def test_blocked_plan_never_changes_target(self):
        from xyequip.installer import EquipmentInstallError, EquipmentInstaller

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            plan = self.make_plan(target)
            plan.blockers.append("测试阻止项")
            before = tree_hash(target)
            with self.assertRaisesRegex(EquipmentInstallError, "测试阻止项"):
                EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)
            self.assertEqual(tree_hash(target), before)

    def test_manual_change_after_install_blocks_rollback(self):
        from xyequip.installer import EquipmentInstallError, EquipmentInstaller

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(self.make_plan(target))
            (target / "Mir200/Envir/ItemDescList.txt").write_bytes(b"manual")
            with self.assertRaisesRegex(EquipmentInstallError, "手工修改"):
                installer.rollback(target, receipt.transaction_id)

    def test_install_bootstraps_missing_shared_lists_and_rollback_removes_them(self):
        from xyequip.installer import EquipmentInstaller

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            shared = [target / "Mir200/Envir" / name for name in (
                "ItemDescList.txt", "ItemRuleList.txt", "GroupItemList.txt"
            )]
            for path in shared:
                path.unlink()
            before = tree_hash(target)
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(self.make_plan(target, "空白服头盔"))
            self.assertTrue(all(path.exists() for path in shared))
            installer.rollback(target, receipt.transaction_id)
            self.assertTrue(all(not path.exists() for path in shared))
            self.assertEqual(tree_hash(target), before)

    def test_auto_template_weapon_keeps_base_shape_and_script_tooltip(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (8, '基础动作武器', 5, 77, 8, 0, 0)")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{
                    "名称": "自动母版脚本刀", "部位": "武器", "攻击": "10-10",
                    "神力倍攻": "20", "打怪伤害": "30", "暴击伤害": "40", "固定切割": "500",
                }],
                Path("fixture.xlsx"),
                "fixture-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertEqual(plan.blockers, [])
            EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            shape = connection.execute("SELECT Shape FROM StdItems WHERE Name='自动母版脚本刀'").fetchone()[0]
            connection.close()
            item_desc = (target / "Mir200/Envir/ItemDescList.txt").read_bytes().decode("gb18030")
            self.assertEqual(shape, 77)
            self.assertIn("神力倍攻+20%", item_desc)
            self.assertIn("打怪伤害+30%", item_desc)
            self.assertIn("暴击伤害+40%", item_desc)
            self.assertIn("固定切割+500", item_desc)

    def test_install_writes_addbag_display_without_duplicate_effect_branch(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (8, '基础显示武器', 5, 1, 8, 0, 0)")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{
                    "名称": "自动显示武器", "部位": "武器",
                    "神力倍攻": "20", "打怪伤害": "30", "暴击伤害": "40",
                    "固定切割": "500", "爆率": "50", "最大爆率": "60",
                    "鞭尸": "9",
                }],
                Path("fixture.xlsx"),
                "fixture-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            qfunction = (target / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes().decode("gb18030")
            self.assertEqual(qfunction.count("CHECKITEMW 自动显示武器 1"), 12)
            self.assertIn("INC N$XY_RT_Power 20", qfunction)
            self.assertIn("INC N$XY_RT_Blast 40", qfunction)
            self.assertIn("INC N$XY_RT_Drop 50", qfunction)
            self.assertIn("INC N$XY_RT_DropMax 60", qfunction)
            self.assertEqual(qfunction.count("; XY-EQUIP-MAKER-DISPLAY 自动显示武器"), 1)
            self.assertIn("[@AddBag]", qfunction)
            self.assertIn("LINKPICKUPITEM", qfunction)
            self.assertIn("SetCustomItemAbil -1 0 1 40", qfunction)
            self.assertIn("SetCustomItemAbil -1 6 1 48", qfunction)
            self.assertNotIn("GetAllCustomItemValue 40", qfunction)

    def test_existing_effect_branch_can_be_upgraded_with_display_block(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.legacy import xy_equip_maker as maker
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_text(
                "[@PlayLogin]\r\n#IF\r\n#ACT\r\n"
                "; XY_EQUIP_MAKER_POWER_ANCHOR\r\n"
                "#IF\r\nCHECKITEMW 已有显示刀 1\r\n#ACT\r\nINC N$倍攻 20\r\n",
                encoding="gb18030",
            )
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (8, '已有显示刀', 5, 1, 8, 0, 0)")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "已有显示刀", "部位": "武器", "神力倍攻": "20"}],
                Path("fixture.xlsx"),
            )
            previous_paths = maker._PATHS
            maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
            try:
                spec_file = Path(directory) / "已有显示刀.txt"
                spec_file.write_text(compiled.rows[0].equipment_text, encoding="utf-8")
                generated = maker.build_qfunction_text(
                    maker.parse_spec(spec_file), maker.load_script_props(), allow_existing_effect_branch=True
                )
            finally:
                maker.configure_paths(previous_paths)

            self.assertEqual(generated.count("CHECKITEMW 已有显示刀 1"), 1)
            self.assertEqual(generated.count("; XY-EQUIP-MAKER-DISPLAY 已有显示刀"), 1)

    def test_display_repair_updates_only_qfunction_for_existing_equipment(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (8, '补写显示刀', 5, 1, 8, 0, 0)")
            connection.commit()
            connection.close()
            before_db = (target / "Mud2/DB/ApexM2.DB").read_bytes()
            before_desc = (target / "Mir200/Envir/ItemDescList.txt").read_bytes()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "补写显示刀", "部位": "武器", "神力倍攻": "20"}],
                Path("fixture.xlsx"),
                "fixture-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="repair_display")
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.operation, "repair_display")
            self.assertEqual([change.relative_path for change in plan.changes], ["Mir200/Envir/Market_Def/QFunction-0.txt"])
            EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            self.assertEqual((target / "Mud2/DB/ApexM2.DB").read_bytes(), before_db)
            self.assertEqual((target / "Mir200/Envir/ItemDescList.txt").read_bytes(), before_desc)
            qfunction = (target / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes().decode("gb18030")
            self.assertIn("; XY-EQUIP-MAKER-DISPLAY 补写显示刀", qfunction)

    def test_platform_base_profile_creates_missing_shoes_with_anicount(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            for column in ("Weight", "Anicount", "DuraMax", "Need", "NeedLevel", "Price", "Stock", "Color", "OverLap", "Light", "Horse", "Job", "CustomItem"):
                connection.execute(f"ALTER TABLE StdItems ADD COLUMN {column}")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "平台母版鞋", "部位": "鞋子"}],
                Path("fixture.xlsx"),
                "fixture-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.base_templates, {"平台母版鞋": "平台基础母版（鞋子，StdMode=62）"})
            EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            row = connection.execute(
                "SELECT StdMode, Shape, Weight, Anicount, DuraMax, NeedLevel FROM StdItems WHERE Name='平台母版鞋'"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (62, 0, 1, 0, 60000, 1))

    def test_update_changes_named_definition_preserves_appearance_and_rolls_back(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN DuraMax INTEGER DEFAULT 8000")
            connection.execute("UPDATE StdItems SET Looks=99, DuraMax=7777 WHERE Name='青铜头盔'")
            connection.commit()
            connection.close()
            before = tree_hash(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "防御": "3-8", "攻击加成": "12"}],
                Path("update.xlsx"),
                "update-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.operation, "update")
            receipt = EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            row = connection.execute("SELECT Ac, Ac2, Looks, DuraMax FROM StdItems WHERE Name='青铜头盔'").fetchone()
            connection.close()
            self.assertEqual(row, (3, 8, 99, 60000))
            self.assertIn("攻击加成+12%", (target / "Mir200/Envir/ItemDescList.txt").read_bytes().decode("gb18030"))
            EquipmentInstaller(EQUIPMENT_ROOT.parent).rollback(target, receipt.transaction_id)
            restored = tree_hash(target)
            restored.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored, before)

    def test_create_and_update_weapon_preserve_accuracy_and_attack_speed(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN Mac INTEGER DEFAULT 0")
            connection.execute("ALTER TABLE StdItems ADD COLUMN Mac2 INTEGER DEFAULT 0")
            connection.execute("ALTER TABLE StdItems ADD COLUMN Dc INTEGER DEFAULT 0")
            connection.execute("ALTER TABLE StdItems ADD COLUMN Dc2 INTEGER DEFAULT 0")
            connection.execute(
                "INSERT INTO StdItems "
                "(Idx, Name, StdMode, Shape, Looks, Ac, Ac2, Mac, Mac2, Dc, Dc2) "
                "VALUES (8, '基础动作武器', 5, 1, 8, 0, 0, 0, 0, 1, 1)"
            )
            connection.commit()
            connection.close()

            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            planner = EquipmentPlanner(EQUIPMENT_ROOT.parent)
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            created = service.compile_rows(
                [{
                    "名称": "准确攻速测试刀",
                    "部位": "武器",
                    "攻击": "10-20",
                    "防御": "",
                    "魔御": "",
                    "幸运": "",
                    "准确": "52",
                    "攻击速度": "2",
                }],
                Path("create.xlsx"),
                "create-accuracy-speed-hash",
            )
            create_plan = planner.preflight(target, created)
            self.assertEqual(create_plan.blockers, [])
            installer.install(create_plan)

            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            created_values = connection.execute(
                "SELECT Ac2, Mac2 FROM StdItems WHERE Name='准确攻速测试刀'"
            ).fetchone()
            connection.close()
            self.assertEqual(created_values, (52, 12))

            updated = service.compile_update_rows(
                [{
                    "名称": "准确攻速测试刀",
                    "防御": "",
                    "魔御": "",
                    "幸运": "",
                    "准确": "70",
                    "攻击速度": "6",
                }],
                Path("update.xlsx"),
                "update-accuracy-speed-hash",
            )
            update_plan = planner.preflight(target, updated, mode="update")
            self.assertEqual(update_plan.blockers, [])
            installer.install(update_plan)

            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            updated_values = connection.execute(
                "SELECT Ac, Ac2, Mac, Mac2 FROM StdItems WHERE Name='准确攻速测试刀'"
            ).fetchone()
            connection.close()
            self.assertEqual(updated_values, (0, 70, 0, 16))

    def test_update_native_crit_chance_writes_tooltip_description(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN Element INTEGER DEFAULT 0")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "暴击几率": "100"}],
                Path("native-update.xlsx"),
                "native-update-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertEqual(plan.blockers, [])
            EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            description = (target / "Mir200/Envir/ItemDescList.txt").read_bytes().decode("gb18030")
            self.assertIn("暴击几率+100%", description)

    def test_update_wraps_long_remark_and_preserves_managed_item_hint_suffix(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.item_hint import FINAL_SUFFIX
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            item_desc = target / "Mir200/Envir/ItemDescList.txt"
            item_desc.write_bytes(
                ("青铜头盔=\\242/　原说明" + FINAL_SUFFIX + "\r\n").encode("gb18030")
            )
            remark = (
                "沉船守财者专属。盔顶的金币不是装饰，而是守财者给自己留下的船资。"
                "他活着没舍得登船，死后却每天守在码头，等一艘永远不会靠岸的渡船。"
            )
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "攻击加成": "20", "备注": remark}],
                Path("wrapped-update.xlsx"),
                "wrapped-update-hash",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertEqual(plan.blockers, [])
            EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            lines = item_desc.read_bytes().decode("gb18030").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].count(FINAL_SUFFIX), 1)
            self.assertTrue(lines[0].endswith(FINAL_SUFFIX))
            self.assertGreaterEqual(lines[0].count("\\242/"), 4)

    def test_update_syncs_every_same_name_definition_from_a_partial_source_sheet(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = __import__("sqlite3").connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("INSERT INTO StdItems VALUES (2, '青铜头盔', 15, 0, 99, 1, 2)")
            connection.execute("INSERT INTO StdItems VALUES (3, '未修改的装备', 22, 0, 33, 7, 8)")
            connection.commit()
            connection.close()
            before = tree_hash(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "防御": "3-8"}], Path("update.xlsx"), "partial-update-hash"
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertTrue(any("定义不唯一" in item for item in plan.blockers))
            self.assertEqual(tree_hash(target), before)

    def test_update_blank_column_clears_platform_script_property(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            first = service.compile_update_rows([{"名称": "青铜头盔", "神力倍攻": "20"}], Path("update.xlsx"))
            installer.install(EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, first, mode="update"))
            cleared = service.compile_update_rows(
                [{"名称": "青铜头盔", "神力倍攻": ""}], Path("update.xlsx")
            )
            installer.install(EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, cleared, mode="update"))
            qfunction = (target / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes().decode("gb18030")
            self.assertNotIn("CHECKITEMW 青铜头盔 1", qfunction)
            self.assertNotIn("; XY-EQUIP-MAKER-DISPLAY 青铜头盔", qfunction)

    def test_update_workbook_applies_sustain_properties_and_rolls_back_byte_exactly(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction_path = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction_path.write_text(
                qfunction_path.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR\n"
                + "; XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR\n",
                encoding="gb18030",
            )
            qmanage_path = target / "Mir200/Envir/MapQuest_Def/QManage.txt"
            qmanage_path.write_text(
                qmanage_path.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR\n",
                encoding="gb18030",
            )
            before = tree_hash(target)
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            compiled = service.compile_update_rows(
                [{"名称": "青铜头盔", "吸血": "15", "每秒回血": "120"}],
                Path("XuanYuanItems_Update.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertEqual(plan.blockers, [])
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(plan)
            qfunction = qfunction_path.read_text(encoding="gb18030")
            qmanage = qmanage_path.read_text(encoding="gb18030")
            self.assertIn("INC N$XY_SUS_LifeSteal 15", qfunction)
            self.assertIn("MOV N$XY_SUS_HPActive 1", qfunction)
            self.assertIn("HumanHP + 120", qmanage)
            self.assertNotIn("N$XY_SUS_HPPerSec", qfunction + qmanage)
            self.assertIn("SetCustomItemAbil -1 0 1 54", qfunction)
            self.assertIn("SetCustomItemAbil -1 1 1 55", qfunction)
            desc = (target / "Mir200/Envir/ItemDescList.txt").read_text(encoding="gb18030")
            self.assertIn("吸血+15%", desc)
            self.assertIn("每秒回血+120", desc)

            installer.rollback(target, receipt.transaction_id)
            restored = tree_hash(target)
            restored.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored, before)

    def test_update_workbook_applies_recycle_bonus_to_manual_and_auto_routes(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            qfunction_path = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qmanage_path = target / "Mir200/Envir/MapQuest_Def/QManage.txt"
            qfunction_path.write_text(
                qfunction_path.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR\n",
                encoding="gb18030",
            )
            qmanage_path.write_text(
                qmanage_path.read_text(encoding="gb18030")
                + "; XY_EQUIP_MAKER_RECYCLE_BONUS_QMANAGE_ANCHOR\n",
                encoding="gb18030",
            )
            before = tree_hash(target)
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            compiled = service.compile_update_rows(
                [{"名称": "青铜头盔", "回收增加": "20"}],
                Path("09_装备批量生成.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertEqual(plan.blockers, [])
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(plan)
            qfunction = qfunction_path.read_text(encoding="gb18030")
            qmanage = qmanage_path.read_text(encoding="gb18030")
            for script in (qfunction, qmanage):
                self.assertIn("CHECKITEMW 青铜头盔 1", script)
                self.assertIn("INC N$XY_RecycleEquipBonus 20", script)
            desc = (target / "Mir200/Envir/ItemDescList.txt").read_text(encoding="gb18030")
            self.assertIn("回收增加+20%", desc)
            self.assertNotIn("XY-EQUIP-MAKER-DISPLAY 青铜头盔", qfunction)

            installer.rollback(target, receipt.transaction_id)
            restored = tree_hash(target)
            restored.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored, before)


if __name__ == "__main__":
    unittest.main()
