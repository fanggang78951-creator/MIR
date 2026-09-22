from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


PACKAGE_ID = "xy.optional.recycle.core"
ITEMS = (
    "木剑",
    "铁剑",
    "青铜剑",
    "短剑",
    "匕首",
    "布衣(男)",
    "布衣(女)",
    "轻型盔甲(男)",
    "轻型盔甲(女)",
    "古铜戒指",
    "铁手镯",
    "金项链",
)


class RecycleCandidatePackageTests(unittest.TestCase):
    def package(self):
        return validate_package(
            platform_root() / "packages" / "verified" / PACKAGE_ID
        )

    def make_server(self, root: Path) -> Path:
        server = root / "server"
        envir = server / "Mir200" / "Envir"
        market = envir / "Market_Def"
        market.mkdir(parents=True)
        (server / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (server / "Mud2" / "DB").mkdir(parents=True)
        (server / "Mud2" / "DB" / "StdItems.DB").write_bytes(b"fixture")
        (envir / "MapInfo.txt").write_text("[0 盟重]\r\n", encoding="gb18030")
        (envir / "MerChant.txt").write_bytes(b"")
        (envir / "UserCmd.txt").write_text("传\t3\r\n", encoding="gb18030")
        (market / "QFunction-0.txt").write_text(
            "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n",
            encoding="gb18030",
        )
        return server

    def test_manifest_is_optional_verified_and_owns_one_command_entry(self):
        package = self.package()
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.version, "1.0.2")
        self.assertEqual(package.residency, "optional")
        self.assertEqual(package.dependencies, ())
        self.assertEqual(
            set(package.claims["labels"]),
            {
                "UserCmd31",
                "XY_RECYCLE_COMMAND",
                "XY_RECYCLE_PAGE",
                "XY_RECYCLE_CONFIRM",
                "XY_RECYCLE_APPLY",
            },
        )
        self.assertEqual(package.claims["variables"], [])
        operation_types = [item["type"] for item in package.operations]
        self.assertEqual(operation_types, ["unique_line", "managed_block"])
        usercmd = package.operations[0]
        self.assertEqual(usercmd["target"], "Mir200/Envir/UserCmd.txt")
        self.assertEqual(usercmd["line"], "快捷回收\t31")
        self.assertEqual(usercmd["key_fields"], [0])

    def test_script_is_confirmed_exact_whitelist_without_auto_recycle(self):
        package = self.package()
        managed = next(item for item in package.operations if item["type"] == "managed_block")
        command = managed["content"]
        script = command
        self.assertIn("[@UserCmd31]", command)
        self.assertIn("GOTO @XY_RECYCLE_COMMAND", command)
        self.assertIn("[@XY_RECYCLE_PAGE]", command)
        self.assertIn("[@XY_RECYCLE_CONFIRM]", command)
        self.assertIn("GOTO @XY_RECYCLE_APPLY", command)
        self.assertIn("[@XY_RECYCLE_APPLY]", command)
        self.assertNotIn("#CALL [\\玄渊功能\\回收", command)
        for name in ITEMS:
            self.assertEqual(script.count(f"CHECKITEM {name} 1"), 10, name)
            self.assertEqual(script.count(f"TAKE {name} 1"), 10, name)
        self.assertEqual(script.count("GIVE 金币 1000"), len(ITEMS) * 10)
        for forbidden in (
            "TakeBagItem",
            "OPENMERCHANTBIGDLG",
            "自动回收",
            "明月",
            "灵符",
            "金元宝",
        ):
            self.assertNotIn(forbidden, script)

    def test_readme_discloses_candidate_scope_and_interfaces(self):
        text = (
            platform_root()
            / "packages"
            / "verified"
            / PACKAGE_ID
            / "README_使用说明.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "@快捷回收",
            "@XY_RECYCLE_COMMAND",
            "12项精确白名单",
            "每种最多10件",
            "每件1000金币",
            "不自动回收",
            "verified",
            "游戏内验收",
        ):
            self.assertIn(phrase, text)

    def test_preflight_install_idempotency_conflict_and_byte_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            server = self.make_server(root)
            before = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file()
            }
            repository = PackageRepository(platform_root() / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            plan = installer.preflight(server, [PACKAGE_ID], {})
            self.assertEqual(
                {item.relative_path for item in plan.changes},
                {
                    "Mir200/Envir/UserCmd.txt",
                    "Mir200/Envir/Market_Def/QFunction-0.txt",
                },
            )
            receipt = installer.install(plan)
            self.assertEqual(installer.preflight(server, [PACKAGE_ID], {}).changes, [])
            installer.rollback(server, receipt.transaction_id)
            after = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)

            (server / "Mir200/Envir/UserCmd.txt").write_text(
                "快捷回收\t99\r\n", encoding="gb18030"
            )
            with self.assertRaisesRegex(Exception, "唯一键冲突"):
                installer.preflight(server, [PACKAGE_ID], {})

if __name__ == "__main__":
    unittest.main()
