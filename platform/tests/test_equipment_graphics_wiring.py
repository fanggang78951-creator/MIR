import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
_override = os.environ.get("XYDP_UI_CANDIDATE_ROOT")
if _override:
    UI = Path(_override).resolve()
elif (ROOT / "src" / "xydp").is_dir():
    UI = ROOT / "src" / "xydp"
else:
    UI = ROOT / "ui_candidate" / "src" / "xydp"


def load_function(path, name, extra=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    candidates = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    node = candidates[0]
    ns = {"Path": Path}
    if extra:
        ns.update(extra)
    exec(compile(ast.Module([node], type_ignores=[]), str(path), "exec"), ns)
    return ns[name]


def load_method_subclass(path, name, base):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    subclass = ast.ClassDef(
        name="ExtractedRoute",
        bases=[ast.Name(id="Base", ctx=ast.Load())],
        keywords=[],
        body=[node],
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[subclass], type_ignores=[]))
    namespace = {"Base": base, "Path": Path, "messagebox": Mock()}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["ExtractedRoute"]


class WiringTests(unittest.TestCase):
    def test_cli_failed_status_is_nonzero_contract(self):
        failed = load_function(UI / "cli.py", "_graphics_result_failed")
        cli_source = (UI / "cli.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(cli_source.count("return 1 if _graphics_result_failed(result) else 0"), 4)
        self.assertTrue(failed({"status": "failed"}))
        self.assertTrue(failed({"status": "failed-restored"}))
        self.assertTrue(failed({"status": "failed-rollback-incomplete"}))
        self.assertTrue(failed({"status": "error"}))
        self.assertTrue(failed({"success": False, "status": "done"}))
        self.assertTrue(failed({"blockers": ["hash drift"]}))
        self.assertFalse(failed({"success": True, "status": "ok", "blockers": []}))

    def test_gui_failure_never_shows_success_and_receipt_feeds_verify(self):
        shown = []
        error = load_function(UI / "gui.py", "_graphics_result_error")
        failed = load_function(UI / "gui.py", "_graphics_result_failed")
        success = load_function(UI / "gui.py", "_graphics_result_success")
        handle = load_function(UI / "gui.py", "_handle_graphics_result", {
            "messagebox": Mock(showerror=lambda *a: shown.append(("error", a)), showinfo=lambda *a: shown.append(("info", a))),
        })
        class Harness:
            pass
        obj = Harness()
        obj._graphics_result_failed = failed.__get__(obj)
        obj._graphics_result_success = success.__get__(obj)
        obj._graphics_result_error = error.__get__(obj)
        obj._show_equipment_graphics_result = Mock()
        handle.__get__(obj)({"status": "failed", "receipt_path": "receipt.json"}, "应用失败", "应用完成")
        self.assertEqual([kind for kind, _ in shown], ["error"])
        obj._show_equipment_graphics_result.assert_called_once()

        shown.clear()
        handle.__get__(obj)({"status": "registered", "receipt_path": "receipt.json"}, "应用失败", "应用完成")
        self.assertEqual(shown, [])

        # A receipt returned by apply is the exact input accepted by verify.
        receipt = Path(tempfile.mkdtemp()) / "receipt.json"
        receipt.write_text(json.dumps({"receipt_path": str(receipt)}), encoding="utf-8")
        core = Mock()
        core.graphics_verify_launcher.return_value = {"success": True, "status": "ok"}
        obj.equipment_graphics_receipt_var = Mock(get=lambda: str(receipt))
        obj.equipment = core
        obj._run_equipment_graphics_async = lambda _op, worker, done: done(worker())
        verify = load_function(UI / "gui.py", "equipment_graphics_verify_launcher", {
            "messagebox": Mock(showerror=Mock()), "Path": Path,
        })
        verify.__get__(obj)()
        core.graphics_verify_launcher.assert_called_once_with(receipt)

    def test_overview_graphics_route_is_explicit(self):
        class Base:
            def goto_project_entry(self):
                self.base_route_calls += 1

        Route = load_method_subclass(UI / "gui.py", "goto_project_entry", Base)

        class Harness(Route):
            pass

        graphics = Harness()
        graphics.base_route_calls = 0
        graphics._selected_project_card = lambda: {
            "id": "document:equipment_graphics",
            "entry": {"supported": True, "tab": "批量做装备"},
            "platform": "玄渊成果植入平台",
        }
        graphics.overview_input = Mock(get=lambda: r"C:\fixture\equipment-graphics.json")
        graphics.equipment_graphics_config_var = Mock()
        graphics.platform_root = Path(r"C:\fixture\platform")
        graphics.tabs = {"批量做装备": object()}
        graphics.notebook = Mock()

        graphics.goto_project_entry()

        graphics.equipment_graphics_config_var.set.assert_called_once_with(r"C:\fixture\equipment-graphics.json")
        graphics.notebook.select.assert_called_once_with(graphics.tabs["批量做装备"])
        self.assertEqual(0, graphics.base_route_calls)

        other = Harness()
        other.base_route_calls = 0
        other._selected_project_card = lambda: {
            "id": "document:material_create",
            "entry": {"supported": True, "tab": "批量做装备"},
        }
        other.equipment_graphics_config_var = Mock()

        other.goto_project_entry()

        self.assertEqual(1, other.base_route_calls)
        other.equipment_graphics_config_var.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
