from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xydp.configpatch import ConfigPatchError, merge_config_text, set_flat_config_values
from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.validator import PackageValidationError, validate_package


class ConfigMergePrimitiveTests(unittest.TestCase):
    def test_missing_target_uses_default_template_and_requested_newline(self):
        defaults = "[基础]\n功能开关=1\n"
        self.assertEqual(merge_config_text(None, defaults, "\r\n"), "[基础]\r\n功能开关=1\r\n")

    def test_existing_values_are_preserved_and_missing_defaults_are_added(self):
        current = "[消耗]\r\n; 用户调整\r\n消耗数量=999\r\n"
        defaults = "[消耗]\n消耗类型=账户金刚石\n消耗数量=100\n[属性]\n神力倍攻=200\n"
        merged = merge_config_text(current, defaults, "\r\n")
        self.assertIn("; 用户调整\r\n消耗数量=999", merged)
        self.assertIn("消耗类型=账户金刚石", merged)
        self.assertIn("[属性]\r\n神力倍攻=200", merged)
        self.assertNotIn("消耗数量=100", merged)

    def test_second_merge_is_idempotent(self):
        defaults = "[基础]\n功能开关=1\n[消耗]\n消耗数量=100\n"
        first = merge_config_text("[基础]\r\n功能开关=0\r\n", defaults, "\r\n")
        self.assertEqual(merge_config_text(first, defaults, "\r\n"), first)

    def test_duplicate_section_is_rejected(self):
        with self.assertRaisesRegex(ConfigPatchError, "重复节"):
            merge_config_text("[基础]\n功能开关=1\n[基础]\n其他=1\n", "[基础]\n功能开关=1\n", "\n")

    def test_duplicate_key_is_rejected_case_insensitively(self):
        with self.assertRaisesRegex(ConfigPatchError, "重复键"):
            merge_config_text("[base]\nEnable=1\nenable=0\n", "[base]\nEnable=1\n", "\n")

    def test_key_before_section_is_rejected(self):
        with self.assertRaisesRegex(ConfigPatchError, "节之前"):
            merge_config_text("功能开关=1\n", "[基础]\n功能开关=1\n", "\n")

    def test_flat_config_set_replaces_only_requested_values_and_is_idempotent(self):
        current = "Other=9\r\nSendItemDescList=0\r\nSendTzItemDescList=0\r\n"
        wanted = {"SendItemDescList": "1", "SendTzItemDescList": "1"}
        first = set_flat_config_values(current, wanted, "\r\n")
        self.assertEqual(first, "Other=9\r\nSendItemDescList=1\r\nSendTzItemDescList=1\r\n")
        self.assertEqual(set_flat_config_values(first, wanted, "\r\n"), first)

    def test_flat_config_set_rejects_duplicate_target_key(self):
        with self.assertRaisesRegex(ConfigPatchError, "重复键"):
            set_flat_config_values("SendItemDescList=0\nsenditemdesclist=1\n", {"SendItemDescList": "1"}, "\n")


class ConfigMergeOperationTests(unittest.TestCase):
    def make_target(self, root: Path) -> Path:
        envir = root / "Mir200/Envir"
        (root / "Mir200").mkdir(parents=True)
        (root / "Mir200/M2Server.exe").write_bytes(b"M2")
        (envir / "Market_Def").mkdir(parents=True)
        (envir / "MapInfo.txt").write_text("[0 盟重]\r\n", encoding="gb18030")
        (envir / "Market_Def/QFunction-0.txt").write_text("[@PlayLogin]\r\n#IF\r\n#ACT\r\n", encoding="gb18030")
        return envir / "QuestDiary/玄渊配置/演示配置.txt"

    def make_package(self, root: Path) -> Path:
        package = root / "packages/candidate/xy.optional.config-demo"
        (package / "payload").mkdir(parents=True)
        (package / "payload/demo-config.txt").write_text(
            "[基础]\n功能开关=1\n[消耗]\n消耗数量=100\n", encoding="utf-8"
        )
        data = {
            "schema_version": 1, "id": "xy.optional.config-demo", "version": "1.0.0",
            "display_name": "配置合并演示", "status": "candidate", "engine": "LFM2",
            "residency": "optional", "bundle": None, "dependencies": [], "parameters": {},
            "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
            "operations": [{
                "type": "config_merge", "source": "payload/demo-config.txt",
                "target": "Mir200/Envir/QuestDiary/玄渊配置/演示配置.txt",
                "source_encoding": "utf-8", "target_encoding": "gb18030", "newline": "\r\n",
            }],
            "preflight_checks": [], "post_checks": [], "evidence": ["static:test"],
        }
        (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return package

    def test_install_preserves_custom_value_adds_missing_key_and_rolls_back_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root / "server"; config = self.make_target(target)
            config.parent.mkdir(parents=True)
            original = "[基础]\r\n功能开关=0\r\n".encode("gb18030")
            config.write_bytes(original)
            self.make_package(root)
            repository = PackageRepository(root / "packages"); repository.refresh()
            installer = Installer(repository, root / "backups")

            plan = installer.preflight(target, ["xy.optional.config-demo"], {})
            self.assertEqual(config.read_bytes(), original)
            planned = plan.changes[0].after.decode("gb18030")
            self.assertIn("功能开关=0", planned)
            self.assertIn("[消耗]\r\n消耗数量=100", planned)
            receipt = installer.install(plan)
            self.assertEqual(installer.preflight(target, ["xy.optional.config-demo"], {}).changes, [])
            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(config.read_bytes(), original)

    def test_missing_config_is_created_in_declared_encoding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root / "server"; config = self.make_target(target)
            self.make_package(root)
            repository = PackageRepository(root / "packages"); repository.refresh()
            installer = Installer(repository, root / "backups")
            receipt = installer.install(installer.preflight(target, ["xy.optional.config-demo"], {}))
            self.assertIn("功能开关=1", config.read_bytes().decode("gb18030"))
            installer.rollback(target, receipt.transaction_id)
            self.assertFalse(config.exists())

    def test_validator_rejects_missing_config_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); package = self.make_package(root)
            (package / "payload/demo-config.txt").unlink()
            with self.assertRaisesRegex(PackageValidationError, "源文件不存在"):
                validate_package(package)

    def test_config_set_is_read_only_in_preflight_idempotent_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root / "server"; self.make_target(target)
            setup = target / "Mir200/!setup.txt"
            original = b"Other=9\r\nSendItemDescList=0\r\nSendTzItemDescList=0\r\n"
            setup.write_bytes(original)
            package = root / "packages/verified/xy.combat.core"
            package.mkdir(parents=True)
            data = {
                "schema_version": 1, "id": "xy.combat.core", "version": "1.2.0",
                "display_name": "战斗核心", "status": "verified", "engine": "LFM2",
                "residency": "resident", "bundle": "combat-suite", "dependencies": [], "parameters": {},
                "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
                "operations": [{
                    "type": "config_set", "target": "Mir200/!setup.txt",
                    "values": {"SendItemDescList": "1", "SendTzItemDescList": "1"},
                    "target_encoding": "gb18030",
                }],
                "preflight_checks": [], "post_checks": [], "evidence": ["static:test"],
            }
            (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            repository = PackageRepository(root / "packages"); repository.refresh()
            installer = Installer(repository, root / "backups")
            plan = installer.preflight(target, ["xy.combat.core"], {})
            self.assertEqual(setup.read_bytes(), original)
            receipt = installer.install(plan)
            self.assertEqual(setup.read_text(encoding="gb18030"), "Other=9\nSendItemDescList=1\nSendTzItemDescList=1\n")
            self.assertEqual(installer.preflight(target, ["xy.combat.core"], {}).changes, [])
            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(setup.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
