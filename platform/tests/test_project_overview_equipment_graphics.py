from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xydp.project_overview import ProjectOverview


class EquipmentGraphicsProjectRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self._write("所需材料表格汇总/00_填写文档注册表.json", {"documents": [
            {"id": "equipment_graphics", "file": "装备图形配置.json", "consumer": "equipment-graphics"},
            {"id": "equipment_wash_import", "file": "洗练属性.txt", "consumer": "equipment-wash-import"},
        ]})
        self.target = self.root / "target"
        self._write("所需材料表格汇总/装备图形配置.json", {
            "schemaVersion": 1,
            "target": {"serverRoot": str(self.target)},
            "items": [],
        })
        self._write("所需材料表格汇总/洗练属性.txt", "说明")
        self._write("run_cli.py", "# isolated entry")
        self.service = ProjectOverview(self.root)

    def _write(self, relative: str, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value, encoding="utf-8")
        return path

    def test_registry_card_uses_batch_equipment_tab_and_graphics_preflight(self):
        card = self.service.get("document:equipment_graphics")
        self.assertEqual("批量做装备", card["entry"]["tab"])
        self.assertEqual("equipment-graphics", card["entry"]["route"])
        self.assertTrue(card["entry"]["supported"])
        order = self.service.task_order(card["id"], self.target, validation=True)
        self.assertEqual(
            [order["preflight_argv"][0], order["preflight_argv"][1], "--root", str(self.root),
             "equipment-graphics-preflight", "--config", str(self.root / "所需材料表格汇总/装备图形配置.json")],
            order["preflight_argv"],
        )
        self.assertNotIn("config-sync-preflight", order["preflight_argv"])
        self.assertNotIn("equipment-preflight", order["preflight_argv"])

    def test_existing_equipment_route_still_uses_config_sync(self):
        card = self.service.get("document:equipment_wash_import")
        order = self.service.task_order(card["id"], self.target, validation=True)
        self.assertIn("config-sync-preflight", order["preflight_argv"])
        self.assertNotIn("equipment-graphics-preflight", order["preflight_argv"])

    def test_graphics_route_rejects_target_mismatch(self):
        card = self.service.get("document:equipment_graphics")
        with self.assertRaisesRegex(ValueError, "配置目标与任务单目标不一致"):
            self.service.task_order(card["id"], self.root / "other-target", validation=True)

    def test_graphics_route_derives_server_root_from_database_path(self):
        self._write("所需材料表格汇总/装备图形配置.json", {
            "schemaVersion": 1,
            "target": {"database": str(self.target / "Mud2" / "DB" / "ApexM2.DB")},
            "items": [],
        })
        card = self.service.get("document:equipment_graphics")
        order = self.service.task_order(card["id"], self.target, validation=True)
        self.assertIn("equipment-graphics-preflight", order["preflight_argv"])

    def test_graphics_route_accepts_nonstandard_database_below_explicit_server_root(self):
        self._write("所需材料表格汇总/装备图形配置.json", {
            "schemaVersion": 1,
            "target": {
                "serverRoot": str(self.target),
                "database": str(self.target / "ApexM2.DB"),
            },
            "items": [],
        })
        card = self.service.get("document:equipment_graphics")
        order = self.service.task_order(card["id"], self.target, validation=True)
        self.assertIn("equipment-graphics-preflight", order["preflight_argv"])


if __name__ == "__main__":
    unittest.main()
