import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xydp.cli import _parser, main
from xydp.gui import TAB_TITLES
from xydp.importer import ImportError as PackageImportError, PackageImporter
from xydp.migration import MigrationRegistry


def package_data(package_id="xy.imported"):
    return {
        "schema_version": 1, "id": package_id, "version": "1.0.0", "display_name": "导入包",
        "status": "candidate", "engine": "LFM2", "bundle": None, "dependencies": [],
        "parameters": {}, "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
        "operations": [], "preflight_checks": [], "post_checks": [], "evidence": []
    }


class AppToolsTests(unittest.TestCase):
    def test_gui_has_required_tabs_and_batch_equipment(self):
        self.assertEqual(
            TAB_TITLES,
            ("项目总览", "目标管理", "成果包库", "预检报告", "安装历史/回滚", "开发者包导入", "脚本配置同步", "命格", "非常驻脚本", "装备回收", "处决测试", "NPC编辑", "批量做装备", "装备光环", "怪物库"),
        )

    def test_cli_supports_script_folder_and_resident_commands(self):
        parser = _parser()
        self.assertEqual(parser.parse_args(["script-folder-list"]).command, "script-folder-list")
        self.assertEqual(
            parser.parse_args(["script-folder-link", "--id", "demo", "--package", "xy.demo"]).command,
            "script-folder-link",
        )
        self.assertEqual(
            parser.parse_args(["resident-preflight", "--server", "D:\\Server"]).command,
            "resident-preflight",
        )
        self.assertEqual(
            parser.parse_args(["execution-preflight", "--server", "D:\\Server"]).command,
            "execution-preflight",
        )
        self.assertEqual(
            parser.parse_args([
                "config-sync-preflight", "--server", "D:\\Server",
                "--file", "E:\\XuanYuanDevPlatform\\所需材料表格汇总\\02_捐献.xlsx",
            ]).command,
            "config-sync-preflight",
        )
        self.assertEqual(
            parser.parse_args([
                "recycle-config-preflight", "--server", "D:\\Server",
                "--input", "E:\\XuanYuanDevPlatform\\所需材料表格汇总\\19_装备回收配置.xlsx",
            ]).command,
            "recycle-config-preflight",
        )
        self.assertEqual(
            parser.parse_args([
                "recycle-config-search", "--input", "E:\\XuanYuanDevPlatform\\所需材料表格汇总\\19_装备回收配置.xlsx",
                "--keyword", "木剑",
            ]).command,
            "recycle-config-search",
        )

    def test_cli_registers_lists_and_shows_raw_script_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "来源" / "副本脚本"; source.mkdir(parents=True)
            (source / "使用说明.md").write_text("# 使用说明\n待首次验证", encoding="utf-8")
            (source / "脚本.txt").write_text("[@DEMO]", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--root", str(root / "platform"), "script-folder-register", "--source", str(source)]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "pending")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--root", str(root / "platform"), "script-folder-list"]), 0)
            self.assertEqual(json.loads(output.getvalue())[0]["script_id"], "副本脚本")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--root", str(root / "platform"), "script-folder-show", "--id", "副本脚本"]), 0)
            self.assertIn("待首次验证", json.loads(output.getvalue())["instructions"])

    def test_cli_resident_preflight_reports_candidate_and_does_not_write_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            platform = root / "platform"
            package = platform / "packages/candidate/xy.resident.cli"
            (package / "payload").mkdir(parents=True)
            data = package_data("xy.resident.cli")
            data["residency"] = "resident"
            data["operations"] = [{"type": "copy", "source": "payload/demo.txt", "target": "Mir200/Envir/demo.txt"}]
            (package / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            (package / "payload/demo.txt").write_text("demo", encoding="utf-8")
            server = root / "server"
            envir = server / "Mir200/Envir"; envir.mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--root", str(platform), "resident-preflight", "--server", str(server)])
            result = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(result["operation"], "resident-base")
            self.assertEqual(result["candidate_packages"], ["xy.resident.cli"])
            self.assertFalse((envir / "demo.txt").exists())

    def test_package_importer_imports_valid_xypkg(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "demo.xypkg"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("manifest.json", json.dumps(package_data(), ensure_ascii=False))
                zf.writestr("payload/demo.txt", "玄渊")
            imported = PackageImporter(root / "packages").import_archive(archive)
            self.assertEqual(imported.id, "xy.imported")
            self.assertEqual((root / "packages/candidate/xy.imported/payload/demo.txt").read_text(encoding="utf-8"), "玄渊")

    def test_package_importer_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "bad.xypkg"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("manifest.json", json.dumps(package_data("xy.badzip")))
                zf.writestr("../escape.txt", "bad")
            with self.assertRaisesRegex(PackageImportError, "越界"):
                PackageImporter(root / "packages").import_archive(archive)

    def test_package_importer_rejects_executable_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "unsafe.xypkg"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("manifest.json", json.dumps(package_data("xy.unsafeimport")))
                zf.writestr("payload/run.ps1", "Write-Host unsafe")
            with self.assertRaisesRegex(Exception, "可执行文件"):
                PackageImporter(root / "packages").import_archive(archive)

    def test_migration_registry_copies_source_and_records_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "source.txt"; source.write_text("原始技能", encoding="utf-8")
            registry = MigrationRegistry(root / "platform")
            record = registry.copy_and_register(source, "xy.demo", "candidate")
            self.assertTrue(Path(record.destination).exists())
            self.assertEqual(len(record.sha256), 64)
            saved = json.loads((root / "platform/migration/registry.json").read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["package_id"], "xy.demo")

    def test_cli_lists_packages_as_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); package = root / "packages/candidate/xy.cli"; package.mkdir(parents=True)
            (package / "manifest.json").write_text(json.dumps(package_data("xy.cli")), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--root", str(root), "list-packages"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())[0]["id"], "xy.cli")

    def test_cli_validates_package_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); package = root / "candidate/xy.valid"; package.mkdir(parents=True)
            (package / "manifest.json").write_text(json.dumps(package_data("xy.valid")), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--root", str(root), "validate-package", str(package)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["valid"], "xy.valid")

    def test_validator_rejects_executable_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); package = root / "xy.unsafe"; package.mkdir()
            (package / "manifest.json").write_text(json.dumps(package_data("xy.unsafe")), encoding="utf-8")
            (package / "run.bat").write_text("echo unsafe", encoding="ascii")
            output = io.StringIO()
            with self.assertRaisesRegex(Exception, "可执行文件"):
                with contextlib.redirect_stdout(output):
                    main(["--root", str(root), "validate-package", str(package)])

    def test_validator_rejects_non_boolean_preserve_existing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "xy.invalid-preserve"
            (package / "payload").mkdir(parents=True)
            (package / "payload/config.txt").write_text("demo", encoding="utf-8")
            data = package_data("xy.invalid-preserve")
            data["operations"] = [{
                "type": "render",
                "source": "payload/config.txt",
                "target": "Mir200/Envir/config.txt",
                "preserve_existing": "yes",
            }]
            (package / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "preserve_existing"):
                main(["--root", str(root), "validate-package", str(package)])


if __name__ == "__main__":
    unittest.main()
