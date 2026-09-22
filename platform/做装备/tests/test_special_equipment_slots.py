from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EQUIPMENT_ROOT / "src"))

from test_equipment_preflight import make_target


def tree_hash(root: Path) -> dict[str, str]:
    import hashlib
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def prepare_special_target(root: Path) -> Path:
    make_target(root)
    connection = sqlite3.connect(root / "Mud2/DB/ApexM2.DB")
    for column in (
        "Weight", "Anicount", "Source", "Reserved", "DuraMax", "Mac", "Mac2",
        "Dc", "Dc2", "Mc", "Mc2", "Sc", "Sc2", "Need", "NeedLevel", "Price",
        "Stock", "Color", "OverLap", "HP", "MP", "Element", "Light", "Horse",
        "Job", "CustomItem",
    ):
        connection.execute(f"ALTER TABLE StdItems ADD COLUMN {column} INTEGER DEFAULT 0")
    connection.execute(
        "INSERT INTO StdItems (Idx,Name,StdMode,Shape,Looks,Anicount) VALUES (20,'背包神器母版',41,0,20,0)"
    )
    connection.execute(
        "INSERT INTO StdItems (Idx,Name,StdMode,Shape,Looks,Anicount) VALUES (21,'称号卷母版',31,0,21,79)"
    )
    connection.execute(
        "INSERT INTO StdItems (Idx,Name,StdMode,Shape,Looks,Anicount) VALUES (22,'旧称号',70,0,0,1)"
    )
    connection.commit()
    connection.close()
    qfunction = root / "Mir200/Envir/Market_Def/QFunction-0.txt"
    text = qfunction.read_text(encoding="gb18030").replace("\r\n", "\n").replace("\n", "\r\n")
    text += "[@AddBag]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    qfunction.write_bytes(text.encode("gb18030"))
    return root


class SpecialEquipmentSlotTests(unittest.TestCase):
    def test_batch_exposes_special_slots_without_fake_equipment_durability(self):
        from xyequip.legacy.xy_batch_equip_maker import row_to_equipment_txt

        bag = row_to_equipment_txt({"名称": "背包神物", "部位": "背包神器", "神力倍攻": "20"})
        title = row_to_equipment_txt({"名称": "[称号]试炼者", "部位": "称号卷", "攻击": "9-9"})
        self.assertIn("部位=背包神器", bag)
        self.assertNotIn("DuraMax=60000", bag)
        self.assertIn("部位=称号卷", title)
        self.assertIn("DuraMax=1", title)

    def test_backpack_artifact_uses_checkitem_not_checkitemw(self):
        from xyequip.paths import EquipmentPaths
        from xyequip.legacy import xy_equip_maker as maker

        with tempfile.TemporaryDirectory() as directory:
            target = prepare_special_target(Path(directory) / "Server")
            spec_path = Path(directory) / "bag.txt"
            spec_path.write_text(
                "[装备]\n名称=背包神物\n部位=背包神器\n[特殊属性]\n神力倍攻=20\n",
                encoding="utf-8",
            )
            old_paths = maker._PATHS
            try:
                maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target))
                maker.make_equipment(spec_path)
                qfunction = maker.read_text_auto(maker.QFUNCTION)
                self.assertIn("CHECKITEM 背包神物 1", qfunction)
                self.assertNotIn("CHECKITEMW 背包神物 1", qfunction)
                connection = sqlite3.connect(maker.DB_PATH)
                row = connection.execute(
                    "SELECT StdMode,Shape,DuraMax FROM StdItems WHERE Name='背包神物'"
                ).fetchone()
                connection.close()
                self.assertEqual(row, (41, 0, 0))
            finally:
                maker.configure_paths(old_paths)

    def test_backpack_artifact_blocks_silent_native_stats(self):
        from xyequip.legacy.xy_batch_equip_maker import row_to_equipment_txt
        from xyequip.legacy import xy_equip_maker as maker

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.txt"
            path.write_text(
                row_to_equipment_txt({"名称": "错误背包神物", "部位": "背包神器", "攻击": "10-10"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "背包神器.*不会由引擎自动生效"):
                maker.parse_spec(path)

    def test_title_scroll_creates_scroll_title_trigger_and_client_description(self):
        from xyequip.paths import EquipmentPaths
        from xyequip.legacy import xy_equip_maker as maker

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = prepare_special_target(root / "Server")
            client = root / "Client" / "data"
            client.mkdir(parents=True)
            (client / "fenghao.dat").write_text("旧称号=旧属性\r\n", encoding="gb18030", newline="")
            spec_path = root / "title.txt"
            spec_path.write_text(
                "[装备]\n名称=[称号]试炼者\n部位=称号卷\n攻击=99-99\n"
                "[特殊属性]\n神力倍攻=20\n",
                encoding="utf-8",
            )
            old_paths = maker._PATHS
            try:
                maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target, client))
                result = maker.make_equipment(spec_path)
                connection = sqlite3.connect(maker.DB_PATH)
                rows = connection.execute(
                    "SELECT Name,StdMode,Shape,Looks,Anicount,Dc,Dc2 FROM StdItems "
                    "WHERE Name IN ('[称号]试炼者','试炼者') ORDER BY Idx"
                ).fetchall()
                connection.close()
                self.assertEqual(rows[0][0:2], ("[称号]试炼者", 31))
                self.assertEqual(rows[1][0:2], ("试炼者", 70))
                self.assertEqual(rows[1][5:7], (99, 99))
                self.assertEqual(rows[1][3], rows[1][2] * 5)
                qfunction = maker.read_text_auto(maker.QFUNCTION)
                self.assertIn(f"[@StdModeFunc{rows[0][4]}]", qfunction)
                self.assertIn("CHECKFENGHAO 试炼者", qfunction)
                self.assertNotIn("CHECKITEMW [称号]试炼者 1", qfunction)
                self.assertIn("试炼者=攻击+99-99；神力倍攻+20%", maker.read_text_auto(client / "fenghao.dat"))
                self.assertIn("称号本体=试炼者", result)
            finally:
                maker.configure_paths(old_paths)

    def test_title_scroll_requires_explicit_scroll_name(self):
        from xyequip.legacy.xy_batch_equip_maker import row_to_equipment_txt
        from xyequip.legacy import xy_equip_maker as maker

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-title.txt"
            path.write_text(
                row_to_equipment_txt({"名称": "试炼者", "部位": "称号卷"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, r"\[称号\]"):
                maker.parse_spec(path)

    def test_title_scroll_transaction_includes_fenghao_and_rolls_back(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = prepare_special_target(root / "Server")
            client = root / "Client" / "data"
            client.mkdir(parents=True)
            (client / "fenghao.dat").write_text("旧称号=旧属性\r\n", encoding="gb18030", newline="")
            before_server = tree_hash(target)
            before_client = tree_hash(client)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "[称号]事务试炼者", "部位": "称号卷", "攻击": "9-9"}],
                Path("fixture.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, client)
            self.assertEqual(plan.blockers, [])
            self.assertIn(
                ("client", "fenghao.dat"),
                {(change.scope, change.relative_path) for change in plan.changes},
            )
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(plan)
            self.assertIn("事务试炼者=攻击+9-9", (client / "fenghao.dat").read_text(encoding="gb18030"))
            installer.rollback(target, receipt.transaction_id)
            restored_server = tree_hash(target)
            restored_server.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_server, before_server)
            self.assertEqual(tree_hash(client), before_client)


if __name__ == "__main__":
    unittest.main()
