from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


PACKAGE_ID = "xy.optional.bag.function-service"
DEPENDENCY_ID = "xy.optional.recycle.drop-filter"


class BagFunctionServicePackageTests(unittest.TestCase):
    def package(self):
        return validate_package(
            platform_root() / "packages" / "candidate" / PACKAGE_ID
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
        qfunction = (
            "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n\r\n"
            "[@CustomButtonClick]\r\n"
            "#IF\r\nEQUAL <$CustomButtonID> 20\r\n"
            "#ACT\r\nOpenStorageView 1\r\nBREAK\r\n\r\n"
            "#IF\r\nEQUAL <$CustomButtonID> 21\r\n"
            "#ACT\r\nGOTO @XY_RECYCLE_COMMAND\r\nBREAK\r\n"
            "\r\n[@XY_COLLECTION_COMMAND]\r\n"
            "#IF\r\n#ACT\r\nBREAK\r\n"
        )
        (market / "QFunction-0.txt").write_bytes(qfunction.encode("gb18030"))
        return server

    def test_manifest_owns_button_23_menu_and_reuses_filter_dependency(self):
        package = self.package()
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.version, "1.0.0-candidate.2")
        self.assertEqual(package.residency, "optional")
        self.assertEqual(package.dependencies, (DEPENDENCY_ID,))
        self.assertEqual(
            package.claims["labels"], ["XY_BAG_FUNCTION_SERVICE_PANEL"]
        )
        self.assertEqual(
            [operation["type"] for operation in package.operations],
            ["ensure_event_label", "event_hook", "managed_block"],
        )
        hook = package.operations[1]["content"]
        panel = package.operations[2]["content"]
        self.assertIn("EQUAL <$CustomButtonID> 23", hook)
        self.assertIn("GOTO @XY_BAG_FUNCTION_SERVICE_PANEL", hook)
        for other_id in (20, 21, 22, 24):
            self.assertNotIn(f"<$CustomButtonID> {other_id}", hook)
        self.assertIn("@XY_RECYCLE_DROP_FILTER_ENABLE", panel)
        self.assertIn("@XY_RECYCLE_DROP_FILTER_DISABLE", panel)
        self.assertIn("<装备收集/@XY_COLLECTION_COMMAND>", panel)
        self.assertNotIn("FILTERGLOBALMSG", panel)
        self.assertIn(
            {
                "type": "label_exists",
                "path": "Mir200/Envir/Market_Def/QFunction-0.txt",
                "label": "XY_COLLECTION_COMMAND",
            },
            package.preflight_checks,
        )

    def test_preflight_blocks_when_collection_entry_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            server = self.make_server(root)
            qfunction = server / "Mir200/Envir/Market_Def/QFunction-0.txt"
            text = qfunction.read_text(encoding="gb18030")
            qfunction.write_text(
                text.replace("\n[@XY_COLLECTION_COMMAND]\n#IF\n#ACT\nBREAK\n", ""),
                encoding="gb18030",
                newline="",
            )
            repository = PackageRepository(platform_root() / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            with self.assertRaisesRegex(InstallError, "标签不存在: XY_COLLECTION_COMMAND"):
                installer.preflight(server, [PACKAGE_ID], {})

    def test_install_preserves_buttons_20_21_and_is_idempotent_and_reversible(self):
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
            self.assertEqual(set(plan.package_ids), {DEPENDENCY_ID, PACKAGE_ID})
            receipt = installer.install(plan)
            text = (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_text(
                encoding="gb18030"
            )
            self.assertEqual(text.count("[@CustomButtonClick]"), 1)
            for button_id in (20, 21, 23):
                self.assertEqual(text.count(f"EQUAL <$CustomButtonID> {button_id}"), 1)
            self.assertEqual(text.count("[@XY_BAG_FUNCTION_SERVICE_PANEL]"), 1)
            self.assertEqual(text.count("FILTERGLOBALMSG 1 1"), 1)
            self.assertEqual(text.count("FILTERGLOBALMSG 1 0"), 1)
            self.assertEqual(installer.preflight(server, [PACKAGE_ID], {}).changes, [])

            installer.rollback(server, receipt.transaction_id)
            after = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
