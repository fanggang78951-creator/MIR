import json
import ast
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "所需材料表格汇总"
CATALOG = ROOT / "catalog" / "feature_annotations.json"


class GraphicsAppendRegistrationTests(unittest.TestCase):
    def test_append_document_is_separate_and_uses_existing_consumer(self):
        registry = json.loads((DOCS / "00_填写文档注册表.json").read_text(encoding="utf-8"))
        entries = {entry["id"]: entry for entry in registry["documents"]}
        self.assertEqual("44_装备素材替换.json", entries["equipment_graphics"]["file"])
        self.assertEqual("45_装备素材追加.json", entries["equipment_graphics_append"]["file"])
        self.assertEqual("equipment-graphics", entries["equipment_graphics_append"]["consumer"])

    def test_append_template_keeps_database_out_and_separates_static_sources(self):
        template = json.loads((DOCS / "45_装备素材追加.json").read_text(encoding="utf-8"))
        self.assertEqual("equipment-graphics-append", template["operation"])
        self.assertEqual(42, template["expectedResourceCount"])
        self.assertEqual(8900, template["startLooks"])
        self.assertNotIn("database", template["target"])
        self.assertEqual([], template["resources"])
        item = template["resourceItemTemplate"]
        self.assertEqual({"bagImage", "innerImage", "actionFrames"}, set(item["sources"]))
        self.assertEqual({"bagPlacement", "innerPlacement"}, set(item["static"]))
        self.assertFalse(template["safety"]["databaseWrite"])
        self.assertFalse(template["safety"]["bindStdItems"])

    def test_feature_card_is_candidate_and_does_not_claim_game_binding(self):
        card = json.loads(CATALOG.read_text(encoding="utf-8"))["features"]["document:equipment_graphics_append"]
        self.assertIn(card["deployment"]["status"], {"candidate", "published"})
        self.assertFalse(card["game_verified"])
        joined = "\n".join(card["limitations"])
        self.assertIn("不绑定 StdItems", joined)
        self.assertIn("不声称动作嵌入生成的 EXE", joined)

    def test_existing_task_order_target_root_accepts_server_root_without_database(self):
        platform_root = os.environ.get("XYDP_PROJECT_OVERVIEW_ROOT")
        if not platform_root:
            self.skipTest("set XYDP_PROJECT_OVERVIEW_ROOT to the platform root to exercise its task-order helper")
        source = Path(platform_root) / "src" / "xydp" / "project_overview.py"
        self.assertTrue(source.is_file())
        tree = ast.parse(source.read_text(encoding="utf-8"))
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "_equipment_graphics_target_root")
        namespace = {"Path": Path, "json": json, "_json": lambda path, default=None: json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
        with tempfile.TemporaryDirectory() as raw:
            config = Path(raw) / "append.json"
            config.write_text(json.dumps({"target": {"serverRoot": r"D:\\MirServer"}}), encoding="utf-8")
            self.assertEqual(Path(r"D:\MirServer"), namespace["_equipment_graphics_target_root"](config))


if __name__ == "__main__":
    unittest.main()
