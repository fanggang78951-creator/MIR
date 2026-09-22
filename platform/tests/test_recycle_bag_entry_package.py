from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


PACKAGE_ID = "xy.optional.recycle.bag-entry"


class RecycleBagEntryPackageTests(unittest.TestCase):
    def package(self):
        return validate_package(
            platform_root() / "packages" / "candidate" / PACKAGE_ID
        )

    def make_server(self, root: Path, *, existing_event: bool = False) -> Path:
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
        qfunction = "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        if existing_event:
            qfunction += (
                "\r\n[@CustomButtonClick]\r\n"
                "#IF\r\nEQUAL <$CustomButtonID> 20\r\n"
                "#ACT\r\nSENDMSG 6 仓库入口\r\nBREAK\r\n"
            )
        (market / "QFunction-0.txt").write_bytes(qfunction.encode("gb18030"))
        return server

    def test_manifest_owns_only_button_21_entry(self):
        package = self.package()
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.version, "1.0.0-candidate.1")
        self.assertEqual(package.residency, "optional")
        self.assertEqual(package.dependencies, ("xy.optional.recycle.core",))
        self.assertTrue(all(not values for values in package.claims.values()))
        self.assertEqual(
            [operation["type"] for operation in package.operations],
            ["ensure_event_label", "event_hook"],
        )
        hook = package.operations[1]
        self.assertEqual(hook["label"], "CustomButtonClick")
        self.assertIn("EQUAL <$CustomButtonID> 21", hook["content"])
        self.assertIn("GOTO @XY_RECYCLE_COMMAND", hook["content"])
        for other_id in (20, 22, 23, 24):
            self.assertNotIn(f"<$CustomButtonID> {other_id}", hook["content"])
        for forbidden in ("CHECKITEM", "TAKE ", "GIVE ", "#CALL"):
            self.assertNotIn(forbidden, hook["content"])

    def test_install_creates_event_and_is_idempotent_and_reversible(self):
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
                set(plan.package_ids),
                {"xy.optional.recycle.core", PACKAGE_ID},
            )
            receipt = installer.install(plan)
            text = (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_text(
                encoding="gb18030"
            )
            self.assertEqual(text.count("[@CustomButtonClick]"), 1)
            self.assertEqual(text.count("EQUAL <$CustomButtonID> 21"), 1)
            self.assertEqual(text.count("GOTO @XY_RECYCLE_COMMAND"), 2)
            self.assertEqual(installer.preflight(server, [PACKAGE_ID], {}).changes, [])

            installer.rollback(server, receipt.transaction_id)
            after = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)

    def test_existing_button_20_handler_survives_button_21_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            server = self.make_server(root, existing_event=True)
            repository = PackageRepository(platform_root() / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")
            receipt = installer.install(installer.preflight(server, [PACKAGE_ID], {}))
            text = (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_text(
                encoding="gb18030"
            )
            self.assertIn("EQUAL <$CustomButtonID> 20", text)
            self.assertIn("SENDMSG 6 仓库入口", text)
            self.assertIn("EQUAL <$CustomButtonID> 21", text)
            installer.rollback(server, receipt.transaction_id)


if __name__ == "__main__":
    unittest.main()
