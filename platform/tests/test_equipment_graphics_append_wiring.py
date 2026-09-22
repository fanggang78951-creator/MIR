import ast
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "xydp" / "gui.py"


def load_route(path: Path, base):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef) and item.name == "goto_project_entry")
    child = ast.ClassDef(
        name="ExtractedRoute",
        bases=[ast.Name(id="Base", ctx=ast.Load())],
        keywords=[], body=[node], decorator_list=[],
    )
    namespace = {"Base": base, "Path": Path, "messagebox": Mock()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[child], type_ignores=[])), str(path), "exec"), namespace)
    return namespace["ExtractedRoute"]


class GraphicsAppendWiringTests(unittest.TestCase):
    def test_append_card_prefers_explicit_selection_then_uses_45_template(self):
        class Base:
            def goto_project_entry(self):
                self.base_calls += 1

        Route = load_route(UI, Base)

        def harness(selected: str):
            item = Route()
            item.base_calls = 0
            item._selected_project_card = lambda: {
                "id": "document:equipment_graphics_append",
                "entry": {"supported": True, "tab": "批量做装备"},
                "platform": "玄渊成果植入平台",
            }
            item.overview_input = Mock(get=lambda: selected)
            item.equipment_graphics_config_var = Mock()
            item.platform_root = Path(r"C:\fixture\platform")
            item.tabs = {"批量做装备": object()}
            item.notebook = Mock()
            return item

        selected = harness(r"C:\task\append.json")
        selected.goto_project_entry()
        selected.equipment_graphics_config_var.set.assert_called_once_with(r"C:\task\append.json")
        selected.notebook.select.assert_called_once_with(selected.tabs["批量做装备"])
        self.assertEqual(0, selected.base_calls)

        defaulted = harness("")
        defaulted.goto_project_entry()
        defaulted.equipment_graphics_config_var.set.assert_called_once_with(
            str(Path(r"C:\fixture\platform") / "所需材料表格汇总" / "45_装备素材追加.json")
        )

    def test_replacement_card_still_defaults_to_44_template(self):
        source = UI.read_text(encoding="utf-8")
        self.assertIn('"document:equipment_graphics": "44_装备素材替换.json"', source)
        self.assertIn('"document:equipment_graphics_append": "45_装备素材追加.json"', source)
        self.assertIn("装备素材替换/追加（配置文件驱动）", source)


if __name__ == "__main__":
    unittest.main()
