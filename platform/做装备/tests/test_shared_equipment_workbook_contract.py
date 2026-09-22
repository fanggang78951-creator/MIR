from __future__ import annotations

import hashlib
import json
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


def write_library(client_data: Path, lib: str, count: int = 3) -> None:
    wzl = bytearray(64)
    offsets: list[int] = []
    for index in range(count):
        offsets.append(len(wzl))
        payload = bytes((index + 11, len(lib), index + 31))
        wzl.extend(struct.pack("<HHHHhhhh", 6, 0, 1, 1, index, -index, len(payload), 0) + payload)
    struct.pack_into("<I", wzl, 44, count)
    wzx = bytearray(48)
    struct.pack_into("<I", wzx, 44, count)
    for offset in offsets:
        wzx.extend(struct.pack("<I", offset))
    (client_data / f"{lib}.wzl").write_bytes(wzl)
    (client_data / f"{lib}.wzx").write_bytes(wzx)


def make_client(client_data: Path) -> None:
    client_data.mkdir(parents=True)
    for library in ("Items", "StateItem", "DnItems"):
        write_library(client_data, library)


def library_counts(client_data: Path) -> dict[str, int]:
    return {
        library: (len((client_data / f"{library}.wzx").read_bytes()) - 48) // 4
        for library in ("Items", "StateItem", "DnItems")
    }


class SharedEquipmentWorkbookContractTests(unittest.TestCase):
    def test_equipment_durability_is_fixed_and_old_column_is_ignored(self):
        from xyequip.legacy.xy_batch_equip_maker import row_to_equipment_txt

        text = row_to_equipment_txt({
            "名称": "固定持久头盔",
            "部位": "头盔",
            "来源编号": "1",
            "持久": "1234",
            "DuraMax": "5678",
        })
        self.assertIn("DuraMax=60000", text)
        self.assertNotIn("1234", text)
        self.assertNotIn("5678", text)

    def test_create_requires_source_id(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "遗漏来源头盔", "部位": "头盔"}],
                Path("09_装备批量生成.xlsx"),
                enforce_create_source=True,
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled)
            self.assertTrue(any("必须填写来源编号" in item for item in plan.blockers))

    def test_create_with_source_reuses_looks_without_client_write_and_rolls_back(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Server"
            client = root / "Client" / "data"
            make_target(target)
            make_client(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN DuraMax INTEGER DEFAULT 8000")
            connection.commit()
            connection.close()
            before_server = tree_hash(target)
            before_client = tree_hash(client)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_rows(
                [{"名称": "合法来源头盔", "部位": "头盔", "来源编号": "1", "持久": "1234"}],
                Path("09_装备批量生成.xlsx"),
                "shared-create",
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, client)
            self.assertEqual(plan.blockers, [])
            self.assertEqual(len([change for change in plan.changes if change.scope == "client"]), 0)
            self.assertTrue(any("直接复用来源编号" in warning for warning in plan.warnings))
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(plan)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            row = connection.execute(
                "SELECT StdMode,Shape,Looks,DuraMax FROM StdItems WHERE Name='合法来源头盔'"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (15, 0, 1, 60000))
            self.assertEqual(library_counts(client), {"Items": 3, "StateItem": 3, "DnItems": 3})
            self.assertEqual(tree_hash(client), before_client)
            receipt_data = json.loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(receipt_data["source_icon_results"], [{
                "name": "合法来源头盔",
                "source_id": 1,
                "old_looks": None,
                "new_looks": 1,
                "action": "reuse_source_id",
                "client_files_changed": False,
            }])
            installer.rollback(target, receipt.transaction_id)
            restored_server = tree_hash(target)
            restored_server.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_server, before_server)
            self.assertEqual(tree_hash(client), before_client)

    def test_update_blank_source_preserves_appearance_and_sets_fixed_durability(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN DuraMax INTEGER DEFAULT 7777")
            connection.execute("UPDATE StdItems SET Shape=9, Looks=2, DuraMax=7777 WHERE Name='青铜头盔'")
            connection.commit()
            connection.close()
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "部位": "", "来源编号": "", "防御": "3-8"}],
                Path("09_装备批量生成.xlsx"),
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertEqual(plan.blockers, [])
            self.assertFalse(any(change.scope == "client" for change in plan.changes))
            receipt = EquipmentInstaller(EQUIPMENT_ROOT.parent).install(plan)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            row = connection.execute(
                "SELECT Ac, Ac2, Shape, Looks, DuraMax FROM StdItems WHERE Name='青铜头盔'"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (3, 8, 9, 2, 60000))
            receipt_data = json.loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(receipt_data["fixed_durability"], 60000)
            self.assertEqual(receipt_data["source_icon_results"][0]["action"], "preserve_old_looks")

    def test_update_reuses_existing_source_id_without_expanding_client_libraries(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Server"
            client = root / "Client" / "data"
            make_target(target)
            make_client(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN DuraMax INTEGER DEFAULT 8000")
            connection.execute("UPDATE StdItems SET Shape=7, Looks=0 WHERE Name='青铜头盔'")
            connection.execute(
                "INSERT INTO StdItems (Idx,Name,StdMode,Shape,Looks,Ac,Ac2,DuraMax) "
                "VALUES (2,'第二头盔',15,8,2,0,0,9000)"
            )
            connection.commit()
            connection.close()
            before_server = tree_hash(target)
            before_client = tree_hash(client)
            rows = [
                {"名称": "青铜头盔", "来源编号": "1"},
                {"名称": "第二头盔", "来源编号": "1"},
            ]
            service = BatchEquipmentService(EQUIPMENT_ROOT.parent)
            compiled = service.compile_update_rows(rows, Path("09_装备批量生成.xlsx"), "shared-update")
            planner = EquipmentPlanner(EQUIPMENT_ROOT.parent)
            plan = planner.preflight(target, compiled, client, mode="update")
            self.assertEqual(plan.blockers, [])
            self.assertEqual(len([change for change in plan.changes if change.scope == "client"]), 0)
            self.assertEqual(library_counts(client), {"Items": 3, "StateItem": 3, "DnItems": 3})
            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            receipt = installer.install(plan)
            self.assertEqual(library_counts(client), {"Items": 3, "StateItem": 3, "DnItems": 3})
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            changed = connection.execute(
                "SELECT Name,Shape,Looks,DuraMax FROM StdItems WHERE Name IN ('青铜头盔','第二头盔') ORDER BY Idx"
            ).fetchall()
            connection.close()
            self.assertEqual(changed, [("青铜头盔", 7, 1, 60000), ("第二头盔", 8, 1, 60000)])
            first_receipt = json.loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["action"] for item in first_receipt["source_icon_results"]],
                ["reuse_source_id", "reuse_batch_source_id"],
            )

            second_plan = planner.preflight(target, compiled, client, mode="update")
            self.assertEqual(second_plan.blockers, [])
            second_receipt = installer.install(second_plan)
            self.assertEqual(library_counts(client), {"Items": 3, "StateItem": 3, "DnItems": 3})
            second_data = json.loads(Path(second_receipt.receipt_path).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["action"] for item in second_data["source_icon_results"]],
                ["reuse_source_id", "reuse_batch_source_id"],
            )

            installer.rollback(target, second_receipt.transaction_id)
            installer.rollback(target, receipt.transaction_id)
            restored_server = tree_hash(target)
            restored_server.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_server, before_server)
            self.assertEqual(tree_hash(client), before_client)

    def test_update_source_reuse_never_attempts_client_commit(self):
        from xyequip import installer as installer_module
        from xyequip.batch import BatchEquipmentService
        from xyequip.installer import EquipmentInstaller
        from xyequip.planner import EquipmentPlanner
        from xyequip.transaction import atomic_write_bytes as real_atomic_write

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Server"
            client = root / "Client" / "data"
            make_target(target)
            make_client(client)
            connection = sqlite3.connect(target / "Mud2/DB/ApexM2.DB")
            connection.execute("ALTER TABLE StdItems ADD COLUMN DuraMax INTEGER DEFAULT 8000")
            connection.commit()
            connection.close()
            before_server = tree_hash(target)
            before_client = tree_hash(client)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "来源编号": "1"}], Path("09_装备批量生成.xlsx")
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, client, mode="update")
            self.assertEqual(plan.blockers, [])
            failed = False

            def fail_once(path: Path, data: bytes) -> None:
                nonlocal failed
                if Path(path).name == "StateItem.wzl" and not failed:
                    failed = True
                    raise PermissionError("simulated locked client library")
                real_atomic_write(path, data)

            installer = EquipmentInstaller(EQUIPMENT_ROOT.parent)
            with patch.object(installer_module, "atomic_write_bytes", side_effect=fail_once):
                receipt = installer.install(plan)
            self.assertFalse(failed)
            installer.rollback(target, receipt.transaction_id)
            restored_server = tree_hash(target)
            restored_server.pop(".xydp/equipment-installed.json", None)
            self.assertEqual(restored_server, before_server)
            self.assertEqual(tree_hash(client), before_client)

    def test_update_filled_wrong_slot_blocks(self):
        from xyequip.batch import BatchEquipmentService
        from xyequip.planner import EquipmentPlanner

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            make_target(target)
            compiled = BatchEquipmentService(EQUIPMENT_ROOT.parent).compile_update_rows(
                [{"名称": "青铜头盔", "部位": "武器"}], Path("09_装备批量生成.xlsx")
            )
            plan = EquipmentPlanner(EQUIPMENT_ROOT.parent).preflight(target, compiled, mode="update")
            self.assertTrue(any("不一致" in item for item in plan.blockers))


if __name__ == "__main__":
    unittest.main()
