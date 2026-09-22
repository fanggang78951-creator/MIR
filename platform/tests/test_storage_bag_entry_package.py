from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


PACKAGE_ID = "xy.optional.storage.bag-entry"


class StorageBagEntryPackageTests(unittest.TestCase):
    def package(self):
        return validate_package(
            platform_root() / "packages" / "candidate" / PACKAGE_ID
        )

    def make_server(self, root: Path, *, existing_button_21: bool = False) -> Path:
        server = root / "server"
        envir = server / "Mir200" / "Envir"
        market = envir / "Market_Def"
        market.mkdir(parents=True)
        (server / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (server / "Mud2" / "DB").mkdir(parents=True)
        (server / "Mud2" / "DB" / "StdItems.DB").write_bytes(b"fixture")
        (envir / "MapInfo.txt").write_text("[0 盟重]\r\n", encoding="gb18030")
        (envir / "MerChant.txt").write_bytes(b"")
        qfunction = "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        if existing_button_21:
            qfunction += (
                "\r\n[@CustomButtonClick]\r\n"
                "#IF\r\nEQUAL <$CustomButtonID> 21\r\n"
                "#ACT\r\nGOTO @XY_RECYCLE_COMMAND\r\nBREAK\r\n"
            )
        (market / "QFunction-0.txt").write_bytes(qfunction.encode("gb18030"))
        return server

    def test_manifest_owns_only_button_20_infinite_storage_entry(self):
        package = self.package()
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.version, "1.0.0-candidate.1")
        self.assertEqual(package.residency, "optional")
        self.assertEqual(package.dependencies, ())
        self.assertTrue(all(not values for values in package.claims.values()))
        self.assertEqual(
            [operation["type"] for operation in package.operations],
            ["ensure_event_label", "event_hook"],
        )
        hook = package.operations[1]
        self.assertEqual(hook["label"], "CustomButtonClick")
        self.assertIn("EQUAL <$CustomButtonID> 20", hook["content"])
        self.assertIn("OpenStorageView 1", hook["content"])
        self.assertNotIn("OpenStorageView 0", hook["content"])
        for other_id in (21, 22, 23, 24):
            self.assertNotIn(f"<$CustomButtonID> {other_id}", hook["content"])
        for forbidden in ("@bigstorage", "@biggetback", "#CALL", "GOTO"):
            self.assertNotIn(forbidden, hook["content"])

    def test_install_creates_event_is_idempotent_and_reversible(self):
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
            self.assertEqual(plan.package_ids, [PACKAGE_ID])
            receipt = installer.install(plan)
            text = (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_text(
                encoding="gb18030"
            )
            self.assertEqual(text.count("[@CustomButtonClick]"), 1)
            self.assertEqual(text.count("EQUAL <$CustomButtonID> 20"), 1)
            self.assertEqual(text.count("OpenStorageView 1"), 1)
            self.assertEqual(installer.preflight(server, [PACKAGE_ID], {}).changes, [])

            installer.rollback(server, receipt.transaction_id)
            after = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)

    def test_existing_button_21_handler_survives_button_20_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            server = self.make_server(root, existing_button_21=True)
            repository = PackageRepository(platform_root() / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")
            receipt = installer.install(installer.preflight(server, [PACKAGE_ID], {}))
            text = (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_text(
                encoding="gb18030"
            )
            self.assertIn("EQUAL <$CustomButtonID> 21", text)
            self.assertIn("GOTO @XY_RECYCLE_COMMAND", text)
            self.assertIn("EQUAL <$CustomButtonID> 20", text)
            self.assertIn("OpenStorageView 1", text)
            installer.rollback(server, receipt.transaction_id)


if __name__ == "__main__":
    unittest.main()
