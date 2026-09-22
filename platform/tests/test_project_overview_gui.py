import tempfile
import unittest
from pathlib import Path

from xydp.project_overview_gui import ProjectOverviewMixin, selectable_files_in


class _Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Listbox:
    def __init__(self):
        self.items = []

    def delete(self, _start, _end):
        self.items.clear()

    def insert(self, _where, value):
        self.items.append(value)


class _Notebook:
    def __init__(self):
        self.selected = None

    def select(self, value):
        self.selected = value


class ProjectOverviewGuiTests(unittest.TestCase):
    def test_selectable_files_in_lists_only_supported_direct_files(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            (folder / "b.txt").write_text("b", encoding="utf-8")
            (folder / "a.xlsx").write_text("a", encoding="utf-8")
            (folder / "skip.json").write_text("{}", encoding="utf-8")
            nested = folder / "nested"
            nested.mkdir()
            (nested / "nested.csv").write_text("n", encoding="utf-8")

            self.assertEqual(
                selectable_files_in(folder),
                [str(folder / "a.xlsx"), str(folder / "b.txt")],
            )

    def test_config_sync_uses_only_current_selected_file(self):
        selected = Path("C:/custom/chosen.xlsx")
        app = object.__new__(ProjectOverviewMixin)
        app.overview_input = _Value(str(selected))
        app.config_sync_paths = []
        app.config_sync_document_id = None
        app.current_config_sync_plan = object()
        app.config_sync_selected = _Listbox()
        app.tabs = {"脚本配置同步": object()}
        app.notebook = _Notebook()
        app._selected_project_card = lambda: {
            "id": "document:mingge_content",
            "entry": {"supported": True, "tab": "脚本配置同步"},
            "inputs": [{"path": "C:/registered/one.xlsx"}],
            "platform": "玄渊成果植入平台",
        }

        app.goto_project_entry()

        self.assertEqual(app.config_sync_paths, [selected])
        self.assertEqual(app.config_sync_document_id, "mingge_content")
        self.assertEqual(app.config_sync_selected.items, [str(selected)])
        self.assertIsNone(app.current_config_sync_plan)
        self.assertIs(app.notebook.selected, app.tabs["脚本配置同步"])


if __name__ == "__main__":
    unittest.main()
