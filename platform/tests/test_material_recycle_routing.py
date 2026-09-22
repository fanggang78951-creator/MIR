from __future__ import annotations

import json
import re
import types
import unittest
from pathlib import Path

from xydp.config_sync import ConfigSyncService
from xydp.user_documents import DOCUMENTS
from xydp.recycle_config import (
    MaterialRecycleWorkbook, RecycleCategory, RecycleRule, compile_material_qfunction,
)


CANDIDATE_ROOT = Path(__file__).resolve().parents[1]


class MaterialRecycleRoutingTests(unittest.TestCase):
    def test_each_recycle_workbook_uses_existing_dedicated_route(self):
        document = lambda document_id: types.SimpleNamespace(id=document_id)
        self.assertEqual(ConfigSyncService._route([document("recycle_config")]), "recycle-config")
        self.assertEqual(ConfigSyncService._route([document("material_recycle")]), "recycle-config")

    def test_recycle_workbooks_cannot_be_mixed_or_duplicated(self):
        document = lambda document_id: types.SimpleNamespace(id=document_id)
        self.assertEqual(
            ConfigSyncService._route([document("recycle_config"), document("material_recycle")]),
            "incompatible",
        )
        self.assertEqual(
            ConfigSyncService._route([document("recycle_config"), document("recycle_config")]),
            "incompatible",
        )

    def test_material_categories_render_checkboxes_and_independent_auto_switch(self):
        categories = tuple(
            RecycleCategory(f"M_C{index:02d}", f"大陆{index}材料", index, (
                RecycleRule(f"M_C{index:02d}", f"大陆{index}材料", f"材料{index}", "原生金币", "", index, index, 1),
            )) for index in range(1, 11)
        )
        workbook = MaterialRecycleWorkbook("candidate.xlsx", "hash", "材料回收", categories, mode="自动+手动")
        rendered = compile_material_qfunction(workbook, flags={item.id: 30 + i for i, item in enumerate(categories)}, command_id=32, auto_flag=98, background_index=28)
        self.assertIn("[@XY_MATERIAL_RECYCLE_COMMAND]", rendered)
        self.assertIn("[@XY_MATERIAL_RECYCLE_AUTO_SWITCH]", rendered)
        self.assertEqual(len(re.findall(r"^\[@XY_MATERIAL_RECYCLE_TOGGLE_\d{3}\]$", rendered, re.MULTILINE)), 10)
        self.assertIn("OPENMERCHANTBIGDLG 28 0", rendered)
        self.assertNotIn("N$XY_RecycleEquipBonus", rendered)
        self.assertNotRegex(rendered, r"^\[@XY_MATERIAL_RECYCLE_P\d{2}\]$",)

    def test_candidate_registry_and_document_names_use_one_material_id(self):
        registry_path = CANDIDATE_ROOT / "所需材料表格汇总" / "00_填写文档注册表.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        entries = {entry["id"]: entry for entry in registry["documents"]}
        self.assertEqual(entries["material_recycle"]["file"], "19B_材料回收配置.xlsx")
        self.assertEqual(entries["material_recycle"]["consumer"], "recycle-config")
        self.assertEqual(DOCUMENTS["recycle_config"], "19_装备回收配置.xlsx")
        self.assertEqual(DOCUMENTS["material_recycle"], "19B_材料回收配置.xlsx")
        self.assertNotIn("material_recycle_config", entries)
        self.assertNotIn("material_recycle_config", DOCUMENTS)


if __name__ == "__main__":
    unittest.main()
