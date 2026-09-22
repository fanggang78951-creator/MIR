from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from xydp.cli import _parser


class EquipmentBridgeTests(unittest.TestCase):
    def test_ui_default_server_is_mirserver(self):
        from xydp.equipment_bridge import EquipmentUiState

        state = EquipmentUiState()
        self.assertEqual(state.server_root, r"D:\MirServer")

    def test_cli_equipment_preflight_defaults_to_mirserver(self):
        args = _parser().parse_args(["equipment-preflight"])
        self.assertEqual(args.server, Path(r"D:\MirServer"))
        self.assertEqual(
            args.input,
            Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\09_装备批量生成.xlsx"),
        )

    def test_cli_supports_full_equipment_update_commands(self):
        preflight = _parser().parse_args([
            "equipment-update-preflight", "--client-data", r"D:\Client\data"
        ])
        apply = _parser().parse_args(["equipment-update-apply", "--input", "update.xlsx", "--yes"])
        self.assertEqual(preflight.server, Path(r"D:\MirServer"))
        self.assertEqual(preflight.client_data, Path(r"D:\Client\data"))
        self.assertEqual(
            preflight.input,
            Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\09_装备批量生成.xlsx"),
        )
        self.assertTrue(apply.yes)
        export = _parser().parse_args(["equipment-update-export", "--output", "update.xlsx"])
        self.assertEqual(export.server, Path(r"D:\MirServer"))

    def test_cli_supports_equipment_hint_sync_commands(self):
        preflight = _parser().parse_args([
            "equipment-hint-preflight", "--input", "hint.xlsx", "--client-data", r"D:\Client\data"
        ])
        apply = _parser().parse_args([
            "equipment-hint-apply", "--input", "hint.xlsx", "--client-data", r"D:\Client\data", "--yes"
        ])
        export = _parser().parse_args(["equipment-hint-export", "--output", "hint.xlsx"])
        self.assertEqual(preflight.server, Path(r"D:\MirServer"))
        self.assertTrue(apply.yes)
        self.assertEqual(export.output, Path("hint.xlsx"))

    def test_bridge_uses_platform_master_workbook(self):
        from xydp.equipment_bridge import EquipmentBridge

        bridge = EquipmentBridge(Path(r"E:\XuanYuanDevPlatform"))
        self.assertEqual(
            bridge.default_workbook,
            Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\09_装备批量生成.xlsx"),
        )
        self.assertEqual(
            bridge.default_update_workbook,
            Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\09_装备批量生成.xlsx"),
        )
        self.assertEqual(
            bridge.default_material_workbook,
            Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\11_材料批量生成.xlsx"),
        )
        self.assertEqual(
            bridge.default_hint_workbook,
            Path(r"E:\XuanYuanDevPlatform\做装备\templates\XuanYuanItemHints.xlsx"),
        )

    def test_build_includes_equipment_source_and_profiles(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "build.ps1").read_text(encoding="utf-8")
        self.assertRegex(build, r"(?m)^\$BuildArguments\s*=\s*@\([^\n]*\(Join-Path \$PlatformRoot 'tools\\build_platform_release\.py'\)[^\n]*'--root', \$PlatformRoot")
        self.assertRegex(build, r"(?m)^& \$PythonCommand @BuildArguments\s*$")

        builder = root / "tools/build_platform_release.py"
        builder_text = builder.read_text(encoding="utf-8")
        self.assertIn(
            "timeout=180 if label == 'frozen-gui-smoke' else 3600",
            builder_text,
            "one-file GUI needs a cold-start allowance without weakening the other build gates",
        )
        tree = ast.parse(builder_text, filename=str(builder))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        loops = [node for node in main.body if isinstance(node, ast.For)
                 and isinstance(node.target, ast.Tuple)
                 and [part.id for part in node.target.elts if isinstance(part, ast.Name)] == ["kind", "script", "name", "mode"]]
        self.assertEqual(len(loops), 1, "GUI/CLI must share one actual build command loop")
        loop = loops[0]
        calls = [i for i, node in enumerate(loop.body) if isinstance(node, ast.Expr)
                 and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                 and node.value.func.id == "run" and node.value.args
                 and isinstance(node.value.args[0], ast.Name) and node.value.args[0].id == "argv"]
        self.assertEqual(len(calls), 1)
        # Execute only command construction through run(argv), never main(),
        # imports, file writes, subprocesses, PyInstaller or artifact inspection.
        loop.body = loop.body[:calls[0] + 1]
        fragment = ast.Module(body=[loop], type_ignores=[])
        allowed = (ast.Module, ast.For, ast.Tuple, ast.List, ast.Name, ast.Load,
                   ast.Store, ast.Assign, ast.AugAssign, ast.BinOp, ast.Add,
                   ast.Div, ast.Constant, ast.Call, ast.Attribute, ast.Expr)
        for node in ast.walk(fragment):
            self.assertIsInstance(node, allowed, f"Unreviewed command-construction syntax: {type(node).__name__}")
            if isinstance(node, ast.Attribute):
                self.assertIn(node.attr, ("executable", "release_id", "glob", "append"))
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertIn(node.func.id, ("str", "sorted", "run"))
                else:
                    self.assertIsInstance(node.func, ast.Attribute)
                    self.assertIn(node.func.attr, ("glob", "append"))
        captured = {}

        def capture(argv, label):
            self.assertNotIn(label, captured)
            captured[label] = list(argv)

        scope = {"__builtins__": {"str": str, "sorted": sorted}, "root": root,
                 "build": root / "runtime/build-contract", "run": capture,
                 "sys": SimpleNamespace(executable="test-python"),
                 "a": SimpleNamespace(release_id="contract")}
        exec(compile(ast.fix_missing_locations(fragment), str(builder), "exec"), scope)
        self.assertEqual(set(captured), {"gui-build", "cli-build"})
        required = [("--paths", str(root / "做装备/src")),
                    ("--paths", str(root / "vendor")), ("--collect-all", "openpyxl"),
                    ("--add-data", str(root / "做装备/profiles") + ";做装备/profiles"),
                    ("--add-data", str(root / "做装备/assets") + ";做装备/assets")]
        for kind, mode in (("gui", "--windowed"), ("cli", "--console")):
            with self.subTest(kind=kind):
                argv = captured[kind + "-build"]
                self.assertEqual(argv[:3], ["test-python", "-m", "PyInstaller"])
                self.assertIn(mode, argv)
                self.assertEqual(argv[-1], str(root / f"run_{kind}.py"))
                pairs = list(zip(argv, argv[1:]))
                for pair in required:
                    self.assertIn(pair, pairs)

    def test_gui_uses_one_workbook_and_isolates_create_update_confirmations(self):
        root = Path(__file__).resolve().parents[1]
        gui = (root / "src/xydp/gui.py").read_text(encoding="utf-8")
        self.assertIn('"装备生成/修改源表"', gui)
        self.assertNotIn('self._row(tab, "修改装备源表"', gui)
        self.assertIn('lambda: self.equipment_install("create")', gui)
        self.assertIn('lambda: self.equipment_install("update")', gui)


if __name__ == "__main__":
    unittest.main()
