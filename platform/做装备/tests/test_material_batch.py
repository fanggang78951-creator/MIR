from __future__ import annotations

import hashlib
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EQUIPMENT_ROOT / "src"))

from test_equipment_preflight import make_target, tree_hash


def make_client_data(root: Path, count: int = 1) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for library in ("Items", "StateItem", "DnItems"):
        wzl = bytearray(64)
        struct.pack_into("<I", wzl, 44, count)
        wzx = bytearray(48 + count * 4)
        struct.pack_into("<I", wzx, 44, count)
        for index in range(count):
            struct.pack_into("<I", wzx, 48 + index * 4, 48)
        (root / f"{library}.wzl").write_bytes(bytes(wzl))
        (root / f"{library}.wzx").write_bytes(bytes(wzx))


def make_cloneable_client_data(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for library in ("Items", "StateItem", "DnItems"):
        payload = bytes((1, len(library)))
        frame = struct.pack("<HHHHhhhh", 6, 0, 1, 1, 0, 0, len(payload), 0) + payload
        wzl = bytearray(48)
        struct.pack_into("<I", wzl, 44, 1)
        wzl.extend(frame)
        wzx = bytearray(52)
        struct.pack_into("<I", wzx, 44, 1)
        struct.pack_into("<I", wzx, 48, 48)
        (root / f"{library}.wzl").write_bytes(wzl)
        (root / f"{library}.wzx").write_bytes(wzx)


class MaterialBatchTests(unittest.TestCase):
    def compile(self, rows: list[dict[str, str]]):
        from xyequip.materials import compile_material_rows

        return compile_material_rows(rows, Path("materials.xlsx"), "material-hash")

    def test_material_source_compiles_fixed_stack_contract(self):
        result = self.compile([
            {"名称": "玄渊晶石", "来源编号": "0", "重量": "2", "价格": "88", "颜色": "250"}
        ])

        text = result.rows[0].equipment_text
        self.assertEqual(result.operation, "material_create")
        self.assertIn("部位=材料", text)
        self.assertIn("StdMode=46", text)
        self.assertIn("DuraMax=99999", text)
        self.assertIn("OverLap=2", text)
        self.assertIn("来源编号=0", text)
        self.assertNotIn("[特殊属性]", text)

    def test_material_source_requires_name_source_and_unique_names(self):
        from xyequip.batch import BatchSourceError

        with self.assertRaisesRegex(BatchSourceError, "来源编号"):
            self.compile([{"名称": "无图材料"}])
        with self.assertRaisesRegex(BatchSourceError, "重复"):
            self.compile([
                {"名称": "重复材料", "来源编号": "0"},
                {"名称": "重复材料", "来源编号": "0"},
            ])

    def test_material_preflight_skips_existing_material_and_keeps_only_missing_rows(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute(
                "INSERT INTO StdItems VALUES (2, '已有材料', 46, 1, 77, 0, 0)"
            )
            connection.commit()
            connection.close()
            before_target = tree_hash(target)
            before_client = tree_hash(client)

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([
                    {"名称": "已有材料", "来源编号": "0"},
                    {"名称": "新增材料", "来源编号": "0"},
                ]),
                client,
                mode="material_create",
            )

            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.equipment_names, ["新增材料"])
            self.assertEqual(plan.skipped_existing, ("已有材料",))
            self.assertEqual([row.name for row in plan.compiled.rows], ["新增材料"])
            self.assertTrue(any("不覆盖、不重复添加" in item for item in plan.warnings))
            self.assertEqual(tree_hash(target), before_target)
            self.assertEqual(tree_hash(client), before_client)

    def test_material_preflight_all_existing_is_successful_zero_change_plan(self):
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute(
                "INSERT INTO StdItems VALUES (2, '已有材料', 46, 1, 77, 0, 0)"
            )
            connection.commit()
            connection.close()
            before_target = tree_hash(target)
            before_client = tree_hash(client)

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "已有材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.equipment_names, [])
            self.assertEqual(plan.changes, [])
            self.assertEqual(plan.skipped_existing, ("已有材料",))

            receipt = EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)
            receipt_data = __import__("json").loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(receipt_data["status"], "no_changes")
            self.assertEqual(receipt_data["skipped_existing"], ["已有材料"])
            self.assertEqual(tree_hash(target), before_target)
            self.assertEqual(tree_hash(client), before_client)

    def test_material_preflight_blocks_same_name_non_material_item(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "青铜头盔", "来源编号": "0"}]),
                client,
                mode="material_create",
            )
            self.assertTrue(any("同名物品已存在但不是材料" in item for item in plan.blockers))

    def test_material_install_writes_only_missing_rows_and_preserves_existing_definition(self):
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_cloneable_client_data(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            for column in ("Weight", "Anicount", "Source", "Reserved", "DuraMax", "Need", "NeedLevel", "Price", "Stock", "Color", "OverLap"):
                connection.execute(f"ALTER TABLE StdItems ADD COLUMN {column} INTEGER DEFAULT 0")
            connection.execute(
                "INSERT INTO StdItems (Idx, Name, StdMode, Shape, Looks, Ac, Ac2, Weight, DuraMax, OverLap) "
                "VALUES (2, '已有材料', 46, 1, 88, 7, 9, 3, 12345, 2)"
            )
            connection.commit()
            existing_before = connection.execute(
                "SELECT * FROM StdItems WHERE Name='已有材料'"
            ).fetchone()
            connection.close()
            before_target = tree_hash(target)
            before_client = tree_hash(client)

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([
                    {"名称": "已有材料", "来源编号": "0", "重量": "99"},
                    {"名称": "新增材料", "来源编号": "0", "重量": "2"},
                ]),
                client,
                mode="material_create",
            )
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.equipment_names, ["新增材料"])
            receipt = EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            existing_after = connection.execute(
                "SELECT * FROM StdItems WHERE Name='已有材料'"
            ).fetchone()
            created = connection.execute(
                "SELECT StdMode, DuraMax, OverLap, Weight FROM StdItems WHERE Name='新增材料'"
            ).fetchone()
            connection.close()
            self.assertEqual(existing_after, existing_before)
            self.assertEqual(created, (46, 99999, 2, 2))

            EquipmentInstaller(EQUIPMENT_ROOT.parent).rollback(target, receipt.transaction_id)
            restored_target = tree_hash(target)
            restored_target.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_target, before_target)
            self.assertEqual(tree_hash(client), before_client)

    def test_material_preflight_is_read_only_and_covers_db_and_items_library_only(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            before_target = tree_hash(target)
            before_client = tree_hash(client)
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "只读材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )

            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.operation, "material_create")
            self.assertEqual(tree_hash(target), before_target)
            self.assertEqual(tree_hash(client), before_client)
            self.assertEqual(len(plan.changes), 3)
            self.assertEqual(sum(change.scope == "client" for change in plan.changes), 2)
            self.assertFalse(any("StateItem" in change.relative_path for change in plan.changes))
            self.assertFalse(any("DnItems" in change.relative_path for change in plan.changes))
            self.assertEqual(plan.base_templates, {"只读材料": "平台基础母版（材料，StdMode=46）"})

    def test_material_preflight_does_not_require_dnitems_or_stateitem_libraries(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            (client / "StateItem.wzl").unlink()
            (client / "StateItem.wzx").unlink()
            (client / "DnItems.wzl").unlink()
            (client / "DnItems.wzx").unlink()
            before_client = tree_hash(client)

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "无穿戴图材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )

            self.assertEqual(plan.blockers, [])
            self.assertEqual(tree_hash(client), before_client)
            self.assertTrue(any("不修改 DnItems 或 StateItem" in warning for warning in plan.warnings))

    def test_material_preflight_requires_complete_client_libraries(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            (client / "Items.wzx").unlink()
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "缺图库材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )
            self.assertTrue(any("Items.wzx" in item for item in plan.blockers))

    def test_material_source_error_reports_selected_client_path_not_sandbox(self):
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "selected-data"
            make_target(target)
            make_client_data(client)
            wzx = bytearray((client / "Items.wzx").read_bytes())
            struct.pack_into("<I", wzx, 48, 0)
            (client / "Items.wzx").write_bytes(wzx)

            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "缺地面图材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )

            self.assertTrue(any(str(client.resolve() / "Items.wzx") in item for item in plan.blockers))
            self.assertFalse(any("\\client\\Items.wzx" in item for item in plan.blockers))

    def test_material_install_and_rollback_preserve_non_material_files(self):
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            for column in ("Weight", "Anicount", "Source", "Reserved", "DuraMax", "Need", "NeedLevel", "Price", "Stock", "Color", "OverLap"):
                connection.execute(f"ALTER TABLE StdItems ADD COLUMN {column} INTEGER DEFAULT 0")
            connection.commit()
            connection.close()
            before_target = tree_hash(target)
            before_client = tree_hash(client)
            desc_before = (target / "Mir200/Envir/ItemDescList.txt").read_bytes()
            qfunction_before = (target / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes()
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "事务材料", "来源编号": "0", "重量": "2"}]),
                client,
                mode="material_create",
            )
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)

            def fake_icon(spec, register_resource=True, libraries=()):
                self.assertFalse(register_resource)
                self.assertEqual(libraries, ("Items",))
                spec.fields["Looks"] = int(spec.icon_source["source_id"])
                return "测试图标"

            with patch("xyequip.legacy.xy_equip_maker.apply_static_icon_source", side_effect=fake_icon):
                receipt = installer.install(plan)

            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            row = connection.execute(
                "SELECT StdMode, Shape, Looks, DuraMax, OverLap, Weight FROM StdItems WHERE Name='事务材料'"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (46, 1, 0, 99999, 2, 2))
            self.assertEqual((target / "Mir200/Envir/ItemDescList.txt").read_bytes(), desc_before)
            self.assertEqual((target / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes(), qfunction_before)
            installer.rollback(target, receipt.transaction_id)
            restored_target = tree_hash(target)
            restored_target.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_target, before_target)
            self.assertEqual(tree_hash(client), before_client)

    def test_real_material_install_and_rollback_only_touches_items(self):
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_cloneable_client_data(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            for column in ("Weight", "Anicount", "Source", "Reserved", "DuraMax", "Need", "NeedLevel", "Price", "Stock", "Color", "OverLap"):
                connection.execute(f"ALTER TABLE StdItems ADD COLUMN {column} INTEGER DEFAULT 0")
            connection.commit()
            connection.close()
            before_target = tree_hash(target)
            before_client = tree_hash(client)
            unused_before = {
                f"{lib}.{ext}": (client / f"{lib}.{ext}").read_bytes()
                for lib in ("StateItem", "DnItems")
                for ext in ("wzl", "wzx")
            }
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "真实事务材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )

            self.assertEqual(plan.blockers, [])
            receipt = EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            row = connection.execute(
                "SELECT StdMode, Shape, Looks, DuraMax, OverLap FROM StdItems WHERE Name='真实事务材料'"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (46, 1, 1, 99999, 2))
            wzx = (client / "Items.wzx").read_bytes()
            self.assertEqual(struct.unpack_from("<I", wzx, 44)[0], 2)
            self.assertGreater(struct.unpack_from("<I", wzx, 52)[0], 0)
            for name, data in unused_before.items():
                self.assertEqual((client / name).read_bytes(), data)

            EquipmentInstaller(EQUIPMENT_ROOT.parent).rollback(target, receipt.transaction_id)
            restored_target = tree_hash(target)
            restored_target.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_target, before_target)
            self.assertEqual(tree_hash(client), before_client)

    def test_material_commit_lock_restores_server_and_client_byte_exactly(self):
        from xyequip.installer import EquipmentInstallError, EquipmentInstaller
        from xyequip.planner import EquipmentPlanner
        from xyequip.transaction import atomic_write_bytes as real_atomic_write_bytes

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            client = Path(directory) / "data"
            make_target(target)
            make_client_data(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            for column in ("Weight", "Anicount", "Source", "Reserved", "DuraMax", "Need", "NeedLevel", "Price", "Stock", "Color", "OverLap"):
                connection.execute(f"ALTER TABLE StdItems ADD COLUMN {column} INTEGER DEFAULT 0")
            connection.commit()
            connection.close()
            before_target = tree_hash(target)
            before_client = tree_hash(client)
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(
                target,
                self.compile([{"名称": "锁定材料", "来源编号": "0"}]),
                client,
                mode="material_create",
            )

            def fake_icon(spec, register_resource=True, libraries=()):
                self.assertEqual(libraries, ("Items",))
                spec.fields["Looks"] = 0
                return "测试图标"

            def fail_on_first_client_file(path, data):
                if Path(path).resolve() == (client / "Items.wzl").resolve():
                    raise PermissionError("模拟客户端图库锁定")
                return real_atomic_write_bytes(path, data)

            with patch("xyequip.legacy.xy_equip_maker.apply_static_icon_source", side_effect=fake_icon), patch(
                "xyequip.installer.atomic_write_bytes", side_effect=fail_on_first_client_file
            ):
                with self.assertRaisesRegex(EquipmentInstallError, "已恢复安装前文件"):
                    EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)

            self.assertEqual(tree_hash(target), before_target)
            self.assertEqual(tree_hash(client), before_client)


if __name__ == "__main__":
    unittest.main()
