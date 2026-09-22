from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


ACTIVE = {
    "rage": "xy.optional.rage.core",
    "donate": "xy.optional.donate.core",
}

REMOVED = {
    "xy.ops.rage",
    "xy.ops.rage-title",
    "xy.optional.rage.command",
    "xy.ops.donate",
    "xy.ops.donate-title",
    "xy.optional.donate.command",
    "xy.ops-suite",
}


class OptionalSingleEntryTests(unittest.TestCase):
    def make_server(self, root: Path) -> Path:
        server = root / "server"
        envir = server / "Mir200" / "Envir"
        market = envir / "Market_Def"
        market.mkdir(parents=True)
        (server / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (server / "Mir200" / "!setup.txt").write_bytes(
            "[Setup]\r\nRevivalTime=60000\r\n".encode("gb18030")
        )
        (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
        (envir / "MerChant.txt").write_bytes(b"")
        (market / "QFunction-0.txt").write_bytes((
            "[@AttackDamage]\r\n#IF\r\n#ACT\r\n"
            "[@PlayDie]\r\n#IF\r\n#ACT\r\n"
            "[@PlayOffLine]\r\n#IF\r\n#ACT\r\n"
        ).encode("gb18030"))
        database = server / "Mud2/DB/ApexM2.DB"
        database.parent.mkdir(parents=True)
        rage_manifest = json.loads(
            (platform_root() / "packages/candidate/xy.optional.rage.core/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        rage_values = next(
            item for item in rage_manifest["operations"] if item["type"] == "sqlite_upsert"
        )["values"]
        columns = ["Idx INTEGER", *(
            f'"{name}" {"TEXT" if name == "Name" else "INTEGER"}' for name in rage_values
        )]
        connection = sqlite3.connect(database)
        try:
            connection.execute(f'CREATE TABLE StdItems ({", ".join(columns)})')
            connection.commit()
        finally:
            connection.close()
        return server

    def test_only_one_active_package_per_feature(self):
        root = platform_root() / "packages" / "candidate"
        repository = PackageRepository(platform_root() / "packages")
        repository.refresh()
        self.assertTrue(REMOVED.isdisjoint(repository.packages))
        for package_id in REMOVED:
            self.assertFalse((root / package_id / "manifest.json").exists(), package_id)
        self.assertIn(ACTIVE["rage"], repository.packages)
        self.assertIn(ACTIVE["donate"], repository.packages)

    def test_each_core_owns_its_public_command_and_declared_entry_scope(self):
        expected = {
            "rage": ("XY_RAGE_COMMAND", "@XY_RAGE_NPC_MAIN", "狂暴NPC接口.txt"),
            "donate": ("XY_DONATE_COMMAND", "@XY_DONATE_TRIGGER", "捐献核心.txt"),
        }
        for feature, package_id in ACTIVE.items():
            package = validate_package(platform_root() / "packages" / "candidate" / package_id)
            public_label, trigger, script_name = expected[feature]
            self.assertIn(public_label, package.claims["labels"])
            operation_types = {item["type"] for item in package.operations}
            self.assertIn("managed_block", operation_types)
            targets = "\n".join(str(item.get("target", "")) for item in package.operations)
            content = "\n".join(str(item.get("content", "")) for item in package.operations)
            self.assertIn(f"[@{public_label}]", content)
            self.assertIn(trigger, content)
            self.assertIn(script_name, content)
            if feature == "rage":
                self.assertIn("exclusive_unique_line", operation_types)
                self.assertIn("sqlite_upsert", operation_types)
                self.assertIn("MerChant", targets)
                self.assertEqual(package.claims["npcs"], ["玄渊运营/狂暴之力"])
            else:
                self.assertNotIn("unique_line", operation_types)
                self.assertNotIn("sqlite_upsert", operation_types)
                self.assertNotIn("MerChant", targets)
                self.assertEqual(package.claims["npcs"], [])

    def test_each_package_explains_install_npc_and_icon_interfaces(self):
        required = {
            ACTIVE["rage"]: ("平台入口", "对外接口", "唯一实体NPC", "左上狂暴图标", "不得复制"),
            ACTIVE["donate"]: ("使用方法", "接口命令", "NPC调用", "屏幕图标调用", "不自动创建NPC", "不自动创建屏幕图标"),
        }
        for package_id, phrases in required.items():
            text = (
                platform_root() / "packages" / "candidate" / package_id / "README_使用说明.md"
            ).read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(phrase, text, f"{package_id} missing {phrase}")

    def test_presets_and_cli_have_no_v2_or_adapter_variant(self):
        from xydp.cli import _parser
        from xydp.optional_presets import PRESETS

        self.assertEqual(set(PRESETS), {"rage", "donate"})
        self.assertEqual(PRESETS["rage"].package_ids, (ACTIVE["rage"],))
        self.assertEqual(PRESETS["donate"].package_ids, (ACTIVE["donate"],))

        gui = (platform_root() / "src" / "xydp" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("狂暴含单一NPC唯一入口", gui)
        self.assertNotIn("狂暴V2", gui)
        self.assertNotIn("捐献V2", gui)

        parser = _parser()
        for feature in ("rage", "donate"):
            for action in ("preflight", "install", "rollback"):
                command = f"{feature}-{action}"
                self.assertEqual(parser.parse_args([command]).command, command)
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parser.parse_args([f"{feature}-v2-{action}"])

    def test_each_one_click_is_one_package_idempotent_and_byte_rollback_safe(self):
        from xydp.optional_presets import OptionalPresetService

        for feature in ("rage", "donate"):
            with self.subTest(feature=feature), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                server = self.make_server(root)
                before = {
                    path.relative_to(server): path.read_bytes()
                    for path in server.rglob("*") if path.is_file()
                }
                service = OptionalPresetService(platform_root(), backups_root=root / "backups")
                plan = service.preflight(feature, server)
                if feature == "rage":
                    self.assertEqual(plan.package_ids, [
                        "xy.combat.core", "xy.combat.runtime-refresh", "xy.combat.drop", ACTIVE[feature]
                    ])
                else:
                    self.assertEqual(plan.package_ids, [ACTIVE[feature]])
                self.assertEqual(plan.operation_type, f"optional-preset:{feature}")
                self.assertEqual(
                    any("MerChant" in item.relative_path for item in plan.changes),
                    feature == "rage",
                )
                receipt = service.install(feature, plan)
                self.assertEqual(service.preflight(feature, server).changes, [])
                self.assertEqual(service.rollback_latest(feature, server), receipt.transaction_id)
                after = {
                    path.relative_to(server): path.read_bytes()
                    for path in server.rglob("*")
                    if path.is_file() and ".xydp" not in path.parts
                }
                self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
